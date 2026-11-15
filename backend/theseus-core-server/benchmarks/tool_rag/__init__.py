"""Tool RAG 평가 하네스 패키지.

    from benchmarks.tool_rag import harness
    harness.evaluate(MyRetriever(), split="dev")

import 시 _env가 먼저 실행되어 피드백 로그·HF 오프라인·바이트코드 설정을 고정합니다.
"""

from . import _env  # noqa: F401  # 반드시 가장 먼저

from .harness import (  # noqa: E402
    FROZEN_ESSENTIALS,
    KS,
    Retriever,
    build_registry,
    evaluate,
    format_summary,
    load_eval_set,
)

__all__ = [
    "FROZEN_ESSENTIALS",
    "KS",
    "Retriever",
    "build_registry",
    "evaluate",
    "format_summary",
    "load_eval_set",
]
