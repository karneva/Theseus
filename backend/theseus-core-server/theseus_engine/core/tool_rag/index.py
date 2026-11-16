"""레지스트리 → 불변 검색 인덱스.

인덱스는 전체 레지스트리 기준으로 하나만 만들고, 가시성·RBAC·tool_search 대상은 질의 시점에 후보 집합으로 거릅니다.
그래서 서버 조립, tool_search, 사후 훅이 같은 인덱스를 공유하고, 보이는 범위가 달라도 재인덱싱하지 않습니다.

fingerprint = sha256(도구별 (이름, 설명, example_queries, 입력 스키마) + 피드백 버전 + 임베더 fingerprint + 레시피 버전).
v1은 도구 이름 집합만 비교해서 설명·스키마가 바뀌어도 재인덱싱하지 않았습니다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Mapping, Sequence

import numpy as np

from theseus_engine.core.tool_rag.examples import TOOL_EXAMPLE_QUERIES, TOOL_SEARCH_NAME
from theseus_engine.core.tool_rag.lexical import BM25, coverage_tokens
from theseus_engine.core.tool_rag.text import (
    RECIPE_VERSION,
    anchor_body,
    bm25_document,
    coverage_document,
    passage_body,
    schema_cost_chars,
    tool_input_schema,
)


def static_examples(tool: Any) -> list[str]:
    """정적 few-shot: 코어 도구 예시 + 도구 클래스의 example_queries (중복 제거, 순서 유지)."""
    out = list(TOOL_EXAMPLE_QUERIES.get(tool.name, []))
    attr = getattr(tool, "example_queries", None)
    if isinstance(attr, (list, tuple)):
        for q in attr:
            if isinstance(q, str) and q and q not in out:
                out.append(q)
    return out


def merged_examples(tool: Any, feedback: Mapping[str, Sequence[str]]) -> list[str]:
    out = static_examples(tool)
    for q in feedback.get(tool.name, ()):
        if q and q not in out:
            out.append(q)
    return out


@lru_cache(maxsize=512)
def _model_schema_digest(input_model: Any) -> str:
    try:
        schema = input_model.model_json_schema()
    except Exception:
        return "noschema"
    return hashlib.sha1(json.dumps(schema, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _tool_digest(tool: Any) -> str:
    attr = getattr(tool, "example_queries", None)
    parts = [
        str(tool.name),
        str(getattr(tool, "description", "") or ""),
        json.dumps(list(attr) if isinstance(attr, (list, tuple)) else [], ensure_ascii=False),
        _model_schema_digest(getattr(tool, "input_model", None)),
    ]
    return hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()


def registry_fingerprint(tools: Sequence[Any], *, embedder_fingerprint: str, feedback_version: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"{RECIPE_VERSION}\0{embedder_fingerprint}\0{feedback_version}\0".encode("utf-8"))
    for tool in tools:
        digest.update(_tool_digest(tool).encode("ascii"))
    return digest.hexdigest()


@dataclass(frozen=True)
class ToolIndex:
    fingerprint: str
    names: tuple[str, ...]
    tools: tuple[Any, ...]
    passages: np.ndarray  # (T, d) 순위용
    anchors: np.ndarray  # (T, d) none 판정용
    bm25: BM25
    coverage_vocab: frozenset[str]
    costs: Mapping[str, float]
    anchor_mask: np.ndarray  # tool_search를 뺀 도구
    vector_keys: tuple[str, ...] = field(default=())

    @property
    def size(self) -> int:
        return len(self.names)


@dataclass(frozen=True)
class IndexTexts:
    passages: list[str]
    anchors: list[str]
    bm25_docs: list[list[str]]
    coverage_vocab: frozenset[str]
    costs: dict[str, float]


def build_texts(
    tools: Sequence[Any], *, feedback: Mapping[str, Sequence[str]], passage_prefix: str
) -> IndexTexts:
    passages, anchors, docs = [], [], []
    vocab: set[str] = set()
    costs: dict[str, float] = {}
    for tool in tools:
        schema = tool_input_schema(tool)
        fixed = static_examples(tool)
        shots = merged_examples(tool, feedback)
        passages.append(passage_prefix + passage_body(tool, shots, schema))
        anchors.append(passage_prefix + anchor_body(tool, fixed))
        docs.append(bm25_document(tool, shots, schema))
        vocab.update(coverage_tokens(coverage_document(tool, fixed, schema)))
        costs[tool.name] = schema_cost_chars(tool)
    return IndexTexts(passages, anchors, docs, frozenset(vocab), costs)


def anchor_mask(names: Sequence[str]) -> np.ndarray:
    return np.array([n != TOOL_SEARCH_NAME for n in names], dtype=bool)
