"""현재 저장소의 ToolRetriever를 수정 없이 감싸는 베이스라인 어댑터.

rank()   : retrieve_top_k와 같은 점수(E5 코사인 + _rerank_by_keyword)로 전체 도구를 정렬하고,
           SIMILARITY_THRESHOLD 미만에서 끊습니다(동결 벤치 rank_from_scores와 동일).
           verify=True면 매 질의마다 retrieve_top_k(k=전체, adaptive=False) 결과와 같은지 확인합니다.
select() : CLI 운영점 = retrieve_top_k(query, k=8, adaptive=True)  (theseus_cli: setup_engine(top_k=8))
decide_none은 구현하지 않습니다 → 하네스가 engine_builder 규칙(rag_failed)으로 판정합니다.
"""

from __future__ import annotations

from . import _env  # noqa: F401  # 반드시 theseus_engine보다 먼저

import asyncio
from pathlib import Path

import numpy as np

CLI_BASE_K = 8


class BaselineRetriever:
    name = "baseline"
    uses_torch = True

    def __init__(self, base_k: int = CLI_BASE_K, verify: bool = True) -> None:
        self.base_k = base_k
        self.verify = verify
        self._loop = asyncio.new_event_loop()
        self._retr = None
        self._registry = None
        self.verify_mismatches = 0

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    # --- 하네스 훅 ---------------------------------------------------
    def load(self) -> None:
        from theseus_engine.core.tool_retriever import TOOL_EXAMPLE_QUERIES, ToolRetriever
        from theseus_engine.tools.core.base_tools import ToolRegistry

        if self._retr is not None:
            return
        ToolRetriever._instance = None  # 싱글턴 초기화(같은 프로세스의 이전 상태 배제)
        self._retr = ToolRetriever(ToolRegistry())
        if self._retr._effective_examples != TOOL_EXAMPLE_QUERIES:
            raise RuntimeError("피드백 로그가 few-shot 예시에 섞였습니다(THESEUS_DATA_DIR 고정 실패)")
        self._retr._load_model()

    def index(self, registry) -> None:
        self.load()
        self._registry = registry
        self._retr._full_registry = registry
        self._run(self._retr._ensure_indexed())

    def rank(self, query: str) -> list[tuple[str, float]]:
        from theseus_engine.core.tool_retriever import ESSENTIAL_TOOL_NAMES, SIMILARITY_THRESHOLD

        r = self._retr
        qv = r._get_cached_query_vec(f"query: {query}")
        if qv is None:
            qv = r._model.encode(f"query: {query}", normalize_embeddings=True, show_progress_bar=False)
        scores = r._rerank_by_keyword(query, r._tool_embeddings @ qv)
        out = []
        for idx in np.argsort(scores)[::-1]:  # retrieve_top_k 6단계와 같은 정렬식
            s = float(scores[idx])
            if s < SIMILARITY_THRESHOLD:
                break
            out.append((r._tool_names[idx], s))
        if self.verify:
            full = self._run(r.retrieve_top_k(query, self._registry, k=len(r._tool_names), adaptive=False))
            via_retriever = [t.name for t in full if t.name not in ESSENTIAL_TOOL_NAMES]
            mine = [n for n, _ in out if n not in ESSENTIAL_TOOL_NAMES]
            if via_retriever != mine:
                self.verify_mismatches += 1
        return out

    def select(self, query: str) -> list[str]:
        got = self._run(self._retr.retrieve_top_k(query, self._registry, k=self.base_k, adaptive=True))
        return [t.name for t in got]

    def clear_cache(self) -> None:
        self._retr._query_cache.clear()
        self._retr._query_cache_order.clear()

    def meta(self) -> dict:
        from theseus_engine.core.tool_retriever import SIMILARITY_THRESHOLD

        return {
            "wraps": "theseus_engine.core.tool_retriever.ToolRetriever (unchanged)",
            "model": _env.MODEL_NAME,
            "model_revision_expected": _env.MODEL_REVISION,
            "model_revision_cached_main": _env.cached_main_revision(),
            "pinned_snapshot_cached": (Path(_env.PINNED_SNAPSHOT) / "model.safetensors").exists(),
            "similarity_threshold": SIMILARITY_THRESHOLD,
            "select": f"retrieve_top_k(k={self.base_k}, adaptive=True)",
            "verify_rank_vs_retrieve_top_k": self.verify,
            "verify_mismatches": self.verify_mismatches,
        }
