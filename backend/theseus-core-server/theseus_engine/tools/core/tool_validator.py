import ast
import importlib.util
import inspect
import os
from typing import Dict, List, Optional, Set, Tuple, Type

from pydantic import BaseModel
from theseus_engine.tools.core.base_tools import BaseTool
from theseus_engine.tools.core.tool_creation import (
    ToolCreationError,
    normalize_tool_name,
    inject_permission_level,
)


class ToolValidator:
    """자연어 요청으로 생성된 Tool 코드가 Theseus 규격에 맞는지 검증합니다.

    검증 항목:
    - 파이썬 문법(Syntax) 검사
    - BaseTool / BaseModel 참조 존재 여부
    - execute 메소드 시그니처: (self, arguments, context) 3개 인자
    - ToolResult 올바른 사용법: output/is_error 키워드만 허용
    - context.input_model 안티패턴 감지
    - 보안 위반 검사: AnalysisValidator 위임 (AST 정적 분석)
    """

    @classmethod
    def validate_code(cls, code: str) -> Tuple[bool, str]:
        """파이썬 코드의 문법과 Theseus 구조 규칙을 AST로 검사합니다."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"Syntax Error: {e}"

        if "BaseTool" not in code or "BaseModel" not in code:
            return False, (
                "Code must import and use both BaseTool and BaseModel. "
                "Neither was found in the provided code."
            )

        # AST에서 BaseTool 상속 클래스 탐색
        errors: List[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            # BaseTool을 상속하는 클래스인지 확인
            base_names = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    base_names.append(base.id)
                elif isinstance(base, ast.Attribute):
                    base_names.append(base.attr)
            if "BaseTool" not in base_names:
                continue

            # execute 메소드 시그니처 검증
            cls._check_execute_signature(node, errors)

        # ToolResult 잘못된 사용 패턴 탐지
        cls._check_tool_result_usage(tree, errors)

        # context.input_model 안티패턴 탐지
        cls._check_context_input_model(tree, errors)

        # 입력 모델 클래스명 화이트리스트 검증
        cls._check_input_model_naming(tree, errors)

        # 보안 위반 검사: AnalysisValidator에 위임
        from theseus_engine.validators.analysis_validator import (
            AnalysisValidator,
        )

        security_ok, security_msg = AnalysisValidator.validate(code)
        if not security_ok:
            errors.append(security_msg)

        if errors:
            return False, (
                "Theseus tool specification violations detected:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        return True, "Code syntax and structure validation passed."

    @classmethod
    def _check_execute_signature(
        cls,
        class_node: ast.ClassDef,
        errors: List[str],
    ) -> None:
        """execute 메소드의 인자가 (self, arguments, context)인지 검증합니다."""
        for item in class_node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name != "execute":
                continue

            args = item.args
            # posonlyargs + args 합산 (self 포함 3개여야 함)
            all_args = list(args.posonlyargs) + list(args.args)
            arg_names = [a.arg for a in all_args]

            if len(arg_names) != 3:
                errors.append(
                    f"'{class_node.name}.execute()' has {len(arg_names)} arguments. "
                    f"Required signature: execute(self, arguments: <InputModel>, "
                    f"context: ToolExecutionContext) — exactly 3 arguments required."
                )
                return

            if arg_names[0] != "self":
                errors.append(
                    f"'{class_node.name}.execute()' first argument must be "
                    f"'self'. (found: '{arg_names[0]}')"
                )
            if arg_names[1] not in ("arguments", "args", "params", "input"):
                errors.append(
                    f"'{class_node.name}.execute()' second argument should receive "
                    f"the parsed input model (recommended: 'arguments'). "
                    f"(found: '{arg_names[1]}')"
                )
            if arg_names[2] != "context":
                errors.append(
                    f"'{class_node.name}.execute()' third argument must be "
                    f"'context'. (found: '{arg_names[2]}')"
                )
            return

        errors.append(
            f"Class '{class_node.name}' is missing the required " f"'execute' method definition."
        )

    @classmethod
    def _check_tool_result_usage(
        cls,
        tree: ast.Module,
        errors: List[str],
    ) -> None:
        """ToolResult의 잘못된 사용 패턴을 감지합니다.

        감지 대상:
        - ToolResult.from_error(...)  → 존재하지 않는 클래스 메소드
        - ToolResult(status=..., data=..., message=...)
            → 올바른 키워드는 output, is_error, metadata 뿐
        """
        VALID_KEYWORDS = {"output", "is_error", "metadata"}

        for node in ast.walk(tree):
            # ToolResult.from_error(...) 패턴 감지
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "ToolResult"
                    and func.attr == "from_error"
                ):
                    errors.append(
                        "ToolResult.from_error() does not exist. "
                        "Use ToolResult(output=..., is_error=True) instead."
                    )

                # ToolResult(...) 호출 시 키워드 검사
                if isinstance(func, ast.Name) and func.id == "ToolResult":
                    invalid_kws = [
                        kw.arg
                        for kw in node.keywords
                        if kw.arg is not None and kw.arg not in VALID_KEYWORDS
                    ]
                    if invalid_kws:
                        errors.append(
                            f"ToolResult() received invalid keyword "
                            f"arguments: {', '.join(invalid_kws)}. "
                            f"Allowed keywords: {', '.join(sorted(VALID_KEYWORDS))}"
                        )

    @classmethod
    def _check_context_input_model(
        cls,
        tree: ast.Module,
        errors: List[str],
    ) -> None:
        """context.input_model 안티패턴을 감지합니다.

        Theseus에서 입력 데이터는 execute의 arguments 인자로
        전달되며, context.input_model은 존재하지 않습니다.
        """
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "input_model"
                and isinstance(node.value, ast.Name)
                and node.value.id == "context"
            ):
                errors.append(
                    "context.input_model does not exist. "
                    "Input data is passed as the 'arguments' parameter in "
                    "execute(self, arguments, context)."
                )
                break  # 한 번만 보고

    @classmethod
    def _check_input_model_naming(
        cls,
        tree: ast.Module,
        errors: List[str],
    ) -> None:
        """input_model에 실제 할당된 입력 모델 이름만 검증합니다.

        기존 Core Tool들은 대부분 ``ReadFileTool -> ReadFileInput``처럼
        Tool suffix를 제거한 이름을 사용합니다. generated tool에서는
        ``ReadFileToolInput`` 형태도 함께 허용합니다. ``ProcessInfo``나
        ``CPUStatsOutput`` 같은 보조 Pydantic 모델은 입력 모델이 아니므로
        이 검증 대상에서 제외합니다.
        """
        base_model_names: Set[str] = set()
        tool_input_models: Dict[str, str] = {}

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = [b.id for b in node.bases if isinstance(b, ast.Name)]
            if "BaseModel" in base_names:
                base_model_names.add(node.name)
            if "BaseTool" not in base_names:
                continue

            input_model_name = cls._extract_declared_input_model_name(node)
            if input_model_name:
                tool_input_models[node.name] = input_model_name

        for tool_class_name, input_model_name in tool_input_models.items():
            if input_model_name not in base_model_names:
                errors.append(
                    f"'{tool_class_name}.input_model' references "
                    f"'{input_model_name}', but no matching BaseModel class "
                    f"was found in the module."
                )
                continue

            tool_stem = (
                tool_class_name[:-4] if tool_class_name.endswith("Tool") else tool_class_name
            )
            allowed = {f"{tool_class_name}Input", f"{tool_stem}Input"}
            if input_model_name not in allowed:
                errors.append(
                    f"Input model for '{tool_class_name}' should be named "
                    f"'{tool_stem}Input' or '{tool_class_name}Input'. "
                    f"(found: '{input_model_name}')"
                )

    @staticmethod
    def _extract_declared_input_model_name(class_node: ast.ClassDef) -> str | None:
        """Return the class name assigned to a BaseTool's input_model attr."""
        for item in class_node.body:
            if isinstance(item, ast.Assign):
                if not any(
                    isinstance(target, ast.Name) and target.id == "input_model"
                    for target in item.targets
                ):
                    continue
                if isinstance(item.value, ast.Name):
                    return item.value.id
            if isinstance(item, ast.AnnAssign):
                if not (
                    isinstance(item.target, ast.Name)
                    and item.target.id == "input_model"
                    and isinstance(item.value, ast.Name)
                ):
                    continue
                return item.value.id
        return None

    # ------------------------------------------------------------------
    # 2단계: 모듈 로드 및 런타임 규격 검증
    # ------------------------------------------------------------------

    @classmethod
    def validate_and_load_module(
        cls, module_name: str, file_path: str
    ) -> Tuple[bool, str, Optional[Type[BaseTool]]]:
        """모듈을 동적으로 로드하고 BaseTool 규격을 완벽히 준수하는지 검증합니다."""
        if not os.path.exists(file_path):
            return False, "File does not exist.", None

        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if not spec or not spec.loader:
            return False, "Failed to load module spec.", None

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            return False, f"Error during module execution: {e}", None

        # BaseTool을 상속받은 클래스 탐색
        tool_classes = []
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseTool) and obj is not BaseTool:
                tool_classes.append(obj)

        if not tool_classes:
            return False, "No class inheriting from BaseTool was found.", None

        tool_class = tool_classes[0]  # 첫 번째 발견된 툴 클래스 사용

        # Theseus 필수 속성(name, description, input_model) 검증
        if not hasattr(tool_class, "name") or not getattr(tool_class, "name"):
            return False, "Tool class is missing the 'name' attribute or it is empty.", None
        if not hasattr(tool_class, "description") or not getattr(tool_class, "description"):
            return False, "Tool class is missing the 'description' attribute or it is empty.", None
        if not hasattr(tool_class, "input_model") or not issubclass(
            tool_class.input_model, BaseModel
        ):
            return (
                False,
                "Tool class is missing 'input_model' or it is not a subclass of BaseModel.",
                None,
            )

        # execute 메소드 런타임 시그니처 검증
        execute_method = getattr(tool_class, "execute", None)
        if execute_method is None:
            return False, "The 'execute' method is not defined.", None

        sig = inspect.signature(execute_method)
        params = list(sig.parameters.keys())
        # 바운드 메소드면 self 제외, 언바운드면 self 포함
        if params and params[0] == "self":
            params = params[1:]
        if len(params) != 2:
            return (
                False,
                f"execute method has incorrect signature. "
                f"({len(params)} args excluding self). "
                f"Required: execute(self, arguments, context)",
                None,
            )

        return True, f"Validation passed: tool '{tool_class.name}' loaded successfully.", tool_class
