"""문장 임베딩 백엔드.

기본은 ONNX Runtime + sentencepiece입니다(torch 불필요). 모델 디렉터리 구성:

    model.onnx                 E5 encoder (기본: multilingual-e5-small 동적 int8)
    sentencepiece.bpe.model    XLM-R 토크나이저 (없으면 tokenizer.json + tokenizers 패키지)
    embedder.json              base_model, revision, sha256, dim, max_length, pooling,
                               query_prefix, passage_prefix, quantization
    toolrag_calibration.json   (선택) none 판정 보정값. calibration.py 참고

모델 디렉터리는 scripts/provision_tool_rag_model.py가 만듭니다(Docker 빌드 단계에서 실행).
파인튜닝한 모델로 바꿀 때는 같은 형식의 디렉터리를 만들고 THESEUS_EMBED_MODEL_DIR만 바꾸면 됩니다.

``SentenceTransformerEmbedder``는 개발·파리티 검증용입니다(requirements-torch.txt). 지연 import라서
기본 경로에서는 torch가 import되지 않습니다.

모든 Embedder는 L2 정규화된 float32 (n, dim) 행렬을 돌려주고, 벡터 캐시와 보정값이 다른 모델 것과
섞이지 않도록 ``fingerprint``를 가집니다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

import numpy as np

from theseus_engine.config import (
    EMBED_BACKEND_ONNX,
    EMBED_BACKEND_SENTENCE_TRANSFORMERS,
    ToolRagSettings,
    get_tool_rag_settings,
)

log = logging.getLogger(__name__)

EMBEDDER_META_FILE = "embedder.json"
MODEL_FILE = "model.onnx"
SPM_FILE = "sentencepiece.bpe.model"
TOKENIZER_JSON_FILE = "tokenizer.json"


class EmbedderUnavailableError(RuntimeError):
    """임베딩 모델을 불러올 수 없음(파일 없음, 패키지 없음 등). 호출자는 검색 없이 폴백합니다."""


@runtime_checkable
class Embedder(Protocol):
    dim: int
    fingerprint: str
    query_prefix: str
    passage_prefix: str

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """L2 정규화된 float32 (len(texts), dim) 행렬. 프리픽스는 호출자가 붙입니다."""
        ...


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return (mat / np.clip(norms, 1e-12, None)).astype(np.float32)


# ───────────────────────────── 토크나이저 ─────────────────────────────
class SpmXlmrTokenizer:
    """sentencepiece.bpe.model(5 MB)로 XLM-R 토큰 ID를 만드는 경량 토크나이저.

    tokenizer.json(17 MB, 25만 어휘)을 tokenizers로 로드하면 RSS가 약 250 MB 늘어서 대신 씁니다.
    transformers XLMRobertaTokenizer와 같은 규칙: fairseq offset +1, spm unk(0) → <unk>(3),
    앞에 <s>(0), 뒤에 </s>(2). 본문 속 특수 토큰 문자열은 특수 토큰으로 처리합니다.
    tokenizer.json과의 ID 일치는 tests/test_tool_rag_embedder.py에서 확인합니다.
    """

    BOS, PAD, EOS, UNK, OFFSET = 0, 1, 2, 3, 1
    _SPECIAL = {"<s>": 0, "<pad>": 1, "</s>": 2, "<unk>": 3, "<mask>": 250001}
    _SPECIAL_RE = re.compile("(" + "|".join(map(re.escape, _SPECIAL)) + ")")

    def __init__(self, spm_path: str | os.PathLike, max_length: int = 512) -> None:
        import sentencepiece as spm

        self._sp = spm.SentencePieceProcessor(model_file=str(spm_path))
        # tokenizers(Precompiled 정규화 + Metaspace)는 정규화 결과 끝에 공백이 남으면 '▁' 토큰을 하나 더 냅니다.
        # sentencepiece는 끝 공백을 지우므로 같은 charsmap 정규화(끝 공백 유지)로 확인해 맞춥니다.
        self._norm = spm.SentencePieceNormalizer(
            model_file=str(spm_path),
            add_dummy_prefix=False,
            escape_whitespaces=False,
            remove_extra_whitespaces=False,
        )
        self._space_id = self._sp.piece_to_id("▁") + self.OFFSET
        self.max_length = max_length

    def _segment(self, text: str) -> list[int]:
        ids = [p + self.OFFSET if p != 0 else self.UNK for p in self._sp.encode(text, out_type=int)]
        if self._norm.normalize(text).endswith(" "):
            ids.append(self._space_id)
        return ids

    def ids(self, text: str) -> list[int]:
        out: list[int] = []
        for part in self._SPECIAL_RE.split(text):
            if not part:
                continue
            if part in self._SPECIAL:
                out.append(self._SPECIAL[part])
            else:
                out.extend(self._segment(part))
        return [self.BOS, *out[: self.max_length - 2], self.EOS]


class _HfTokenizer:
    """tokenizer.json 폴백(파인튜닝 모델이 spm 파일 없이 올 때). tokenizers 패키지가 필요합니다."""

    def __init__(self, path: str | os.PathLike, max_length: int) -> None:
        try:
            from tokenizers import Tokenizer
        except ImportError as exc:  # pragma: no cover - 환경 의존
            raise EmbedderUnavailableError(
                f"{TOKENIZER_JSON_FILE}를 쓰려면 tokenizers 패키지가 필요합니다. "
                f"모델 디렉터리에 {SPM_FILE}를 넣거나 pip install tokenizers 를 실행하세요."
            ) from exc
        self._tok = Tokenizer.from_file(str(path))
        self._tok.enable_truncation(max_length=max_length)

    def ids(self, text: str) -> list[int]:
        return list(self._tok.encode(text).ids)


# ───────────────────────────── ONNX ─────────────────────────────
@dataclass(frozen=True)
class EmbedderSpec:
    base_model: str
    revision: str
    sha256: str
    dim: int
    max_length: int
    pooling: str
    query_prefix: str
    passage_prefix: str
    quantization: str
    tokenizer_sha256: str = ""

    @classmethod
    def load(cls, model_dir: Path) -> "EmbedderSpec":
        meta_path = model_dir / EMBEDDER_META_FILE
        meta: dict = {}
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        else:
            log.warning("[ToolRAG] %s가 없어 e5 기본값(프리픽스 query:/passage:, 384차원)을 씁니다.", meta_path)
        return cls(
            base_model=str(meta.get("base_model", "unknown")),
            revision=str(meta.get("revision", "")),
            sha256=str(meta.get("sha256", "")),
            dim=int(meta.get("dim", 384)),
            max_length=int(meta.get("max_length", 512)),
            pooling=str(meta.get("pooling", "mean")),
            query_prefix=str(meta.get("query_prefix", "query: ")),
            passage_prefix=str(meta.get("passage_prefix", "passage: ")),
            quantization=str(meta.get("quantization", "")),
            tokenizer_sha256=str(meta.get("tokenizer_sha256", "")),
        )


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_sha256(path: Path, actual: str, declared: str) -> None:
    if declared and declared.strip().lower() != actual:
        raise EmbedderUnavailableError(
            f"{path.name}의 sha256({actual[:12]}…)이 {EMBEDDER_META_FILE} 선언값({declared[:12]}…)과 다릅니다. "
            "모델을 바꿨다면 scripts/provision_tool_rag_model.py로 embedder.json을 다시 만들고 none 보정도 다시 하세요."
        )


class OnnxE5Embedder:
    """onnxruntime으로 E5 계열 encoder를 돌리는 임베더(평균 풀링 + L2 정규화).

    batch_size는 1로 고정합니다. 동적 int8 양자화 모델은 활성값 양자화 범위를 배치 단위로 잡기 때문에
    같은 문장도 배치 구성에 따라 벡터가 달라집니다. 1개씩 돌리면 결정적이고 메모리도 적게 씁니다.

    로드할 때 model.onnx(와 sentencepiece 모델)의 실제 sha256을 계산해 embedder.json 선언값과 비교합니다(113 MiB 기준
    약 0.1 s). 다르면 EmbedderUnavailableError를 냅니다. 모델만 바꾸고 embedder.json을 그대로 두면 옛 none 보정값과
    디스크 벡터 캐시가 새 모델 점수와 섞이기 때문입니다. fingerprint도 선언값이 아니라 계산한 해시로 만듭니다.
    """

    def __init__(self, model_dir: str | os.PathLike, *, threads: int = 2, max_length: int | None = None) -> None:
        directory = Path(model_dir)
        model_path = directory / MODEL_FILE
        if not model_path.is_file():
            raise EmbedderUnavailableError(
                f"Tool RAG 임베딩 모델이 없습니다: {model_path}. "
                "scripts/provision_tool_rag_model.py로 만들거나 THESEUS_EMBED_MODEL_DIR을 지정하세요."
            )
        self.spec = EmbedderSpec.load(directory)
        model_sha = file_sha256(model_path)
        _verify_sha256(model_path, model_sha, self.spec.sha256)
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise EmbedderUnavailableError("onnxruntime 패키지가 없습니다(requirements.txt).") from exc

        self.model_dir = directory
        self.dim = self.spec.dim
        self.query_prefix = self.spec.query_prefix
        self.passage_prefix = self.spec.passage_prefix
        self.max_length = int(max_length or self.spec.max_length)
        if self.spec.pooling != "mean":
            raise EmbedderUnavailableError(f"지원하지 않는 pooling: {self.spec.pooling}")

        spm_path = directory / SPM_FILE
        if spm_path.is_file():
            if self.spec.tokenizer_sha256:
                _verify_sha256(spm_path, file_sha256(spm_path), self.spec.tokenizer_sha256)
            try:
                self._tok = SpmXlmrTokenizer(spm_path, max_length=self.max_length)
            except ImportError as exc:
                raise EmbedderUnavailableError("sentencepiece 패키지가 없습니다(requirements.txt).") from exc
            tok_kind = "spm"
        elif (directory / TOKENIZER_JSON_FILE).is_file():
            self._tok = _HfTokenizer(directory / TOKENIZER_JSON_FILE, self.max_length)
            tok_kind = "hf"
        else:
            raise EmbedderUnavailableError(f"{directory}에 {SPM_FILE} 또는 {TOKENIZER_JSON_FILE}가 없습니다.")

        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, int(threads))
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.add_session_config_entry("session.intra_op.allow_spinning", "1")
        self._sess = ort.InferenceSession(str(model_path), sess_options=so, providers=["CPUExecutionProvider"])
        self._input_names = {i.name for i in self._sess.get_inputs()}
        self._out_name = self._sess.get_outputs()[0].name
        self._run_lock = threading.Lock()

        self.fingerprint = f"onnx:{model_sha}:{tok_kind}:{self.max_length}:{self.spec.pooling}"
        self.threads = so.intra_op_num_threads

    def _embed_one(self, text: str) -> np.ndarray:
        ids = np.asarray([self._tok.ids(text)], dtype=np.int64)
        mask = np.ones_like(ids)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        with self._run_lock:
            hidden = self._sess.run([self._out_name], feeds)[0]  # (1, T, H) float32
        # attention_mask 가중 평균 풀링(sentence-transformers 1_Pooling과 같은 식)
        m = mask[..., None].astype(np.float32)
        return ((hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None))[0]

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        out = np.stack([self._embed_one(t) for t in texts]).astype(np.float32)
        return _l2_normalize(out)


# ───────────────────────────── sentence-transformers ─────────────────────────────
class SentenceTransformerEmbedder:
    """sentence-transformers(torch) 백엔드. 개발·파리티 검증용(requirements-torch.txt)."""

    query_prefix = "query: "
    passage_prefix = "passage: "

    def __init__(self, model_id: str, revision: str | None = None, *, threads: int | None = None) -> None:
        try:
            for noisy in ("sentence_transformers", "transformers", "huggingface_hub"):
                logging.getLogger(noisy).setLevel(logging.ERROR)
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbedderUnavailableError(
                "THESEUS_EMBED_BACKEND=sentence-transformers에는 requirements-torch.txt 설치가 필요합니다."
            ) from exc
        if threads:
            try:
                import torch

                torch.set_num_threads(int(threads))
            except Exception:  # pragma: no cover
                pass
        self._model = SentenceTransformer(model_id, revision=revision or None, device="cpu")
        self.dim = int(self._model.get_sentence_embedding_dimension() or 384)
        self.fingerprint = f"st:{model_id}@{revision or 'main'}"

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        vecs = self._model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False, batch_size=32)
        return np.asarray(vecs, dtype=np.float32)


# ───────────────────────────── 프로세스 싱글턴 ─────────────────────────────
_EMBEDDERS: dict[tuple, Embedder] = {}
_FAILURES: dict[tuple, EmbedderUnavailableError] = {}
_LOCK = threading.Lock()


def _embedder_key(settings: ToolRagSettings) -> tuple:
    if settings.embed_backend == EMBED_BACKEND_SENTENCE_TRANSFORMERS:
        return (settings.embed_backend, settings.embed_model_id, settings.embed_model_revision, settings.embed_threads)
    return (EMBED_BACKEND_ONNX, os.path.abspath(settings.embed_model_dir), settings.embed_threads, settings.embed_max_length)


def get_embedder(settings: ToolRagSettings | None = None) -> Embedder:
    """설정에 맞는 임베더를 프로세스당 1개만 만듭니다(모델만 싱글턴). 실패도 기억해 매 턴 재시도하지 않습니다."""
    settings = settings or get_tool_rag_settings()
    key = _embedder_key(settings)
    hit = _EMBEDDERS.get(key)
    if hit is not None:
        return hit
    with _LOCK:
        hit = _EMBEDDERS.get(key)
        if hit is not None:
            return hit
        if key in _FAILURES:
            raise _FAILURES[key]
        try:
            if settings.embed_backend == EMBED_BACKEND_SENTENCE_TRANSFORMERS:
                embedder: Embedder = SentenceTransformerEmbedder(
                    settings.embed_model_id, settings.embed_model_revision, threads=settings.embed_threads
                )
            else:
                embedder = OnnxE5Embedder(
                    settings.embed_model_dir, threads=settings.embed_threads, max_length=settings.embed_max_length
                )
        except EmbedderUnavailableError as exc:
            _FAILURES[key] = exc
            log.warning("[ToolRAG] 임베더를 불러오지 못했습니다: %s", exc)
            raise
        except Exception as exc:  # onnxruntime 세션 생성 실패 등
            err = EmbedderUnavailableError(f"임베더 초기화 실패: {exc}")
            _FAILURES[key] = err
            log.warning("[ToolRAG] %s", err)
            raise err from exc
        _EMBEDDERS[key] = embedder
        log.info("[ToolRAG] 임베더 로드 완료: %s", embedder.fingerprint)
        return embedder


def embedder_ready(settings: ToolRagSettings | None = None) -> bool:
    settings = settings or get_tool_rag_settings()
    return _embedder_key(settings) in _EMBEDDERS


def reset_embedders() -> None:
    """테스트용: 싱글턴과 실패 기록을 지웁니다."""
    with _LOCK:
        _EMBEDDERS.clear()
        _FAILURES.clear()
