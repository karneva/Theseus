"""Tool RAG 테스트용 가짜 임베더와 헬퍼(모델 파일 없이 결정적으로 동작)."""

from __future__ import annotations

import dataclasses
import hashlib
import os
from pathlib import Path

import numpy as np

from theseus_engine.config import get_tool_rag_settings
from theseus_engine.core.tool_rag.cache import EmbeddingCache
from theseus_engine.core.tool_rag.lexical import bm25_tokens
from theseus_engine.core.tool_rag.retriever import ToolRetriever


class FakeEmbedder:
    """토큰 해시 무작위 투영의 합(bag of tokens). 같은 단어를 공유하는 텍스트끼리 코사인이 높습니다."""

    dim = 64
    query_prefix = "query: "
    passage_prefix = "passage: "
    fingerprint = "fake:bow64"

    def __init__(self) -> None:
        self.calls = 0
        self.texts_encoded = 0

    def _token_vec(self, token: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha1(token.encode("utf-8")).digest()[:4], "little")
        return np.random.default_rng(seed).standard_normal(self.dim).astype(np.float32)

    def encode(self, texts):
        self.calls += 1
        self.texts_encoded += len(texts)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            body = text.split(": ", 1)[1] if text.startswith(("query: ", "passage: ")) else text
            for token in bm25_tokens(body):
                out[i] += self._token_vec(token)
            if not out[i].any():
                out[i, 0] = 1.0
        return out / np.linalg.norm(out, axis=1, keepdims=True)


def fake_settings(**changes):
    base = dataclasses.replace(get_tool_rag_settings(), feedback="off", cache_dir=None)
    return dataclasses.replace(base, **changes)


def make_retriever(embedder: FakeEmbedder | None = None, *, none_rule=None, **settings_changes) -> ToolRetriever:
    return ToolRetriever(
        embedder=embedder or FakeEmbedder(),
        settings=fake_settings(**settings_changes),
        cache=EmbeddingCache(None),
        none_rule=none_rule,
    )


def real_model_dir() -> Path | None:
    """실제 ONNX 모델 디렉터리(있을 때만). THESEUS_EMBED_MODEL_DIR → 기본 경로 순."""
    from theseus_engine.config import resolve_embed_model_dir

    candidate = Path(os.getenv("THESEUS_EMBED_MODEL_DIR") or resolve_embed_model_dir())
    return candidate if (candidate / "model.onnx").is_file() else None
