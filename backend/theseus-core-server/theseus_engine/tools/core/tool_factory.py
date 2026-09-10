"""Theseus Meta-Tooling: Custom tool creation, validation, and dynamic loading module.

This module provides three core capabilities:
1. ToolValidator: Syntax and Theseus tool specification compliance validation
2. load_custom_tools: Auto-scan and register tools from the custom_tools/ directory
3. ToolCreatorTool: LLM-callable meta-tool to create new tools and inject them into the registry
"""

import os
import re
import json
import logging
import inspect
import importlib.util
from datetime import datetime, timezone
from typing import Any, Dict, Tuple, Type, Optional, List, Set

from pydantic import BaseModel, Field, field_validator
from theseus_engine.tools.core.tool_validator import ToolValidator
from theseus_engine.tools.core.base_tools import (
    BaseTool,
    ToolExecutionContext,
    ToolResult,
    ToolRegistry,
)
from theseus_engine.tools.core.custom_tool_paths import (
    CUSTOM_TOOLS_DIR,
    PROJECT_CUSTOM_TOOLS_DIR,
    canonical_tool_module_stem,
    custom_tool_dirs as _custom_tool_dirs,
    get_custom_tools_dir,
    get_project_custom_tools_dir,
)
from theseus_engine.tools.core.tool_server_adapter import (
    create_tool_via_server,
    resolve_server_create_tool_context,
)
from theseus_engine.tools.tool_repair import (
    COMMON_CUSTOM_TOOL_SECURITY_RULES,
    ToolRepairFailure,
    ToolRepairLoop,
    ToolRepairPolicy,
)

log = logging.getLogger(__name__)

# Default permission level for tools without explicit permission_level
DEFAULT_PERMISSION_LEVEL = 1
MIN_PERMISSION_LEVEL = 1
MAX_PERMISSION_LEVEL = 5
_CUSTOM_TOOL_LOAD_WARNING_KEYS: Set[str] = set()


