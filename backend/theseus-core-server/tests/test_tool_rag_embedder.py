"""ONNX 임베더 검증(실제 모델 필요). 모델 디렉터리가 없으면 건너뜁니다.

모델 준비: python scripts/provision_tool_rag_model.py --out ~/.theseus/models/e5-small-int8
(또는 THESEUS_EMBED_MODEL_DIR로 경로 지정)
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

from tests.fixtures.tool_rag_fakes import real_model_dir

MODEL_DIR = real_model_dir()
GOLDEN = Path(__file__).parent / "fixtures" / "e5_small_golden.json"
SERVER_DIR = Path(__file__).resolve().parents[1]


def _onnx_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
        import sentencepiece  # noqa: F401
    except ImportError:
        return False
    return True


class ModelIntegrityTest(unittest.TestCase):
    """embedder.json의 sha256과 실제 파일이 다르면 로드를 거부합니다(모델 불필요, onnxruntime import 전에 검사)."""

    def _model_dir(self, tmp: str, *, declared: str | None) -> Path:
        directory = Path(tmp)
        (directory / "model.onnx").write_bytes(b"not really an onnx model")
        meta = {"dim": 384, "pooling": "mean"}
        if declared is not None:
            meta["sha256"] = declared
        (directory / "embedder.json").write_text(json.dumps(meta), encoding="utf-8")
        return directory

    def test_mismatched_model_sha_is_rejected(self) -> None:
        import tempfile

        from theseus_engine.core.tool_rag.embedding import EmbedderUnavailableError, OnnxE5Embedder

        with tempfile.TemporaryDirectory() as tmp:
            directory = self._model_dir(tmp, declared="0" * 64)
            with self.assertRaises(EmbedderUnavailableError) as ctx:
                OnnxE5Embedder(directory)
            self.assertIn("sha256", str(ctx.exception))

    def test_matching_sha_passes_integrity_check(self) -> None:
        import hashlib
        import tempfile

        from theseus_engine.core.tool_rag.embedding import EmbedderUnavailableError, OnnxE5Embedder

        with tempfile.TemporaryDirectory() as tmp:
            directory = self._model_dir(tmp, declared=hashlib.sha256(b"not really an onnx model").hexdigest())
            with self.assertRaises(EmbedderUnavailableError) as ctx:  # 해시는 통과, 그다음 단계(토크나이저 없음 등)에서 실패
                OnnxE5Embedder(directory)
            self.assertNotIn("sha256", str(ctx.exception))


@unittest.skipUnless(MODEL_DIR is not None and _onnx_available(), "Tool RAG ONNX 모델 또는 onnxruntime 없음")
class OnnxEmbedderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from theseus_engine.core.tool_rag.embedding import OnnxE5Embedder

        cls.emb = OnnxE5Embedder(MODEL_DIR, threads=2)
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_spec_and_fingerprint(self) -> None:
        self.assertEqual(self.emb.dim, 384)
        self.assertEqual(self.emb.query_prefix, "query: ")
        self.assertTrue(self.emb.fingerprint.startswith("onnx:"))
        from theseus_engine.core.tool_rag.embedding import file_sha256

        actual = file_sha256(Path(MODEL_DIR) / "model.onnx")
        self.assertTrue(self.emb.fingerprint.startswith(f"onnx:{actual}:"))

    def test_golden_vectors_against_torch_reference(self) -> None:
        texts = [item["text"] for item in self.golden["items"]]
        ref = np.asarray([item["vector"] for item in self.golden["items"]], dtype=np.float32)
        got = self.emb.encode(texts)
        cos = (got * ref).sum(axis=1)
        int8 = "int8" in (self.emb.spec.quantization or "")
        self.assertTrue((cos >= (0.99 if int8 else 0.9999)).all(), cos)
        np.testing.assert_allclose(np.linalg.norm(got, axis=1), 1.0, atol=1e-5)

    def test_bitwise_deterministic_across_threads_and_repeats(self) -> None:
        from theseus_engine.core.tool_rag.embedding import OnnxE5Embedder

        texts = ["query: 체크리스트 업데이트해줘", "passage: web_fetch (web fetch): Fetch a URL."]
        base = self.emb.encode(texts)
        for threads in (1, 4):
            other = OnnxE5Embedder(MODEL_DIR, threads=threads)
            np.testing.assert_array_equal(base, other.encode(texts))
        np.testing.assert_array_equal(base, self.emb.encode(texts))
        # 배치 구성이 달라도 같은 문장은 같은 벡터(batch 1 고정)
        np.testing.assert_array_equal(base[1], self.emb.encode([texts[1]])[0])

    def test_spm_ids_match_tokenizer_json(self) -> None:
        tok_json = os.getenv("THESEUS_TEST_TOKENIZER_JSON")
        if not tok_json or not Path(tok_json).is_file():
            self.skipTest("THESEUS_TEST_TOKENIZER_JSON(e5 tokenizer.json) 미지정")
        try:
            from tokenizers import Tokenizer
        except ImportError:
            self.skipTest("tokenizers 미설치")
        from theseus_engine.core.tool_rag.embedding import SpmXlmrTokenizer

        hf = Tokenizer.from_file(tok_json)
        hf.enable_truncation(max_length=512)
        spm = SpmXlmrTokenizer(MODEL_DIR / "sentencepiece.bpe.model")
        cases = [
            "query: 이 파일 읽어줘",
            "passage: read_file (read file): Read a text file. 입력: path, offset, limit.",
            "trailing space   ",
            "  leading and  double  spaces",
            "탭\t과 줄바꿈\n포함",
            "emoji 🚀 and ünïcödé, 日本語, ①②",
            "special <s> tokens </s> inline <mask>",
            "",
            "a" * 3000,
        ]
        for text in cases:
            with self.subTest(text=text[:30]):
                self.assertEqual(spm.ids(text), hf.encode(text).ids)


@unittest.skipUnless(MODEL_DIR is not None and _onnx_available(), "Tool RAG ONNX 모델 또는 onnxruntime 없음")
class NoTorchImportTest(unittest.TestCase):
    def test_server_import_and_retrieval_do_not_import_torch(self) -> None:
        code = (
            "import sys\n"
            "import src.main\n"
            "from theseus_engine.core.tool_rag import get_tool_retriever\n"
            "from theseus_engine.tools.core import ALL_CORE_TOOLS\n"
            "from theseus_engine.tools.core.base_tools import ToolRegistry\n"
            "reg = ToolRegistry()\n"
            "[reg.register(c()) for c in ALL_CORE_TOOLS]\n"
            "r = get_tool_retriever().retrieve_sync('웹 검색해줘', reg, candidates=[t.name for t in reg.list_tools()])\n"
            "assert 'web_search' in r.names, r.names\n"
            "print('torch' in sys.modules, 'sentence_transformers' in sys.modules)\n"
        )
        env = dict(
            os.environ, THESEUS_EMBED_MODEL_DIR=str(MODEL_DIR), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            cwd=SERVER_DIR,
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertEqual(out.stdout.strip().splitlines()[-1], "False False")


if __name__ == "__main__":
    unittest.main()
