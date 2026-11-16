"""Tool RAG v2 검색기.

질의 1개당 처리(인덱스가 준비된 뒤):
  1. 질의를 1번 인코딩합니다('query: ' 프리픽스, LRU 256).
  2. 순위 점수 = cos(q, passage) + bm25_beta * BM25(q) / max BM25(q).
  3. none 특징 = 앵커 passage 코사인 최댓값(top1, tool_search 제외) + 질의 커버리지(cov).
     인덱스 전체 도구 기준이라 숨긴 도구(모드·RBAC)도 들어갑니다(보정과 같은 정의, 알려진 한계).
  4. 전달 집합 = 필수 ∩ 후보 → tool_search(후보에 있을 때) → 히스토리 도구 ∩ 후보 → 비용 인지 슬롯(후보에서 앞의
     것들을 뺀 순위). none이면 슬롯을 상위 soft_keep개로 줄입니다. tool_search는 비용 예산 밖에서 항상 넣습니다.
     일부 도구만 보내는 턴에서 슬롯이 정답을 놓쳤을 때 모델이 나머지 보이는 도구를 찾을 유일한 경로이기 때문입니다.

``candidates``는 호출자가 가시성 정책(모드·계획 단계·RBAC·프로젝트 비활성)으로 계산한 "보이는 도구" 이름 집합입니다.
검색기는 후보 밖의 도구를 절대 돌려주지 않습니다. 서버 조립, tool_search, 사후 훅 주입이 모두 이 규칙을 씁니다.

동기 API(``retrieve_sync``)가 본체이고, ``retrieve``는 같은 일을 스레드에서 돌립니다(모델 로드·인덱스 구축이
이벤트 루프를 막지 않도록). v1 호환 ``retrieve_top_k``도 남겨 둡니다.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

from theseus_engine.config import ToolRagSettings, get_tool_rag_settings
from theseus_engine.core.tool_rag.cache import EmbeddingCache
from theseus_engine.core.tool_rag.calibration import load_none_rule
from theseus_engine.core.tool_rag.embedding import Embedder, embedder_ready, get_embedder
from theseus_engine.core.tool_rag.examples import ESSENTIAL_TOOL_NAMES, TOOL_SEARCH_NAME
from theseus_engine.core.tool_rag.index import (
    ToolIndex,
    anchor_mask,
    build_texts,
    registry_fingerprint,
)
from theseus_engine.core.tool_rag.lexical import BM25, bm25_tokens, coverage
from theseus_engine.core.tool_rag.selector import NoneRule, assemble, select_slots

log = logging.getLogger(__name__)

INDEX_LRU_SIZE = 8
QUERY_LRU_SIZE = 256

# 일부 도구만 보낼 때 system prompt에 붙이는 안내(tool_search가 전달 집합에 있을 때만).
TOOL_SEARCH_REMINDER = (
    "Only the tools most relevant to this request are attached. If you need a capability that is not in "
    "your tool list, call tool_search with a short description; matching tools you are allowed to use "
    "become callable from your next response."
)


@dataclass(frozen=True)
class RetrievalResult:
    tools: list[Any]
    names: list[str]
    essential_names: list[str]
    history_names: list[str]
    slot_names: list[str]
    is_none: bool
    top1: float
    coverage: float
    ranked: list[tuple[str, float]] = field(default_factory=list)  # 후보 안의 순위(상위 max_candidates)
    elapsed_ms: float = 0.0

    @property
    def similarity_count(self) -> int:
        return len([n for n in self.slot_names if n != TOOL_SEARCH_NAME])


def extract_history_tool_names(history_messages: Iterable[Any] | None) -> list[str]:
    """대화 히스토리에서 호출된 tool_use 이름(등장 순서). ConversationMessage와 dict 모두 처리합니다."""
    used: list[str] = []
    for message in history_messages or ():
        names: list[str] = []
        if hasattr(message, "tool_uses"):
            names = [getattr(block, "name", None) for block in message.tool_uses]
        elif isinstance(message, dict):
            content = message.get("content", [])
            if isinstance(content, list):
                names = [c.get("name") for c in content if isinstance(c, dict) and c.get("type") == "tool_use"]
        for name in names:
            if name and name not in used:
                used.append(name)
    return used


class ToolRetriever:
    """Tool RAG v2 검색기. 모델은 get_embedder() 프로세스 싱글턴을 공유합니다.

    Args:
        full_registry: v1 호환용 기본 레지스트리(retrieve_top_k에서 registry를 생략할 때).
        embedder: 테스트나 파리티 검증에서 직접 넣을 임베더. 없으면 설정으로 get_embedder()를 부릅니다.
        settings: 고정 설정. 없으면 호출할 때마다 환경변수에서 읽습니다.
        none_rule: none 판정 계수를 직접 지정(테스트용). 없으면 보정 파일에서 읽습니다.
    """

    def __init__(
        self,
        full_registry: Any | None = None,
        *,
        embedder: Embedder | None = None,
        settings: ToolRagSettings | None = None,
        cache: EmbeddingCache | None = None,
        none_rule: NoneRule | None | str = "auto",
    ) -> None:
        self._full_registry = full_registry
        self._embedder = embedder
        self._settings = settings
        self._cache = cache
        self._none_rule = none_rule
        self._indexes: OrderedDict[str, ToolIndex] = OrderedDict()
        self._index_locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        self._qcache: OrderedDict[tuple[str, str], np.ndarray] = OrderedDict()
        self.encode_calls = 0  # 테스트·진단용: 실제 인코딩 호출 횟수

    # ── 구성 요소 ───────────────────────────────────────────
    @property
    def settings(self) -> ToolRagSettings:
        return self._settings or get_tool_rag_settings()

    def embedder(self) -> Embedder:
        if self._embedder is None:
            return get_embedder(self.settings)
        return self._embedder

    def is_ready(self) -> bool:
        """모델이 이미 로드됐는지(서버가 요청 경로에서 모델 로드를 기다리지 않도록 확인)."""
        return self._embedder is not None or embedder_ready(self.settings)

    def _vector_cache(self) -> EmbeddingCache:
        if self._cache is None:
            with self._lock:
                if self._cache is None:
                    self._cache = EmbeddingCache(self.settings.cache_dir)
        return self._cache

    def none_rule(self) -> NoneRule | None:
        if self._none_rule != "auto":
            return self._none_rule  # type: ignore[return-value]
        settings = self.settings
        model_dir = settings.embed_model_dir if settings.embed_backend == "onnx" else None
        return load_none_rule(self.embedder().fingerprint, settings.calibration_file, model_dir)

    def _feedback(self) -> tuple[dict, str]:
        settings = self.settings
        if settings.feedback != "cli" or settings.feedback_max_per_tool <= 0:
            return {}, "off"
        try:
            from theseus_engine.core.tool_usage_logger import load_feedback_queries

            return load_feedback_queries(settings.feedback_max_per_tool)
        except Exception as exc:  # 피드백은 보강일 뿐이므로 실패해도 검색은 계속합니다.
            log.debug("[ToolRAG] 피드백 로드 실패(무시): %s", exc)
            return {}, "error"

    def _encode(self, embedder: Embedder, texts: list[str]) -> np.ndarray:
        self.encode_calls += 1
        return embedder.encode(texts)

    # ── 인덱스 ──────────────────────────────────────────────
    def get_index(self, registry: Any) -> ToolIndex:
        embedder = self.embedder()
        tools = list(registry.list_tools())
        feedback, feedback_version = self._feedback()
        fingerprint = registry_fingerprint(
            tools, embedder_fingerprint=embedder.fingerprint, feedback_version=feedback_version
        )
        with self._lock:
            hit = self._indexes.get(fingerprint)
            if hit is not None:
                self._indexes.move_to_end(fingerprint)
                return hit
            lock = self._index_locks.setdefault(fingerprint, threading.Lock())
        with lock:
            with self._lock:
                hit = self._indexes.get(fingerprint)
            if hit is not None:
                return hit
            index = self._build_index(tools, fingerprint, embedder, feedback)
            with self._lock:
                self._indexes[fingerprint] = index
                while len(self._indexes) > INDEX_LRU_SIZE:
                    old, _ = self._indexes.popitem(last=False)
                    self._index_locks.pop(old, None)
            return index

    def _build_index(self, tools: list[Any], fingerprint: str, embedder: Embedder, feedback: dict) -> ToolIndex:
        started = time.perf_counter()
        texts = build_texts(tools, feedback=feedback, passage_prefix=embedder.passage_prefix)
        cache = self._vector_cache()
        encode = lambda batch: self._encode(embedder, batch)  # noqa: E731
        passages, p_keys, p_new = cache.get_or_encode(embedder.fingerprint, texts.passages, encode, embedder.dim)
        anchors, a_keys, a_new = cache.get_or_encode(embedder.fingerprint, texts.anchors, encode, embedder.dim)
        cache.flush(embedder.fingerprint, p_keys + a_keys)
        names = tuple(t.name for t in tools)
        index = ToolIndex(
            fingerprint=fingerprint,
            names=names,
            passages=passages,
            anchors=anchors,
            bm25=BM25(texts.bm25_docs),
            coverage_vocab=texts.coverage_vocab,
            costs=texts.costs,
            anchor_mask=anchor_mask(names),
            vector_keys=tuple(p_keys + a_keys),
        )
        log.info(
            "[ToolRAG] 인덱스 구축: 도구 %d개, 새로 인코딩 %d개, %.0f ms (fp %s)",
            len(names),
            p_new + a_new,
            (time.perf_counter() - started) * 1000,
            fingerprint[:12],
        )
        return index

    # ── 점수 ────────────────────────────────────────────────
    def query_vector(self, query: str) -> np.ndarray:
        embedder = self.embedder()
        key = (embedder.fingerprint, query)
        with self._lock:
            hit = self._qcache.get(key)
            if hit is not None:
                self._qcache.move_to_end(key)
                return hit
        vec = self._encode(embedder, [embedder.query_prefix + query])[0]
        with self._lock:
            self._qcache[key] = vec
            while len(self._qcache) > QUERY_LRU_SIZE:
                self._qcache.popitem(last=False)
        return vec

    def clear_query_cache(self) -> None:
        with self._lock:
            self._qcache.clear()

    def score(self, query: str, index: ToolIndex) -> tuple[np.ndarray, float, float]:
        """(순위 점수 벡터, top1, coverage)."""
        if index.size == 0:
            return np.zeros(0), 0.0, coverage(query, index.coverage_vocab)
        qv = self.query_vector(query)
        scores = index.passages @ qv
        beta = self.settings.bm25_beta
        if beta > 0:
            lexical = index.bm25.scores(bm25_tokens(query))
            top = float(lexical.max())
            if top > 0:
                scores = scores + beta * lexical / top
        anchor_scores = index.anchors @ qv
        masked = anchor_scores[index.anchor_mask]
        top1 = float(masked.max()) if masked.size else 0.0
        return scores, top1, coverage(query, index.coverage_vocab)

    def rank(self, query: str, registry: Any, candidates: Iterable[str] | None = None) -> list[tuple[str, float]]:
        """후보 안의 전체 순위 [(이름, 점수)] 내림차순(동점은 레지스트리 순서)."""
        index = self.get_index(registry)
        scores, _, _ = self.score(query, index)
        allowed = None if candidates is None else set(candidates)
        order = np.argsort(-scores, kind="stable")
        return [(index.names[i], float(scores[i])) for i in order if allowed is None or index.names[i] in allowed]

    # ── 선택 ────────────────────────────────────────────────
    def retrieve_sync(
        self,
        query: str,
        registry: Any,
        *,
        candidates: Iterable[str] | None = None,
        history_messages: Sequence[Any] | None = None,
        budget: float | None = None,
        max_candidates: int | None = None,
        none_mode: str | None = None,
        include_essentials: bool = True,
        pinned: Iterable[str] = (),
    ) -> RetrievalResult:
        """질의에 대한 전달 집합을 고릅니다.

        Args:
            candidates: 보이는 도구 이름(가시성·RBAC 통과). None이면 레지스트리 전체(호환용, 새 코드는 항상 넘길 것).
            history_messages: 대화 히스토리. 이미 호출한 도구는 비용 예산과 별개로 고정합니다(Ghost tool call 방지).
            budget: 비용 예산(기본 THESEUS_TOOL_RAG_COST_BUDGET). 사후 훅은 더 작은 값을 씁니다.
            max_candidates: 슬롯 후보 상한(imax).
            none_mode: 'soft' | 'off' (기본 THESEUS_TOOL_RAG_NONE_MODE).
            include_essentials: 필수 도구를 넣을지(사후 훅 주입은 False).
            pinned: 필수처럼 항상 넣을 도구(예: PLAN Executing 단계의 create_tool). 후보 밖이면 무시합니다.
        """
        started = time.perf_counter()
        settings = self.settings
        index = self.get_index(registry)
        allowed = set(index.names) if candidates is None else set(candidates) & set(index.names)
        scores, top1, cov = self.score(query, index)

        essentials = [n for n in index.names if include_essentials and n in ESSENTIAL_TOOL_NAMES and n in allowed]
        if include_essentials and TOOL_SEARCH_NAME in allowed:
            essentials.append(TOOL_SEARCH_NAME)  # 필수처럼 비용 예산 밖에서(사후 훅 주입은 include_essentials=False)
        essentials += [n for n in dict.fromkeys(pinned) if n in allowed and n not in essentials]
        fixed = set(essentials)
        history = [n for n in extract_history_tool_names(history_messages) if n in allowed and n not in fixed]
        fixed.update(history)

        imax = settings.max_candidates if max_candidates is None else max_candidates
        order = np.argsort(-scores, kind="stable")
        pool = [index.names[i] for i in order if index.names[i] in allowed and index.names[i] not in fixed]
        slots = select_slots(
            pool,
            index.costs,
            budget=settings.cost_budget if budget is None else budget,
            alpha=settings.rank_alpha,
            imax=imax,
        )
        mode = settings.none_mode if none_mode is None else none_mode
        rule = self.none_rule() if mode == "soft" else None
        is_none = bool(rule is not None and rule.is_none(top1, cov))
        names, final_slots = assemble(
            essentials,
            history,
            slots,
            is_none=is_none,
            soft_keep=settings.soft_keep,
            tool_search_visible=TOOL_SEARCH_NAME in allowed,
        )
        # 인덱스가 아니라 이번 호출의 레지스트리에서 인스턴스를 찾습니다(같은 fingerprint의 다른 세션 도구를 돌려주지 않음).
        by_name = {t.name: t for t in registry.list_tools()}
        score_of = dict(zip(index.names, scores.tolist()))
        elapsed = (time.perf_counter() - started) * 1000
        result = RetrievalResult(
            tools=[by_name[n] for n in names],
            names=names,
            essential_names=essentials,
            history_names=history,
            slot_names=final_slots,
            is_none=is_none,
            top1=top1,
            coverage=cov,
            ranked=[(n, score_of[n]) for n in pool[: max(imax, 1)]],
            elapsed_ms=elapsed,
        )
        try:
            from theseus_engine.observability.stats import SessionStats

            SessionStats.get().observe("rag.retrieval_ms", elapsed)
        except Exception:  # 통계는 부가 기능
            pass
        log.info(
            "[ToolRAG] '%s' → %d개 (슬롯 %s%s, top1 %.3f cov %.2f, %.1f ms)",
            query[:40],
            len(names),
            ",".join(final_slots) or "-",
            " / none" if is_none else "",
            top1,
            cov,
            elapsed,
        )
        return result

    async def retrieve(self, query: str, registry: Any, **kwargs: Any) -> RetrievalResult:
        """retrieve_sync를 스레드에서 실행합니다(첫 호출의 모델 로드·인덱스 구축이 이벤트 루프를 막지 않음)."""
        return await asyncio.to_thread(self.retrieve_sync, query, registry, **kwargs)

    def warmup(self, registry: Any) -> None:
        """모델 로드 + 인덱스 구축(서버 기동 시 백그라운드에서 호출)."""
        self.get_index(registry)
        self.query_vector("warmup")

    # ── v1 호환 ─────────────────────────────────────────────
    async def retrieve_top_k(
        self,
        query: str,
        full_registry: Any | None = None,
        k: int = 8,
        history_messages: Sequence[Any] | None = None,
        adaptive: bool = True,  # noqa: ARG002 - v2에서는 비용 인지 선택이 대신합니다.
        candidates: Iterable[str] | None = None,
    ) -> list[Any]:
        """v1 시그니처 호환. k는 후보 상한(imax)으로만 씁니다."""
        registry = full_registry if full_registry is not None else self._full_registry
        if registry is None:
            raise ValueError("retrieve_top_k에 레지스트리가 필요합니다.")
        result = await self.retrieve(
            query, registry, candidates=candidates, history_messages=history_messages, max_candidates=k
        )
        return result.tools


_DEFAULT: ToolRetriever | None = None
_DEFAULT_LOCK = threading.Lock()
_WARMUP_STARTED: set[str] = set()


def get_tool_retriever() -> ToolRetriever:
    """프로세스 공용 검색기(인덱스 LRU·질의 캐시를 서버 조립, tool_search, 훅이 공유)."""
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = ToolRetriever()
    return _DEFAULT


def set_tool_retriever(retriever: ToolRetriever | None) -> None:
    """테스트용: 공용 검색기를 바꿉니다(None이면 다음 호출에서 새로 만듦)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = retriever
        _WARMUP_STARTED.clear()


def start_background_warmup(registry: Any, *, retriever: ToolRetriever | None = None, key: str = "default") -> bool:
    """모델 로드와 인덱스 구축을 데몬 스레드에서 한 번만 시작합니다. 새로 시작했으면 True."""
    target = retriever or get_tool_retriever()
    with _DEFAULT_LOCK:
        if key in _WARMUP_STARTED:
            return False
        _WARMUP_STARTED.add(key)

    def _run() -> None:
        started = time.perf_counter()
        try:
            target.warmup(registry)
            log.info("[ToolRAG] 워밍업 완료 (%.1f s)", time.perf_counter() - started)
        except Exception as exc:
            log.warning("[ToolRAG] 워밍업 실패: 검색 없이 보이는 도구 전부를 보냅니다. %s", exc)

    threading.Thread(target=_run, name="tool-rag-warmup", daemon=True).start()
    return True
