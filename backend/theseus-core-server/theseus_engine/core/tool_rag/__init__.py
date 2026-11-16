"""Tool RAG v2: 질의에 맞는 도구 스키마만 골라 LLM에 보내는 도구 검색.

구성(자세한 근거와 측정은 docs/architecture/tool-rag.md):

    embedding.py    Embedder 프로토콜, ONNX(int8, 기본) / sentence-transformers 백엔드, 프로세스 싱글턴
    cache.py        텍스트→벡터 캐시(메모리 + 선택적 디스크 npz)
    text.py         도구 → passage / 앵커 / BM25 문서 / 커버리지 텍스트 레시피
    tool_gloss.py   도구 공통 영→한 용어집
    lexical.py      BM25, 토크나이저(한글 bigram), 커버리지
    index.py        불변 ToolIndex와 레지스트리 fingerprint
    selector.py     비용 인지 슬롯, none 판정, 전달 집합 조립(순수 함수)
    calibration.py  none 판정 보정값 로더
    retriever.py    ToolRetriever(인덱스 LRU, 질의 캐시, retrieve/rank)

설정은 theseus_engine.config.get_tool_rag_settings() 한 곳에서 읽습니다.
"""

from theseus_engine.core.tool_rag.embedding import (
    Embedder,
    EmbedderUnavailableError,
    OnnxE5Embedder,
    SentenceTransformerEmbedder,
    get_embedder,
)
from theseus_engine.core.tool_rag.examples import (
    ESSENTIAL_TOOL_NAMES,
    TOOL_EXAMPLE_QUERIES,
    TOOL_SEARCH_NAME,
)
from theseus_engine.core.tool_rag.retriever import (
    TOOL_SEARCH_REMINDER,
    RetrievalResult,
    ToolRetriever,
    extract_history_tool_names,
    get_tool_retriever,
    set_tool_retriever,
    start_background_warmup,
)
from theseus_engine.core.tool_rag.selector import NoneRule, assemble, decide_none, select_slots

__all__ = [
    "ESSENTIAL_TOOL_NAMES",
    "Embedder",
    "EmbedderUnavailableError",
    "NoneRule",
    "OnnxE5Embedder",
    "RetrievalResult",
    "SentenceTransformerEmbedder",
    "TOOL_EXAMPLE_QUERIES",
    "TOOL_SEARCH_NAME",
    "TOOL_SEARCH_REMINDER",
    "ToolRetriever",
    "assemble",
    "decide_none",
    "extract_history_tool_names",
    "get_embedder",
    "get_tool_retriever",
    "select_slots",
    "set_tool_retriever",
    "start_background_warmup",
]