def _coerce_permission_level(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("permissionLevel must be an integer from 1 to 5.")
    if isinstance(value, int):
        level = value
    elif isinstance(value, str) and value.strip().isdigit():
        level = int(value.strip())
    else:
        raise ValueError("permissionLevel must be an integer from 1 to 5.")
    if not (MIN_PERMISSION_LEVEL <= level <= MAX_PERMISSION_LEVEL):
        raise ValueError("permissionLevel must be an integer from 1 to 5.")
    return level


MISSING_MODULE_PACKAGE_ALIASES = {
    "pynvml": "nvidia-ml-py",
    "speedtest": "speedtest-cli",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "yaml": "PyYAML",
}
MISSING_MODULE_INSTALL_DENYLIST = {"theseus_engine", "src"}


def _safe_dependency_name(value: Any) -> str | None:
    name = str(value or "").strip()
    if not name:
        return None
    if name in MISSING_MODULE_INSTALL_DENYLIST:
        return None
    if re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        return name
    return None


def _extract_missing_modules(message: str) -> List[str]:
    modules: List[str] = []
    for match in re.finditer(r"No module named ['\"]([^'\"]+)['\"]", message):
        module_name = match.group(1).split(".", 1)[0].strip()
        if module_name and module_name not in modules:
            modules.append(module_name)
    return modules


def _install_candidates(
    *,
    dependencies: List[str],
    missing_modules: List[str],
) -> List[str]:
    if dependencies:
        return dependencies
    candidates: List[str] = []
    for module_name in missing_modules:
        candidate = MISSING_MODULE_PACKAGE_ALIASES.get(module_name, module_name)
        safe = _safe_dependency_name(candidate)
        if safe and safe not in candidates:
            candidates.append(safe)
    return candidates


def _custom_tool_log_dedup_key(file_path: str, message: str) -> str:
    return f"{os.path.normcase(os.path.abspath(file_path))}:{message}"


def _log_custom_tool_load_warning(file_path: str, message: str) -> str:
    """Log each custom-tool load failure once per process lifetime.

    Import-failed custom tools are recoverable inventory entries. Repeating the
    same warning on every registry refresh makes local daemon startup look like
    a daemon/server failure, so subsequent identical failures are debug-only.
    """

    key = _custom_tool_log_dedup_key(file_path, message)
    if key in _CUSTOM_TOOL_LOAD_WARNING_KEYS:
        log.debug("Skipped invalid custom tool %s: %s", file_path, message)
    else:
        _CUSTOM_TOOL_LOAD_WARNING_KEYS.add(key)
        log.warning("Skipped invalid custom tool %s: %s", file_path, message)
    return key


def _path_within(path: str, root: str) -> bool:
    try:
        normalized_path = os.path.abspath(path)
        normalized_root = os.path.abspath(root)
        return os.path.commonpath([normalized_path, normalized_root]) == normalized_root
    except (OSError, ValueError):
        return False


def _is_project_custom_tool_dir(path: str) -> bool:
    project_root = get_project_custom_tools_dir()
    return _path_within(path, project_root)


def _metadata_requires_sandbox(meta: Dict[str, Any]) -> bool:
    project_id = str(meta.get("projectId") or "").strip()
    return bool(meta) and project_id not in {"", "local"}


def _metadata_is_sandbox_verified(meta: Dict[str, Any]) -> bool:
    validation = meta.get("validationResult") or {}
    sandbox = meta.get("sandboxResult") or {}
    return (
        meta.get("status") == "active"
        and bool(meta.get("isActive"))
        and bool(validation.get("success"))
        and bool(sandbox.get("success"))
    )


def _sanitize_generated_code(code: str) -> str:
    r"""LLM이 생성한 코드에서 파이썬 파싱을 망가뜨리는 오염 패턴을 제거합니다.

    주요 처리 항목
    ──────────────
    1. 백슬래시 + 후행 공백(trailing whitespace after line continuation)
       원인: LLM이 멀티라인 문자열을 JSON으로 직렬화할 때 ``\\n`` → ``\n`` 변환 후
             실제 개행 앞뒤에 공백이 붙어 ``\\ <space>`` 패턴이 생기는 경우.
             파이썬은 ``\`` 뒤에 공백이 있으면 SyntaxError를 발생시킴.
       처리: ``\\ `` (백슬래시 + 스페이스) → 백슬래시만 남김.

    2. Windows CRLF → LF 정규화
       원인: 일부 모델이 \\r\\n 라인 엔딩을 포함한 코드를 생성.

    3. NULL 바이트 제거
       원인: 바이너리 혼입 시 파서 충돌.

    4. 마크다운 코드펜스 제거
       원인: LLM이 ``python_code`` 인자에 ```python ... ``` 블록째로 넣는 경우.
    """
    # 4. 마크다운 코드펜스 벗기기 (```python ... ``` 또는 ``` ... ```)
    fence_match = re.match(r"^\s*```(?:python)?\s*\n(.*?)\n\s*```\s*$", code, re.DOTALL)
    if fence_match:
        code = fence_match.group(1)

    # 2. CRLF → LF
    code = code.replace("\r\n", "\n").replace("\r", "\n")

    # 3. NULL 바이트 제거
    code = code.replace("\x00", "")

    # 1. 백슬래시 뒤에 공백만 있는 줄 끝 정리
    #    ``\ `` or ``\  `` (여러 공백) → ``\``
    code = re.sub(r"\\ +\n", "\\\n", code)
    #    줄 끝이 아닌 위치의 ``\ `` 패턴 (인라인 line continuation 오염)
    #    예: return value1 \  +  value2  → return value1 \+  value2 (불완전)
    #    → 여기서는 보수적으로 줄 끝 패턴만 처리하고 인라인은 건드리지 않음

    return code


# ---------------------------------------------------------------------------
# Dynamic Tool Loader
# ---------------------------------------------------------------------------


def normalize_tool_meta(
    meta_path: str,
    tool_class: Any,
    module_name: str,
) -> None:
    """meta.json을 정규(canonical) 스키마로 정규화하고 재저장합니다.

    LLM이 edit_file/write_file로 meta.json을 직접 수정하면 키 이름·구조가
    어긋날 수 있습니다. 이 함수는 기존 파일을 읽어 누락 필드를 채우고
    잘못된 키를 canonical 키로 교정한 뒤 덮어씁니다.

    Canonical schema:
        toolName, moduleName, projectId, chatSessionId, creatorUserId,
        planId, fileName, createdAt, updatedAt, permissionLevel,
        status, isActive, validationResult
    """
    now = datetime.now(timezone.utc).isoformat()
    tool_name = getattr(tool_class, "name", module_name)
    permission_level = getattr(tool_class, "permission_level", DEFAULT_PERMISSION_LEVEL)

    # 기존 파일 로드 (없으면 빈 dict)
    existing: Dict[str, Any] = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # 잘못된 키 → canonical 키 매핑
    _key_aliases = {
        "name": "toolName",
        "tool_name": "toolName",
        "module_name": "moduleName",
        "input_model": None,  # meta에 불필요 — 제거
        "description": None,  # .py에서 읽어야 함 — meta에서 제거
        "permission_level": "permissionLevel",
    }
    normalized: Dict[str, Any] = {}
    for k, v in existing.items():
        canonical = _key_aliases.get(k, k)  # 없으면 그대로
        if canonical is not None:
            normalized[canonical] = v

    # 필수 필드 채우기 (py 클래스가 source of truth)
    canonical_meta: Dict[str, Any] = {
        "toolName": tool_name,
        "moduleName": module_name,
        "projectId": normalized.get("projectId", "local"),
        "chatSessionId": normalized.get("chatSessionId"),
        "creatorUserId": normalized.get("creatorUserId", "cli_user"),
        "planId": normalized.get("planId"),
        "fileName": f"{module_name}.py",
        "createdAt": normalized.get("createdAt", now),
        "updatedAt": now,
        "permissionLevel": permission_level,
        "status": normalized.get("status", "active"),
        "isActive": normalized.get("isActive", True),
        "sandboxVerified": normalized.get("sandboxVerified", False),
        "activationSource": normalized.get("activationSource", "standalone_without_sandbox"),
        "validationResult": normalized.get("validationResult")
        or {
            "success": True,
            "status": "validated",
            "message": "Normalized by load_custom_tools.",
            "checkedAt": now,
        },
        "runtimeMode": normalized.get("runtimeMode", "standalone"),
    }

    # 변경이 없으면 쓰지 않음 (updatedAt 제외 비교)
    compare_existing = {k: v for k, v in existing.items() if k != "updatedAt"}
    compare_new = {k: v for k, v in canonical_meta.items() if k != "updatedAt"}
    if compare_existing == compare_new:
        return

    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(canonical_meta, f, ensure_ascii=False, indent=2)
        log.info("[MetaNorm] Normalized meta: %s", meta_path)
    except OSError as e:
        log.warning("[MetaNorm] Failed to write normalized meta %s: %s", meta_path, e)


def _read_tool_meta(meta_path: str) -> Dict[str, Any]:
    try:
        with open(meta_path, encoding="utf-8") as f:
            parsed = json.load(f)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _iter_inventory_dirs(
    extra_dirs: Optional[List[str | os.PathLike[str]]] = None,
) -> List[str]:
    dirs: List[str] = []
    seen: Set[str] = set()
    for base in _custom_tool_dirs(extra_dirs):
        candidates = [base]
        projects_dir = os.path.join(base, "projects")
        if os.path.isdir(projects_dir):
            candidates.extend(
                os.path.join(projects_dir, name)
                for name in sorted(os.listdir(projects_dir))
                if os.path.isdir(os.path.join(projects_dir, name))
            )
        for candidate in candidates:
            key = os.path.normcase(os.path.abspath(candidate))
            if key in seen:
                continue
            seen.add(key)
            dirs.append(os.path.abspath(candidate))
    return dirs


def _inventory_candidate_from_meta(
    custom_tools_dir: str,
    meta_file: str,
) -> Tuple[str, str, str, Dict[str, Any]]:
    meta_path = os.path.join(custom_tools_dir, meta_file)
    meta = _read_tool_meta(meta_path)
    fallback_stem = meta_file.removesuffix(".meta.json")
    file_name = str(meta.get("fileName") or f"{fallback_stem}.py")
    file_name = os.path.basename(file_name)
    if not file_name.endswith(".py"):
        file_name = f"{fallback_stem}.py"
    module_name = str(meta.get("moduleName") or file_name[:-3]).strip() or file_name[:-3]
    return module_name, os.path.join(custom_tools_dir, file_name), meta_path, meta


def _base_tool_inventory_item(
    *,
    module_name: str,
    file_path: str,
    meta_path: str | None,
    meta: Dict[str, Any] | None,
) -> Dict[str, Any]:
    meta = meta or {}
    dependencies = [
        dep
        for dep in (_safe_dependency_name(item) for item in meta.get("dependencies", []) or [])
        if dep
    ]
    fallback_name = os.path.splitext(os.path.basename(file_path))[0]
    item: Dict[str, Any] = {
        "toolName": str(meta.get("toolName") or fallback_name),
        "fileName": os.path.basename(file_path),
        "moduleName": module_name,
        "modulePath": os.path.abspath(file_path),
        "metadataPath": os.path.abspath(meta_path) if meta_path else "",
        "permissionLevel": meta.get("permissionLevel", ""),
        "status": str(meta.get("status") or "unknown"),
        "isActive": bool(meta.get("isActive", True)),
        "validationSuccess": bool((meta.get("validationResult") or {}).get("success")),
        "sandboxVerified": bool((meta.get("sandboxResult") or {}).get("success")),
        "sandboxResult": meta.get("sandboxResult") or {},
        "activationSource": meta.get("activationSource"),
        "dependencies": dependencies,
        "missingModules": [],
        "installCandidates": [],
        "importError": "",
        "loadState": "available",
        "canInstall": False,
        "canRegister": False,
        "canEditSource": False,
    }

    return item


def _mark_tool_inventory_inactive(
    item: Dict[str, Any],
    message: str = "",
) -> Dict[str, Any]:
    item["loadState"] = "inactive"
    item["canInstall"] = False
    item["canRegister"] = False
    if message:
        item["importError"] = message
    return item


def _mark_tool_inventory_unavailable(
    item: Dict[str, Any],
    message: str,
) -> Dict[str, Any]:
    missing_modules = _extract_missing_modules(message)
    install_candidates = _install_candidates(
        dependencies=list(item.get("dependencies") or []),
        missing_modules=missing_modules,
    )
    item["loadState"] = "unavailable"
    item["importError"] = message
    item["logDedupKey"] = _custom_tool_log_dedup_key(
        str(item.get("modulePath") or item.get("fileName") or ""),
        message,
    )
    item["missingModules"] = missing_modules
    item["installCandidates"] = install_candidates
    item["canInstall"] = bool(install_candidates)
    item["canRegister"] = False
    return item


def _log_unavailable_inventory_item(item: Dict[str, Any]) -> None:
    if item.get("loadState") != "unavailable":
        return
    message = str(item.get("importError") or "").strip()
    file_path = str(item.get("modulePath") or "").strip()
    if not message or not file_path:
        return
    item["logDedupKey"] = _log_custom_tool_load_warning(file_path, message)


def _evaluate_tool_inventory_item(
    *,
    module_name: str,
    file_path: str,
    meta_path: str | None,
    meta: Dict[str, Any] | None,
) -> Tuple[Dict[str, Any], Type[BaseTool] | None]:
    meta = meta or {}
    item = _base_tool_inventory_item(
        module_name=module_name,
        file_path=file_path,
        meta_path=meta_path,
        meta=meta,
    )

    if not item["isActive"] or item["status"] not in {"unknown", "active"}:
        return _mark_tool_inventory_inactive(item), None
    if _metadata_requires_sandbox(meta) and not _metadata_is_sandbox_verified(meta):
        return (
            _mark_tool_inventory_inactive(
                item,
                "Project custom tool is not sandbox verified.",
            ),
            None,
        )

    if not os.path.exists(file_path):
        return (
            _mark_tool_inventory_unavailable(
                item,
                f"Missing module file: {os.path.basename(file_path)}",
            ),
            None,
        )

    is_valid, msg, tool_class = ToolValidator.validate_and_load_module(
        module_name,
        file_path,
    )
    if not is_valid or tool_class is None:
        return _mark_tool_inventory_unavailable(item, msg), None

    item["toolName"] = getattr(tool_class, "name", item["toolName"])
    item["permissionLevel"] = getattr(
        tool_class,
        "permission_level",
        item["permissionLevel"] or DEFAULT_PERMISSION_LEVEL,
    )
    item["status"] = "active"
    item["canRegister"] = True
    item["canEditSource"] = item["sandboxVerified"]
    return item, tool_class


def _tool_inventory_item(
    *,
    module_name: str,
    file_path: str,
    meta_path: str | None,
    meta: Dict[str, Any] | None,
) -> Dict[str, Any]:
    item, _tool_class = _evaluate_tool_inventory_item(
        module_name=module_name,
        file_path=file_path,
        meta_path=meta_path,
        meta=meta,
    )
    return item


def scan_custom_tool_inventory(
    extra_dirs: Optional[List[str | os.PathLike[str]]] = None,
) -> List[Dict[str, Any]]:
    """Return loadable and unavailable custom tools without mutating a registry."""
    inventory: List[Dict[str, Any]] = []
    seen_files: Set[str] = set()

    for custom_tools_dir in _iter_inventory_dirs(extra_dirs):
        if not os.path.isdir(custom_tools_dir):
            continue

        meta_files = sorted(
            filename
            for filename in os.listdir(custom_tools_dir)
            if filename.endswith(".meta.json") and not filename.startswith("_")
        )
        for meta_file in meta_files:
            module_name, file_path, meta_path, meta = _inventory_candidate_from_meta(
                custom_tools_dir,
                meta_file,
            )
            seen_files.add(os.path.normcase(os.path.abspath(file_path)))
            inventory.append(
                _tool_inventory_item(
                    module_name=module_name,
                    file_path=file_path,
                    meta_path=meta_path,
                    meta=meta,
                )
            )

        for filename in sorted(os.listdir(custom_tools_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            file_path = os.path.abspath(os.path.join(custom_tools_dir, filename))
            if os.path.normcase(file_path) in seen_files:
                continue
            inventory.append(
                _tool_inventory_item(
                    module_name=filename[:-3],
                    file_path=file_path,
                    meta_path=None,
                    meta={},
                )
            )

    return sorted(
        inventory,
        key=lambda item: (
            str(item.get("loadState") or ""),
            str(item.get("toolName") or item.get("fileName") or ""),
        ),
    )


def load_custom_tools(
    registry: ToolRegistry,
    tool_permissions: Optional[Dict[str, int]] = None,
    extra_dirs: Optional[List[str | os.PathLike[str]]] = None,
    load_report: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """custom_tools/ 폴더 내의 모든 .py 파일을 스캔하여 ToolRegistry에 자동 등록합니다.

    각 툴 클래스에 `permission_level` 클래스 속성이 있으면 이를 읽어
    tool_permissions 딕셔너리에 자동으로 추가합니다.

    Args:
        registry: 툴을 등록할 ToolRegistry 인스턴스.
        tool_permissions: RBAC 권한 맵핑 딕셔너리. 이 함수가 로드한
            툴의 permission_level을 여기에 자동 추가합니다.

    Returns:
        성공적으로 로드된 툴 이름 목록.
    """
    loaded: List[str] = []

    for custom_tools_dir in _custom_tool_dirs(extra_dirs):
        if _is_project_custom_tool_dir(custom_tools_dir):
            log.debug(
                "Skipping project custom tool directory in global loader: %s",
                custom_tools_dir,
            )
            continue
        if not os.path.isdir(custom_tools_dir):
            if os.path.normcase(custom_tools_dir) == os.path.normcase(CUSTOM_TOOLS_DIR):
                os.makedirs(custom_tools_dir, exist_ok=True)
            continue

        for filename in sorted(os.listdir(custom_tools_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue

            module_name = filename[:-3]  # .py 제거
            file_path = os.path.join(custom_tools_dir, filename)
            meta_path = os.path.join(custom_tools_dir, f"{module_name}.meta.json")
            meta = _read_tool_meta(meta_path)

            report_item, tool_class = _evaluate_tool_inventory_item(
                module_name=module_name,
                file_path=file_path,
                meta_path=meta_path,
                meta=meta,
            )
            if report_item.get("loadState") != "available" or tool_class is None:
                _log_unavailable_inventory_item(report_item)
                if load_report is not None:
                    load_report.append(report_item)
                continue

            try:
                instance = tool_class()
                registry.register(instance)
                loaded.append(tool_class.name)
                if load_report is not None:
                    load_report.append(report_item)

                # 툴의 permission_level을 RBAC 맵에 자동 등록
                level = getattr(tool_class, "permission_level", DEFAULT_PERMISSION_LEVEL)
                if tool_permissions is not None:
                    tool_permissions[tool_class.name] = level
                    log.info(
                        "Custom tool loaded: %s (level=%d, file=%s)",
                        tool_class.name,
                        level,
                        file_path,
                    )

                # meta.json 정규화 (누락·이름 오류 교정)
                normalize_tool_meta(meta_path, tool_class, module_name)

            except Exception as e:
                _mark_tool_inventory_unavailable(report_item, str(e))
                _log_unavailable_inventory_item(report_item)
                if load_report is not None:
                    load_report.append(report_item)

    return loaded


def load_custom_tools_for_project(
    registry: ToolRegistry,
    project_id: str,
    tool_permissions: Optional[Dict[str, int]] = None,
    load_report: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """프로젝트 격리 경로에서 커스텀 툴을 로드합니다.

    경로: ``custom_tools/projects/<project_id>/*.py``

    로드 조건 (``meta.json`` 기준):
      - ``isActive == True``
      - ``status == "active"``
      - ``validationResult.success == True``
      - ``sandboxResult.success == True``

    이 함수는 standalone(CLI/TUI)에서도 ``project_id``가 주어지면
    프로젝트 격리 로딩을 지원하기 위해 ``theseus_engine`` 안에 존재한다.
    서버 전용 로더(``src/tooling/service.py``)는 sandbox 결과 등
    추가 조건을 검사하는 상위 레이어이다.

    Args:
        registry: 툴을 등록할 ToolRegistry 인스턴스.
        project_id: 프로젝트 식별자.
        tool_permissions: RBAC 권한 맵핑. 로드된 툴의 level이 자동 추가된다.

    Returns:
        성공적으로 로드된 툴 이름 목록.
    """
    project_dir = os.path.join(get_project_custom_tools_dir(), project_id)
    loaded: List[str] = []

    if not os.path.isdir(project_dir):
        log.info(
            "Project tools dir not found, skipping: %s (project_id=%s)",
            project_dir,
            project_id,
        )
        return loaded

    seen_files: Set[str] = set()
    candidates: List[Tuple[str, str, str | None, Optional[Dict[str, Any]], str]] = []

    for filename in sorted(os.listdir(project_dir)):
        if not filename.endswith(".meta.json") or filename.startswith("_"):
            continue
        meta_path = os.path.join(project_dir, filename)
        fallback_stem = filename.removesuffix(".meta.json")
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as exc:
            log.warning("Failed to read project tool meta %s: %s", meta_path, exc)
            seen_files.add(os.path.normcase(f"{fallback_stem}.py"))
            candidates.append(
                (
                    fallback_stem,
                    f"{fallback_stem}.py",
                    meta_path,
                    None,
                    f"Project custom tool metadata cannot be read: {exc}",
                )
            )
            continue

        file_name = os.path.basename(str(meta.get("fileName") or f"{fallback_stem}.py"))
        if not file_name.endswith(".py") or file_name.startswith("_"):
            file_name = f"{fallback_stem}.py"
        module_name = str(meta.get("moduleName") or file_name[:-3]).strip() or file_name[:-3]
        candidates.append((module_name, file_name, meta_path, meta, ""))
        seen_files.add(os.path.normcase(file_name))

    for filename in sorted(os.listdir(project_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        if os.path.normcase(filename) in seen_files:
            continue
        candidates.append(
            (
                filename[:-3],
                filename,
                None,
                None,
                "Project custom tool requires trusted metadata.",
            )
        )

    for module_name, filename, meta_path, meta, meta_error in candidates:
        file_path = os.path.join(project_dir, filename)
        report_item = _base_tool_inventory_item(
            module_name=module_name,
            file_path=file_path,
            meta_path=meta_path,
            meta=meta or {},
        )
        if not os.path.exists(file_path):
            _mark_tool_inventory_unavailable(
                report_item,
                f"Missing module file: {os.path.basename(file_path)}",
            )
            _log_unavailable_inventory_item(report_item)
            if load_report is not None:
                load_report.append(report_item)
            continue

        # ── meta.json active 체크 ────────────────────────────
        if meta is None:
            _mark_tool_inventory_inactive(report_item, meta_error)
            log.info("Skipped project tool without trusted metadata: %s", module_name)
            if load_report is not None:
                load_report.append(report_item)
            continue
        if not _metadata_is_sandbox_verified(meta):
            _mark_tool_inventory_inactive(
                report_item,
                "Project custom tool is not sandbox verified.",
            )
            log.info(
                "Skipped inactive or unverified project tool: %s "
                "(status=%s isActive=%s validationSuccess=%s sandboxSuccess=%s)",
                module_name,
                meta.get("status"),
                meta.get("isActive"),
                (meta.get("validationResult") or {}).get("success"),
                (meta.get("sandboxResult") or {}).get("success"),
            )
            if load_report is not None:
                load_report.append(report_item)
            continue

        # ── 코드 검증 + 로드 ─────────────────────────────────
        report_item, tool_class = _evaluate_tool_inventory_item(
            module_name=module_name,
            file_path=file_path,
            meta_path=meta_path,
            meta=meta,
        )
        if report_item.get("loadState") != "available" or tool_class is None:
            _log_unavailable_inventory_item(report_item)
            if load_report is not None:
                load_report.append(report_item)
            continue

        try:
            instance = tool_class()
            registry.register(instance)
            loaded.append(tool_class.name)
            if load_report is not None:
                load_report.append(report_item)

            level = getattr(tool_class, "permission_level", DEFAULT_PERMISSION_LEVEL)
            if tool_permissions is not None:
                tool_permissions[tool_class.name] = level

            log.info(
                "Project tool loaded: %s (project=%s level=%d file=%s)",
                tool_class.name,
                project_id,
                level,
                filename,
            )
        except Exception as exc:
            _mark_tool_inventory_unavailable(report_item, str(exc))
            _log_unavailable_inventory_item(report_item)
            if load_report is not None:
                load_report.append(report_item)

    return loaded


def build_filtered_registry(
    full_registry: ToolRegistry,
    tool_permissions: Dict[str, int],
    user_level: int,
    exclude_tools: Optional[Set[str]] = None,
) -> ToolRegistry:
    """사용자의 권한 레벨에 따라 접근 가능한 툴만 담은 새 ToolRegistry를 생성합니다.

    LLM에게 이 필터링된 레지스트리를 전달하면, 권한 밖의 툴은
    API 스키마에 아예 포함되지 않아 에이전트가 존재 자체를 알 수 없게 됩니다.

    Args:
        full_registry: 모든 툴이 등록된 원본 ToolRegistry.
        tool_permissions: {tool_name: required_level} 맵핑.
        user_level: 현재 사용자의 권한 레벨 (자연수).
        exclude_tools: 이번 턴에서 제외할 툴 이름 집합 (모드별 필터링용).

    Returns:
        필터링된 ToolRegistry 인스턴스.
    """
    filtered = ToolRegistry()
    excluded = exclude_tools or set()
    for tool in full_registry.list_tools():
        if tool.name in excluded:
            continue
        required = tool_permissions.get(
            tool.name, getattr(tool, "permission_level", DEFAULT_PERMISSION_LEVEL)
        )
        if user_level >= required:
            filtered.register(tool)
    return filtered


# ---------------------------------------------------------------------------
# Meta-tool: create_tool
# ---------------------------------------------------------------------------


class ToolCreatorInput(BaseModel):
    """Input model for the create_tool meta-tool."""

    tool_name: str = Field(
        description=(
            "Logical name for the new tool (e.g. weather_fetcher). The saved "
            "module file uses the canonical '<tool_name>_tool.py' pattern unless "
            "the name already ends with '_tool'."
        )
    )
    python_code: str = Field(
        description=(
            "A complete, self-contained Python module string that imports "
            "BaseTool and BaseModel and follows the Theseus tool specification. "
            "The BaseTool subclass MUST include a 'permission_level' class attribute. "
            "STRONGLY RECOMMENDED: Also include an 'example_queries' class attribute "
            "(list of 3-5 short user utterances in the user's or project's likely "
            "language context) that would "
            "trigger this tool. This boosts retrieval accuracy in the RAG-based "
            "tool selector. Example: "
            "example_queries = ['<short request>', '<alternate phrasing>', '<domain-specific request>']. "
            "Generated tools must follow Theseus custom tool security rules: no "
            "subprocess/shell execution or other banned modules/functions; use safe "
            "read-only APIs such as psutil, /proc, or /sys where possible."
        )
    )
    permission_level: int = Field(
        default=1,
        ge=MIN_PERMISSION_LEVEL,
        le=MAX_PERMISSION_LEVEL,
        description=(
            "Minimum permission level required to use this tool (integer from 1 to 5). "
            "1 = anyone can use; higher values require higher privileges."
        ),
    )

    @field_validator("permission_level", mode="before")
    @classmethod
    def validate_permission_level(cls, value: Any) -> int:
        return _coerce_permission_level(value)


ToolCreatorInput.model_rebuild()


class ToolCreatorTool(BaseTool):
    """새로운 Python 툴을 생성·검증·저장하고 즉시 사용 가능하게 등록합니다."""

    name = "create_tool"
    description = (
        "Create a new Python tool, validate its syntax and Theseus tool "
        "compliance, and save it to the custom_tools directory. On success, "
        "the tool is registered in the current session's ToolRegistry and "
        "available from the NEXT turn. "
        "WHEN TO USE: Only use this tool when (1) you are in Plan mode's "
        "Executing phase, (2) the user's approved plan explicitly requires "
        "a new capability, and (3) no existing tool can accomplish the task. "
        "HOW TO USE: Produce a complete, self-contained, Pythonic module. "
        "When embedding Python code as a string, use triple single quotes for the "
        "outer string if the inner code contains triple double quote docstrings. "
        "Do not nest unescaped triple double quotes inside another triple double "
        "quoted string. Prefer helper functions, constants, or JSON data over "
        "nested Python source strings when possible. "
        "Generated custom tools must not import subprocess or execute shell commands; "
        "if a required capability needs prohibited command execution, explain that "
        "user feedback or a trusted core adapter is required. "
        "Always declare an 'example_queries' class attribute listing 3-5 short "
        "user utterances in the user's or project's likely language context that should trigger this tool — "
        "this dramatically improves the RAG retriever's ability to surface it. "
        "CRITICAL: You CANNOT create a tool and call it in the SAME turn. "
        "You must call create_tool, wait for the success result, and ONLY "
        "THEN call the newly created tool in your next response."
    )
    input_model = ToolCreatorInput
    permission_level = 2
    is_destructive = True

    # is_read_only is False by default for destructive tools,
    # but we can be explicit if needed.

    async def execute(
        self, arguments: ToolCreatorInput, context: ToolExecutionContext
    ) -> ToolResult:
        return await self._execute_with_repair(arguments, context)

    async def _execute_with_repair(
        self, arguments: ToolCreatorInput, context: ToolExecutionContext
    ) -> ToolResult:
        llm_client = context.metadata.get("llm_client")
        model_name = str(context.metadata.get("model_name") or "")
        policy = context.metadata.get("tool_repair_policy")
        if not isinstance(policy, ToolRepairPolicy):
            policy = ToolRepairPolicy.from_env()

        if llm_client is None or not model_name or policy.max_attempts <= 0:
            return await self._execute_once(arguments, context)

        initial_candidate = self._candidate_from_arguments(arguments)
        repair_loop: ToolRepairLoop[dict[str, Any], ToolResult] = ToolRepairLoop(
            llm_client=llm_client,
            model_name=model_name,
            policy=policy,
            debug_context={
                "session_id": context.metadata.get("session_id"),
                "project_id": context.metadata.get("project_id"),
                "chat_session_id": context.metadata.get("chat_session_id"),
                "run_id": context.run_id,
                "agent_mode": context.metadata.get("agent_mode"),
            },
        )

        async def _validate(candidate: dict[str, Any]) -> ToolResult:
            candidate_args = self._arguments_from_candidate(candidate, fallback=arguments)
            result = await self._execute_once(candidate_args, context)
            if result.is_error:
                raise self._failure_from_tool_result(result)
            return result

        result = await repair_loop.run(
            initial_prompt="Validate and, if needed, repair this create_tool request.",
            initial_candidate=initial_candidate,
            task_context=(
                "The runtime is executing the create_tool meta-tool. "
                "Repair the generated Python custom tool code while preserving the "
                "requested capability and following the security rules.\n\n"
                f"Original toolName={arguments.tool_name}\n"
                f"Original permissionLevel={arguments.permission_level}\n"
            ),
            candidate_contract=self._creator_candidate_contract(),
            generate_candidate=self._generate_unexpected_creator_candidate,
            validate_candidate=_validate,
            parse_candidate_payload=self._parse_creator_candidate,
            render_candidate=lambda candidate: candidate,
        )

        if result.success and result.value is not None:
            metadata = dict(result.value.metadata)
            metadata["repairAttempts"] = result.attempts
            result.value.metadata = metadata
            return result.value

        message = result.final_message(policy)
        metadata = {
            "status": "repair_failed",
            "repairAttempts": result.attempts,
            "lastFailureCode": result.last_failure.code if result.last_failure else None,
            "needsUserFeedback": result.needs_user_feedback,
        }
        if result.feedback_message:
            metadata["feedbackMessage"] = result.feedback_message
        return ToolResult(
            output=f"❌ Tool repair failed:\n{message}", is_error=True, metadata=metadata
        )

    async def _generate_unexpected_creator_candidate(self, prompt: str) -> dict[str, Any]:
        raise ToolRepairFailure(
            stage="repair_generation",
            code="LLM_OUTPUT_INVALID",
            message="create_tool repair candidate generation did not produce a candidate.",
            metadata={"prompt": prompt[:1000]},
        )

    @staticmethod
    def _candidate_from_arguments(arguments: ToolCreatorInput) -> dict[str, Any]:
        return {
            "toolName": arguments.tool_name,
            "pythonCode": arguments.python_code,
            "permissionLevel": arguments.permission_level,
        }

    @staticmethod
    def _arguments_from_candidate(
        candidate: dict[str, Any],
        *,
        fallback: ToolCreatorInput,
    ) -> ToolCreatorInput:
        return ToolCreatorInput(
            tool_name=str(
                candidate.get("toolName") or candidate.get("tool_name") or fallback.tool_name
            ),
            python_code=str(
                candidate.get("pythonCode") or candidate.get("python_code") or fallback.python_code
            ),
            permission_level=_coerce_permission_level(
                candidate.get("permissionLevel")
                or candidate.get("permission_level")
                or fallback.permission_level
            ),
        )

    @staticmethod
    def _parse_creator_candidate(payload: dict[str, Any]) -> dict[str, Any]:
        tool_name = payload.get("toolName") or payload.get("tool_name")
        python_code = payload.get("pythonCode") or payload.get("python_code")
        if not tool_name or not python_code:
            raise ValueError("candidate requires toolName and pythonCode")
        permission_level = payload.get("permissionLevel") or payload.get("permission_level") or 1
        return {
            "toolName": str(tool_name),
            "pythonCode": str(python_code),
            "permissionLevel": _coerce_permission_level(permission_level),
        }

    @staticmethod
    def _creator_candidate_contract() -> str:
        return (
            "Candidate object schema:\n"
            "{\n"
            '  "toolName": "snake_case logical tool name",\n'
            '  "pythonCode": "complete Python source code for one Theseus BaseTool module",\n'
            '  "permissionLevel": 1\n'
            "}\n\n"
            f"{COMMON_CUSTOM_TOOL_SECURITY_RULES}"
        )

    @staticmethod
    def _failure_from_tool_result(result: ToolResult) -> ToolRepairFailure:
        metadata = result.metadata or {}
        stage = str(metadata.get("stage") or metadata.get("status") or "validation_failed")
        errors = metadata.get("errors")
        return ToolRepairFailure(
            stage=stage,
            code=stage.upper(),
            message=str(result.output),
            metadata={"errors": errors, **metadata},
        )

    async def _execute_once(
        self, arguments: ToolCreatorInput, context: ToolExecutionContext
    ) -> ToolResult:
        """서버 컨텍스트가 있으면 서버 파이프라인, 없으면 standalone 경로로 실행합니다."""
        server_context = resolve_server_create_tool_context(
            context.metadata,
            run_id=context.run_id,
        )

        if server_context is not None:
            try:
                result = await create_tool_via_server(
                    tool_name=arguments.tool_name,
                    python_code=arguments.python_code,
                    permission_level=arguments.permission_level,
                    server_context=server_context,
                    registry=context.metadata.get("tool_registry"),
                    tool_permissions=context.metadata.get("tool_permissions"),
                )
            except RuntimeError as exc:
                if str(exc) != "server_tooling_unavailable":
                    raise
                return ToolResult(
                    output=(
                        "❌ Server create_tool pipeline is unavailable in a server "
                        "execution context. Refusing standalone fallback because it "
                        "would activate a project custom tool without Core sandbox "
                        "verification."
                    ),
                    is_error=True,
                    metadata={
                        "status": "server_tooling_unavailable",
                        "activationSource": "blocked_server_standalone_fallback",
                        "sandboxVerified": False,
                    },
                )

            if result.status == "created" and context.metadata.get("active_registry") is not None:
                instance = context.metadata["tool_registry"].get(arguments.tool_name)
                if instance:
                    user_rbac = context.metadata.get("user_rbac_level", 1)
                    tool_lv = getattr(instance, "permission_level", 1)
                    if user_rbac >= tool_lv:
                        context.metadata["active_registry"].register(instance)

            return ToolResult(
                output=result.message,
                is_error=result.status != "created",
                metadata=result.to_metadata(),
            )

        return await self._execute_standalone(arguments, context)

    async def _execute_standalone(
        self, arguments: ToolCreatorInput, context: ToolExecutionContext
    ) -> ToolResult:
        from theseus_engine.tools.core.tool_creation import (
            inject_permission_level,
            normalize_tool_name,
            ToolCreationError,
        )
        import json
        from datetime import datetime, timezone

        os.makedirs(CUSTOM_TOOLS_DIR, exist_ok=True)

        # 0. 네이밍 룰 및 정규화
        try:
            safe_tool_name = normalize_tool_name(arguments.tool_name)
        except ToolCreationError as e:
            log.error("[ToolAudit] Legacy tool creation failed at naming: %s", e.message)
            return ToolResult(output=f"❌ Naming validation failed:\n{e.message}", is_error=True)

        module_stem = canonical_tool_module_stem(safe_tool_name)
        file_path = os.path.join(CUSTOM_TOOLS_DIR, f"{module_stem}.py")
        meta_path = os.path.join(CUSTOM_TOOLS_DIR, f"{module_stem}.meta.json")

        # 1. 권한 자동 주입 (service.py 재사용)
        try:
            code = inject_permission_level(arguments.python_code, arguments.permission_level)
        except ToolCreationError as e:
            log.error(
                "[ToolAudit] Legacy tool creation failed at permission injection: %s", e.message
            )
            return ToolResult(output=f"❌ {e.message}", is_error=True)

        # 2. 코드 정제 (LLM 출력에서 발생하는 이스케이프 오염 제거)
        code = _sanitize_generated_code(code)

        # 2b. 코드 문법 검증
        is_valid_code, code_msg = ToolValidator.validate_code(code)
        if not is_valid_code:
            # 문제 코드 7번 줄 전후를 로그에 덤프해 디버깅을 돕는다
            lines = code.splitlines()
            snippet = "\n".join(f"  {i+1:>4}: {l}" for i, l in enumerate(lines[:20]))
            log.error(
                "[ToolAudit] Legacy tool creation failed at validation:\n%s\n"
                "[Code snippet (first 20 lines)]\n%s",
                code_msg,
                snippet,
            )
            return ToolResult(
                output=f"❌ Code syntax/structure validation failed:\n{code_msg}",
                is_error=True,
            )

        # 3. 파일 저장 (임시)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)

        # 4. 모듈 로드 및 구조(Schema) 검증
        is_valid_module, mod_msg, tool_class = ToolValidator.validate_and_load_module(
            module_stem, file_path
        )
        if not is_valid_module:
            os.remove(file_path)
            log.error(
                "[ToolAudit] Legacy tool creation failed at module load (rolled back):\n%s", mod_msg
            )
            return ToolResult(
                output=f"❌ Tool specification validation failed (file rolled back):\n{mod_msg}",
                is_error=True,
            )

        # 5. 로컬 메타데이터 생성 및 저장 (.meta.json)
        now = datetime.now(timezone.utc).isoformat()
        metadata = {
            "toolName": tool_class.name,
            "moduleName": module_stem,
            "projectId": "local",
            "chatSessionId": None,
            "creatorUserId": "cli_user",
            "planId": None,
            "fileName": f"{module_stem}.py",
            "createdAt": now,
            "updatedAt": now,
            "permissionLevel": getattr(tool_class, "permission_level", arguments.permission_level),
            "status": "active",
            "isActive": True,
            "sandboxVerified": False,
            "activationSource": "standalone_without_sandbox",
            "validationResult": {
                "success": True,
                "status": "validated",
                "message": "ToolValidator validation passed.",
                "checkedAt": now,
            },
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        # 5b. 생성 직후 정규화 (스키마 일관성 보장)
        normalize_tool_meta(meta_path, tool_class, module_stem)
        result_metadata = {
            "tool_name": tool_class.name,
            "module_path": file_path,
            "metadata_path": meta_path,
            "permission_level": getattr(tool_class, "permission_level", arguments.permission_level),
            "status": "created",
            "sandboxVerified": False,
            "activationSource": "standalone_without_sandbox",
        }

        # 6. 런타임 ToolRegistry 및 RBAC에 즉시 등록
        registry = context.metadata.get("tool_registry")
        tool_permissions = context.metadata.get("tool_permissions")
        level = metadata["permissionLevel"]

        if registry is not None and tool_class is not None:
            try:
                instance = tool_class()
                registry.register(instance)

                if tool_permissions is not None:
                    tool_permissions[tool_class.name] = level

                # 7. active_registry에도 즉시 등록 (RBAC 체크 후)
                active_registry = context.metadata.get("active_registry")
                user_rbac = context.metadata.get("user_rbac_level", 1)
                if active_registry is not None and user_rbac >= level:
                    active_registry.register(instance)
                    log.info(
                        "[ToolAudit] Tool also registered in active_registry: %s (user_lv=%d, tool_lv=%d)",
                        tool_class.name,
                        user_rbac,
                        level,
                    )
                elif active_registry is not None:
                    log.warning(
                        "[ToolAudit] Tool not added to active_registry: user_lv=%d < tool_lv=%d",
                        user_rbac,
                        level,
                    )

                log.info("[ToolAudit] Legacy tool creation activated: %s", tool_class.name)
                return ToolResult(
                    output=(
                        f"✅ Tool '{tool_class.name}' created, validated, and registered!\n"
                        f"File: {file_path}\n"
                        f"Metadata: {meta_path}\n"
                        f"Permission level: {level}\n"
                        f"⚡ This tool is immediately available in the current session."
                    ),
                    metadata=result_metadata,
                )
            except Exception as e:
                log.error("[ToolAudit] Legacy tool runtime registration failed: %s", e)
                return ToolResult(
                    output=(
                        f"✅ Tool file & metadata saved, but runtime registration failed: {e}\n"
                        f"File: {file_path}\n"
                        f"The tool will be auto-loaded on the next session start."
                    ),
                    metadata={**result_metadata, "status": "created_registration_failed"},
                )

        log.info(
            "[ToolAudit] Legacy tool creation finished without registry access: %s", tool_class.name
        )
        return ToolResult(
            output=(
                f"✅ Tool '{tool_class.name}' created and validated!\n"
                f"File: {file_path}\n"
                f"Metadata: {meta_path}\n"
                f"Permission level: {level}\n"
                f"⚠️ Could not access runtime registry for auto-registration. "
                f"The tool will be auto-loaded on the next session start."
            ),
            metadata={**result_metadata, "status": "created_not_registered"},
        )
