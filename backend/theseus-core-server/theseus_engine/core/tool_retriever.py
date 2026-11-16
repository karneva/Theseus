"""v1 호환 모듈. 구현은 theseus_engine.core.tool_rag 패키지로 옮겼습니다.

기존 import 경로(``from theseus_engine.core.tool_retriever import ToolRetriever``)를 깨지 않기 위해 남겨 둔 얇은 래퍼입니다.
새 코드는 ``theseus_engine.core.tool_rag``의 ``get_tool_retriever()``와 ``retrieve(..., candidates=...)``를 쓰세요.

v2에서 지운 것: 하드코딩 키워드 리랭크(_rerank_by_keyword), SIMILARITY_THRESHOLD(한 번도 발동하지 않음),
compute_adaptive_k(공백 단어 수 기반이라 한국어에서 부정확; 비용 인지 선택이 대체), __new__ 싱글턴.
"""

from __future__ import annotations

from typing import Iterable

from theseus_engine.core.tool_rag import (
    ESSENTIAL_TOOL_NAMES,
    TOOL_EXAMPLE_QUERIES,
    RetrievalResult,
    ToolRetriever,
    get_tool_retriever,
)
from theseus_engine.tools.core.base_tools import BaseTool, ToolRegistry


def build_retrieved_registry(retrieved_tools: Iterable[BaseTool]) -> ToolRegistry:
    """검색된 도구 목록으로 새 레지스트리를 만듭니다."""
    registry = ToolRegistry()
    for tool in retrieved_tools:
        registry.register(tool)
    return registry


__all__ = [
    "ESSENTIAL_TOOL_NAMES",
    "TOOL_EXAMPLE_QUERIES",
    "RetrievalResult",
    "ToolRetriever",
    "build_retrieved_registry",
    "get_tool_retriever",
]
