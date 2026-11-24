"""Filesystem globbing tool."""

import logging
from pathlib import Path

from pydantic import BaseModel, Field
from theseus_engine.tools.core.base_tools import BaseTool, ToolExecutionContext, ToolResult

from theseus_engine.tools.core.file_utils import _resolve_path, _check_path_security

log = logging.getLogger(__name__)


class GlobInput(BaseModel):
    """Input for globbing files."""

    pattern: str = Field(description="Glob pattern (e.g., 'src/**/*.py' or '*.md')")
    root: str = Field(default=".", description="Optional sub-directory to start searching from")


def _effective_pattern(pattern: str) -> str:
    """'dir/**'처럼 **로 끝나는 패턴은 그 아래 모든 파일을 뜻하게 합니다.

    Python 3.11의 Path.glob은 **로 끝나는 패턴에 디렉터리만 돌려주므로, 파일만 남기는 이 도구에서는 항상
    결과가 비었습니다. 'dir/**/*'로 바꿔 사용자가 기대하는 대로 하위 파일 전부를 찾습니다.
    """
    stripped = pattern.rstrip("/")
    if stripped == "**" or stripped.endswith("/**"):
        return stripped + "/*"
    return pattern


class GlobTool(BaseTool):
    """Lists files matching a pattern."""

    name = "glob"
    description = (
        "Find files in the workspace matching a glob pattern. Recursive search supported with '**'."
    )
    input_model = GlobInput
    permission_level = 1
    is_destructive = False

    def is_read_only(self, arguments) -> bool:
        return True

    async def execute(self, arguments: GlobInput, context: ToolExecutionContext) -> ToolResult:
        search_root = _resolve_path(context.cwd, arguments.root)

        security_err = _check_path_security(search_root, context.cwd)
        if security_err:
            return ToolResult(output=security_err, is_error=True)

        try:
            # Path.glob()은 패턴에 **가 포함되면 재귀 탐색을 자체 지원하므로
            # rglob()을 별도로 사용할 필요 없음 (rglob("**/*.py")는 이중 재귀 발생)
            matches = list(search_root.glob(_effective_pattern(arguments.pattern)))
            if "__pycache__" not in arguments.pattern:
                # 바이트코드 캐시는 찾는 대상이 아니므로 결과를 가리지 않게 뺍니다(패턴에 직접 쓴 경우는 그대로).
                matches = [p for p in matches if "__pycache__" not in p.relative_to(search_root).parts]

            # Filter directories and convert to relative paths
            files = sorted(str(p.relative_to(context.cwd)) for p in matches if p.is_file())

            if not files:
                dirs = sorted(str(p.relative_to(context.cwd)) for p in matches if p.is_dir())
                if dirs:
                    # 디렉터리만 걸린 경우(예: '*'): "없음" 대신 디렉터리를 보여 줘 다음 패턴을 고를 수 있게 합니다.
                    return ToolResult(
                        output=f"No files match '{arguments.pattern}' in '{arguments.root}', "
                        f"but {len(dirs)} directories do (glob lists files; use e.g. "
                        f"'{dirs[0]}/**/*.py' to list files inside):\n"
                        + "\n".join(d + "/" for d in dirs[:200])
                        + ("\n... (truncated)" if len(dirs) > 200 else "")
                    )
                return ToolResult(
                    output=f"No matches found for pattern '{arguments.pattern}' in '{arguments.root}'"
                )

            return ToolResult(
                output=f"Found {len(files)} matches:\n"
                + "\n".join(files[:500])
                + ("\n... (truncated)" if len(files) > 500 else "")
            )
        except Exception as e:
            return ToolResult(output=f"Glob failed: {e}", is_error=True)
