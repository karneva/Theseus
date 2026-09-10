from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.auth.client import auth_client
from src.auth.schemas import SessionContext
from src.config import settings

security = HTTPBearer(auto_error=False)


def _build_mock_session_context(token: str) -> SessionContext:
    if not settings.mock_auth_enabled:
        raise RuntimeError("Mock authentication is disabled in this environment")

    return SessionContext(
        user_id=9999,
        project_id=8888,
        permission_level=3,
        token=token,
    )


async def get_bearer_token(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """
    Authorization Header에서 Bearer 토큰을 추출합니다.
    """
    if auth:
        return auth.credentials

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_sse_token(
    request: Request,
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """
    SSE 연결에서는 Header(Bearer) 또는 Query Parameter(token)에서 토큰을 추출합니다.
    """
    if auth:
        return auth.credentials

    token = request.query_params.get("token")
    if token:
        return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_session_context(token: str = Depends(get_bearer_token)) -> SessionContext:
    """
    추출된 토큰을 검증하고 세션 컨텍스트를 반환합니다.
    AUTH_MODE=mock은 dev/test 환경에서만 허용됩니다.
    """
    return await _resolve_session_context(token)


async def get_sse_session_context(
    request: Request, token: str = Depends(get_sse_token)
) -> SessionContext:
    """
    SSE 전용 토큰 추출 방식을 사용하는 세션 컨텍스트 의존성입니다.
    """
    return await _resolve_session_context(
        token,
        chat_session_id=request.query_params.get("chat_session_id"),
        project_id=request.query_params.get("project_id"),
    )


async def _resolve_session_context(
    token: str,
    *,
    chat_session_id: str | None = None,
    project_id: str | None = None,
) -> SessionContext:
    if settings.mock_auth_enabled:
        return _build_mock_session_context(token)

    user_session = await auth_client.verify_token(
        token,
        chat_session_id=chat_session_id,
        project_id=project_id,
    )
    return SessionContext(
        user_id=user_session.user_id,
        project_id=user_session.project_id,
        permission_level=user_session.permission_level,
        token=token,
    )
