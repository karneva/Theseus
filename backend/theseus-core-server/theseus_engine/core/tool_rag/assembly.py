"""런타임 조립용: "보이는 도구" 중 이번 턴에 LLM에 보낼 도구를 고릅니다.

서버(src/builder/engine.py)와 로컬 CLI/TUI(theseus_engine/core/engine_builder.py)가 같은 규칙을 씁니다.

    visible = build_visible_registry(full_registry, policy)     # 모드·계획 단계·RBAC·프로젝트 비활성
    selection = select_tools_for_turn(full_registry=..., visible_registry=visible, user_query=...)
    engine(tool_registry=selection.registry, ...)

검색을 건너뛰고 보이는 도구 전부를 보내는 경우:
  * Tool RAG가 꺼져 있음(THESEUS_TOOL_RAG_ENABLED / 서버는 THESEUS_SERVER_TOOL_RAG)
  * 사용자 질의가 없음
  * 보이는 도구가 THESEUS_TOOL_RAG_SMALL_SET개 이하(ASK 모드, PLAN 초안 단계 등)
  * 모델이 아직 로드되지 않았고 호출자가 로드를 기다리지 않겠다고 함(서버: 백그라운드 워밍업 시작)
  * 임베딩·검색이 실패함(경고 로그). full_registry로 폴백하지 않습니다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from theseus_engine.config import ToolRagSettings, get_tool_rag_settings
from theseus_engine.core.tool_rag.examples import TOOL_SEARCH_NAME
from theseus_engine.core.tool_rag.retriever import (
    TOOL_SEARCH_REMINDER,
    RetrievalResult,
    ToolRetriever,
    get_tool_retriever,
    start_background_warmup,
)

log = logging.getLogger(__name__)

PROVENANCE_METADATA_KEY = "tool_rag_provenance"

# 같은 실패(예: 모델 파일 없음)는 get_embedder가 기억해 매 턴 똑같이 실패하므로 경고는 종류별로 한 번만 남깁니다.
_WARNED_FAILURES: set[str] = set()


@dataclass
class ToolSelection:
    registry: Any  # ToolRegistry: 이번 턴에 LLM에 보낼 도구
    mode: str  # "retrieved" | "all_visible"
    reason: str
    visible_names: tuple[str, ...]
    result: RetrievalResult | None = None
    # 도구 이름 → 검색이 고른 경위(slot). 피드백 로거와 tool_search/훅 주입이 같은 dict를 갱신합니다.
    provenance: dict[str, str] = field(default_factory=dict)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(t.name for t in self.registry.list_tools())

    @property
    def is_none(self) -> bool:
        return bool(self.result is not None and self.result.is_none)

    def runtime_reminders(self) -> tuple[str, ...]:
        names = set(self.names)
        if self.mode == "retrieved" and TOOL_SEARCH_NAME in names and len(names) < len(self.visible_names):
            return (TOOL_SEARCH_REMINDER,)
        return ()


def _registry_of(tools: Iterable[Any]):
    from theseus_engine.tools.core.base_tools import ToolRegistry

    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def _all_visible(visible_registry: Any, reason: str) -> ToolSelection:
    names = tuple(t.name for t in visible_registry.list_tools())
    return ToolSelection(
        registry=_registry_of(visible_registry.list_tools()),
        mode="all_visible",
        reason=reason,
        visible_names=names,
    )


def select_tools_for_turn(
    *,
    full_registry: Any,
    visible_registry: Any,
    user_query: str | None,
    history_messages: Sequence[Any] | None = None,
    pinned: Iterable[str] = (),
    server: bool = False,
    wait_for_model: bool = True,
    retriever: ToolRetriever | None = None,
    settings: ToolRagSettings | None = None,
) -> ToolSelection:
    """동기 버전. 서버 조립(동기 함수)에서 wait_for_model=False로 부릅니다."""
    settings = settings or get_tool_rag_settings()
    visible_tools = visible_registry.list_tools()
    visible_names = tuple(t.name for t in visible_tools)
    if not settings.enabled or (server and not settings.server_enabled):
        return _all_visible(visible_registry, "disabled")
    if not (user_query or "").strip():
        return _all_visible(visible_registry, "no_query")
    if len(visible_tools) <= settings.small_set:
        return _all_visible(visible_registry, "small_set")

    retriever = retriever or get_tool_retriever()
    if not wait_for_model and not retriever.is_ready():
        start_background_warmup(full_registry, retriever=retriever)
        return _all_visible(visible_registry, "warming_up")
    try:
        result = retriever.retrieve_sync(
            str(user_query),
            full_registry,
            candidates=visible_names,
            history_messages=history_messages,
            pinned=pinned,
        )
    except Exception as exc:  # 모델 없음, onnxruntime 오류 등
        reason = f"error: {type(exc).__name__}"
        if reason not in _WARNED_FAILURES:
            _WARNED_FAILURES.add(reason)
            log.warning("[ToolRAG] 도구 검색 실패, 보이는 도구 전부를 보냅니다: %s", exc)
        else:
            log.debug("[ToolRAG] 도구 검색 실패(반복), 보이는 도구 전부를 보냅니다: %s", exc)
        return _all_visible(visible_registry, reason)

    visible_set = set(visible_names)
    leaked = [n for n in result.names if n not in visible_set]
    if leaked:  # 검색기 계약 위반 방어(후보 밖 도구는 절대 보내지 않음)
        log.error("[ToolRAG] 후보 밖 도구가 선택돼 제외합니다: %s", leaked)
    # 보내는 인스턴스는 이번 요청의 보이는 레지스트리에서 꺼냅니다(세션별 Remote Workspace 설정·custom tool 코드 유지).
    tools = [t for t in (visible_registry.get(n) for n in result.names if n in visible_set) if t is not None]
    return ToolSelection(
        registry=_registry_of(tools),
        mode="retrieved",
        reason="none_soft_fallback" if result.is_none else "ok",
        visible_names=visible_names,
        result=result,
        provenance={n: "slot" for n in result.slot_names if n in visible_set},
    )


async def aselect_tools_for_turn(**kwargs: Any) -> ToolSelection:
    """비동기 버전(CLI/TUI). 모델 로드·인덱스 구축을 스레드에서 돌려 이벤트 루프를 막지 않습니다."""
    return await asyncio.to_thread(lambda: select_tools_for_turn(**kwargs))


def inject_visible_tool(
    active_registry: Any,
    tool: Any,
    injectable_names: Iterable[str] | None,
    *,
    provenance: dict[str, str] | None = None,
    source: str = "tool_search",
) -> bool:
    """보이는 도구(injectable_names)일 때만 active_registry에 등록합니다. 등록했으면 True.

    tool_search와 사후 훅 주입은 반드시 이 함수를 거칩니다. injectable_names가 None이면(정책 정보 없음)
    아무것도 등록하지 않습니다(fail closed).
    """
    name = getattr(tool, "name", None)
    allowed = None if injectable_names is None else set(injectable_names)
    if not name or allowed is None or name not in allowed:
        log.warning("[ToolRAG] 보이지 않는 도구 주입 거부: %s (source=%s)", name, source)
        return False
    if active_registry.get(name) is not None:
        return False
    active_registry.register(tool)
    if provenance is not None:
        provenance.setdefault(name, source)
    return True
