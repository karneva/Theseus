"""저장소의 Tool RAG v2 구현(theseus_engine/core/tool_rag)을 그대로 감싸는 하네스 어댑터.

    python -m benchmarks.tool_rag.run --variant v2 --split dev

rank()        : ToolRetriever.rank (dense + BM25 융합 점수, 레지스트리 전체)
select()      : ToolRetriever.retrieve_sync(candidates=가시성 통과 도구) 의 전달 집합
                (필수 ∩ 후보 + 비용 인지 슬롯, none이면 상위 3 + tool_search) — 서버 조립과 같은 호출
decide_none() : 같은 호출의 is_none

평가 조건 고정: 피드백 few-shot 끔, 디스크 벡터 캐시 끔, ONNX 스레드 4(Combine 단계 test 측정과 같음).
서버 권장값 2스레드는 --variant-kwargs '{"threads": 2}'로 잽니다.
"""

from __future__ import annotations

from . import _env  # noqa: F401  # 반드시 theseus_engine보다 먼저

import dataclasses
import sys
from pathlib import Path
from typing import Any


def _display_path(path: str | None) -> str | None:
    """결과 JSON에 개인 로컬 경로가 남지 않도록 홈 디렉터리 아래 경로는 ~/... 로 기록합니다."""
    if not path:
        return path
    try:
        rel = Path(path).expanduser().resolve().relative_to(Path.home().resolve())
    except (ValueError, OSError):
        return path
    return "~/" + rel.as_posix()

class V2Retriever:
    name = "v2"
    uses_torch = False

    def __init__(self, threads: int = 4, model_dir: str | None = None, backend: str | None = None, **overrides: Any):
        self.threads = threads
        self.model_dir = model_dir
        self.backend = backend
        self.overrides = overrides
        self._retr = None
        self._registry = None
        self._visible: set[str] = set()
        self._results: dict[str, Any] = {}

    def load(self) -> None:
        from theseus_engine.config import get_tool_rag_settings
        from theseus_engine.core.tool_rag.cache import EmbeddingCache
        from theseus_engine.core.tool_rag.retriever import ToolRetriever

        if self._retr is not None:
            return
        settings = get_tool_rag_settings()
        changes: dict[str, Any] = {"embed_threads": self.threads, "feedback": "off", "cache_dir": None}
        if self.model_dir:
            changes["embed_model_dir"] = self.model_dir
        if self.backend:
            changes["embed_backend"] = self.backend
        changes.update(self.overrides)
        self.settings = dataclasses.replace(settings, **changes)
        self.uses_torch = self.settings.embed_backend != "onnx"
        self._retr = ToolRetriever(settings=self.settings, cache=EmbeddingCache(None))
        self._retr.embedder()  # 모델 로드(콜드 로드 측정 구간)

    def index(self, registry) -> None:
        from theseus_engine.core.tool_visibility import build_visible_registry

        from .harness import _visibility_policy

        self.load()
        self._registry = registry
        visible = build_visible_registry(registry, _visibility_policy(registry))
        self._visible = {t.name for t in visible.list_tools()}
        self._retr.get_index(registry)

    def rank(self, query: str) -> list[tuple[str, float]]:
        return self._retr.rank(query, self._registry)

    def _retrieve(self, query: str):
        hit = self._results.get(query)
        if hit is None:
            hit = self._results[query] = self._retr.retrieve_sync(query, self._registry, candidates=self._visible)
        return hit

    def select(self, query: str) -> list[str]:
        return list(self._retrieve(query).names)

    def decide_none(self, query: str) -> bool:
        return bool(self._retrieve(query).is_none)

    def clear_cache(self) -> None:
        self._retr.clear_query_cache()
        self._results.clear()

    def meta(self) -> dict:
        emb = self._retr.embedder()
        s = self.settings
        return {
            "wraps": "theseus_engine.core.tool_rag.ToolRetriever (repo v2)",
            "embedder_fingerprint": emb.fingerprint,
            "embed_backend": s.embed_backend,
            "embed_model_dir": _display_path(s.embed_model_dir) if s.embed_backend == "onnx" else None,
            "threads": s.embed_threads,
            "bm25_beta": s.bm25_beta,
            "cost_budget": s.cost_budget,
            "rank_alpha": s.rank_alpha,
            "max_candidates": s.max_candidates,
            "none_mode": s.none_mode,
            "none_rule": dataclasses.asdict(self._retr.none_rule()) if self._retr.none_rule() else None,
            "soft_keep": s.soft_keep,
            "feedback": s.feedback,
            "torch_imported": "torch" in sys.modules,
            "sentence_transformers_imported": "sentence_transformers" in sys.modules,
        }


class AllVisibleTools:
    """v1 서버 동작 참조점: 검색 없이 레지스트리 전체를 보냄(하네스가 가시성 필터를 적용).

    순위 지표는 의미가 없고(모두 0점), 전달 집합 재현율·스키마 토큰 비교용입니다.
        python -m benchmarks.tool_rag.run --variant all-visible --registry server --split all --passes 0
    """

    name = "all-visible(v1 server)"
    uses_torch = False

    def index(self, registry) -> None:
        self.names = [t.name for t in registry.list_tools()]

    def rank(self, query: str) -> list[tuple[str, float]]:
        return [(n, 0.0) for n in self.names]

    def select(self, query: str) -> list[str]:
        return list(self.names)
