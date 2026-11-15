"""API Server 전용 Tool 관리 엔드포인트(삭제, 권한 레벨 변경).

사용자 요청은 API Server에서 권한을 검사한 뒤 서버 간 호출로 들어오므로,
라우터 전체를 내부 API 키로 보호합니다. project_id를 int로 받아
`PROJECT_TOOLS_DIR / str(project_id)` 경로 조합에 `..` 같은 값이 섞이지 않게 합니다.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field

from src.auth.guards import require_internal_api_key
from src.tooling.service import move_tool_to_trash, update_tool_permission_level

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_internal_api_key)])


class ToolPermissionLevelUpdateRequest(BaseModel):
    permissionLevel: int = Field(ge=1, le=5)


def _internal_error(action: str, project_id: int, tool_name: str) -> HTTPException:
    """예외 상세는 traceId와 함께 로그에만 남기고, 응답에는 일반화된 메시지만 보냅니다."""
    trace_id = uuid.uuid4().hex[:12]
    logger.error(
        "Tool %s failed. traceId=%s project=%s tool=%s",
        action,
        trace_id,
        project_id,
        tool_name,
        exc_info=True,
    )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Failed to {action}. traceId={trace_id}",
    )


@router.delete("/tools/{project_id}/{tool_name}")
async def delete_tool_endpoint(project_id: int = Path(ge=1), tool_name: str = Path()):
    try:
        moved = move_tool_to_trash(str(project_id), tool_name)
    except Exception:
        raise _internal_error("delete tool", project_id, tool_name)
    if not moved:
        return {"status": "skipped", "message": "No physical files found to delete."}
    return {"status": "success", "message": f"Successfully moved tool {tool_name} to trash."}


@router.patch("/tools/{project_id}/{tool_name}/permission-level")
async def update_tool_permission_level_endpoint(
    request: ToolPermissionLevelUpdateRequest,
    project_id: int = Path(ge=1),
    tool_name: str = Path(),
):
    try:
        updated = update_tool_permission_level(
            str(project_id), tool_name, request.permissionLevel
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise _internal_error("update tool permissionLevel", project_id, tool_name)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool metadata file not found.",
        )
    return {
        "status": "success",
        "message": f"Successfully updated tool {tool_name} permissionLevel.",
        "permissionLevel": request.permissionLevel,
    }
