import logging

from fastapi import APIRouter, Depends, HTTPException, status

from src.auth.dependencies import get_session_context
from src.auth.schemas import SessionContext
from src.sandbox.base import (
    SandboxExecutionRequest,
    SandboxInput,
    SandboxUnavailableError,
)
from src.sandbox.docker_executor import DockerExecutor

logger = logging.getLogger(__name__)
router = APIRouter()
executor = DockerExecutor()


@router.post("/sandbox/execute")
async def execute_in_sandbox(
    request: SandboxExecutionRequest,
    session: SessionContext = Depends(get_session_context),
):
    """
    Internal/admin-facing sandbox execution endpoint.
    Binds execution to the authenticated project context.
    """
    if session.permission_level < 3:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sandbox execution requires elevated permissions",
        )

    sandbox_input = SandboxInput(
        project_id=session.project_id,
        tool_name=request.tool_name,
        tool_code=request.tool_code,
        payload=request.payload,
        timeout_seconds=request.timeout_seconds,
    )

    try:
        return await executor.execute(sandbox_input)
    except SandboxUnavailableError as exc:
        # 예외 메시지에 Docker host 같은 내부 정보가 들어 있으므로 로그에만 남깁니다.
        logger.warning("Sandbox unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sandbox is unavailable.",
        ) from exc
