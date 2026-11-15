"""서버 간(API Server → Core) 호출을 보호하는 FastAPI dependency.

Core의 Tool 관리, Remote Workspace 연결 테스트, 상세 진단(/health/details) 엔드포인트는
사용자 JWT가 아니라 API Server가 붙여 보내는 `X-Internal-Api-Key`로만 인증합니다.
라우터 단위 `dependencies=[Depends(require_internal_api_key)]`로 걸어서
엔드포인트를 새로 추가해도 인증이 빠지지 않게 합니다.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException, status

from src.config import settings

logger = logging.getLogger(__name__)

INTERNAL_API_KEY_HEADER = "X-Internal-Api-Key"


def is_valid_internal_api_key(provided: str | None) -> bool:
    """설정된 내부 키와 요청 키가 같은지 상수 시간으로 비교합니다.

    키가 설정되지 않은 환경에서는 어떤 요청도 통과시키지 않습니다(fail-closed).
    `==` 비교는 앞부분이 일치하는 길이에 따라 응답 시간이 달라져 키를 추측할 단서가
    되므로 `hmac.compare_digest`를 씁니다.
    """
    expected = settings.INTERNAL_API_KEY
    if not expected or not expected.strip() or not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


async def require_internal_api_key(
    internal_api_key: str | None = Header(default=None, alias=INTERNAL_API_KEY_HEADER),
) -> None:
    """내부 API 키가 없거나 틀리면 401을 반환합니다."""
    if not is_valid_internal_api_key(internal_api_key):
        logger.warning("Rejected internal API call: missing or invalid internal API key.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal API key.",
        )
