"""Tool RAG v2 순수 단위 테스트(모델 불필요): 어휘·용어집·선택 규칙·none 판정·인덱스/캐시·피드백 로거."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from pydantic import BaseModel, Field

from tests.fixtures.tool_rag_fakes import FakeEmbedder, make_retriever
from theseus_engine.core.tool_rag import lexical, selector
from theseus_engine.core.tool_rag.cache import EmbeddingCache
from theseus_engine.core.tool_rag.examples import ESSENTIAL_TOOL_NAMES
from theseus_engine.core.tool_rag.index import registry_fingerprint
from theseus_engine.core.tool_rag.selector import NoneRule
from theseus_engine.core.tool_rag.text import anchor_body, passage_body, tool_input_schema
from theseus_engine.core.tool_rag.tool_gloss import korean_gloss
from theseus_engine.tools.core import ALL_CORE_TOOLS
from theseus_engine.tools.core.base_tools import BaseTool, ToolRegistry, ToolResult


def core_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for cls in ALL_CORE_TOOLS:
        reg.register(cls())
    return reg


class _In(BaseModel):
    path: str = Field(description="file path")


class _Tool(BaseTool):
    input_model = _In
    permission_level = 1

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description

    async def execute(self, arguments, context):  # pragma: no cover
        return ToolResult(output="ok")


class LexicalTest(unittest.TestCase):
    def test_hangul_bigrams_and_single_syllable(self) -> None:
        self.assertEqual(lexical.bm25_tokens("메모리에"), ["메모", "모리", "리에"])
        self.assertEqual(lexical.bm25_tokens("툴"), ["툴"])

    def test_camel_snake_stopwords_and_stem(self) -> None:
        self.assertEqual(lexical.bm25_tokens("readFile"), ["read", "file"])
        self.assertEqual(lexical.bm25_tokens("web_search the tools"), ["web", "search", "tool"])
        self.assertEqual(lexical.bm25_tokens("searching libraries"), ["search", "library"])
        # 측정한 구성과 같은 동작을 유지하기 위해 고정한 규칙의 알려진 한계: -es를 먼저 떼서 files → fil
        self.assertEqual(lexical.stem("files"), "fil")
        self.assertEqual(lexical.bm25_tokens("is a an"), [])

    def test_bm25_is_deterministic_and_prefers_matching_doc(self) -> None:
        docs = [lexical.bm25_tokens("web search internet 검색"), lexical.bm25_tokens("read file 파일 읽기")]
        bm = lexical.BM25(docs)
        first = bm.scores(lexical.bm25_tokens("파일 읽어줘"))
        second = lexical.BM25(docs).scores(lexical.bm25_tokens("파일 읽어줘"))
        np.testing.assert_array_equal(first, second)
        self.assertGreater(first[1], first[0])
        self.assertEqual(bm.normalized_scores("파일 읽어줘").max(), 1.0)
        self.assertFalse(bm.normalized_scores("zzz").any())

    def test_coverage(self) -> None:
        vocab = set(lexical.coverage_tokens("read_file 파일 읽기"))
        self.assertEqual(lexical.coverage("파일", vocab), 1.0)
        self.assertEqual(lexical.coverage("카카오톡", vocab), 0.0)
        self.assertEqual(lexical.coverage("!!", vocab), 1.0)  # 토큰 없음 → 판단 보류
        self.assertIn("file", vocab)  # snake 부분어


class TextRecipeTest(unittest.TestCase):
    def test_korean_gloss_order_and_dedup(self) -> None:
        self.assertEqual(korean_gloss("read_file", "Read a file. Read files."), "읽기 파일")
        self.assertEqual(korean_gloss("zzz"), "")

    def test_passage_snapshots_for_representative_tools(self) -> None:
        reg = core_registry()
        read = reg.get("read_file")
        body = passage_body(read, ["이 파일 읽어줘"], tool_input_schema(read))
        self.assertTrue(body.startswith("read_file (read file): "))
        self.assertIn(" 입력: ", body)
        self.assertIn(" 한국어: 읽기", body)
        self.assertTrue(body.endswith(" 이 파일 읽어줘"))
        self.assertNotIn("예시 질문:", body)

        web = reg.get("web_search")
        self.assertIn("웹 인터넷", passage_body(web, [], tool_input_schema(web)))
        # 앵커(none 판정용)는 v1 concat 레시피를 그대로 씁니다.
        self.assertEqual(anchor_body(web, ["검색해줘"]), f"web_search: {web.description} 예시 질문: 검색해줘")
        self.assertEqual(anchor_body(web, []), f"web_search: {web.description}")


class SelectorTest(unittest.TestCase):
    COSTS = {"a": 100.0, "b": 300.0, "c": 200.0, "d": 10.0, "e": 10.0}

    def test_cost_aware_slots(self) -> None:
        # i=1 항상, i=2: 2*300=600<=700, i=3: 3*200=600, i=4: 4*10, i=5: 5*10
        self.assertEqual(selector.select_slots(["a", "b", "c", "d", "e"], self.COSTS, budget=700), list("abcde"))
        # 예산을 줄이면 비싼 도구가 빠지지만 1위는 남습니다.
        self.assertEqual(selector.select_slots(["b", "a", "c", "d"], self.COSTS, budget=150), ["b", "d"])
        self.assertEqual(selector.select_slots(["b", "a"], self.COSTS, budget=0), ["b"])

    def test_imax_limits_candidates(self) -> None:
        self.assertEqual(selector.select_slots(list("deabc"), self.COSTS, budget=10_000, imax=2), ["d", "e"])
        self.assertEqual(selector.select_slots([], self.COSTS, budget=700), [])

    def test_none_rule_boundary(self) -> None:
        rule = NoneRule(w_top1=-100.0, w_cov=0.0, b=80.0)  # top1 <= 0.8 → none
        self.assertTrue(rule.is_none(0.8, 0.5))
        self.assertTrue(selector.decide_none(0.79, 1.0, rule))
        self.assertFalse(selector.decide_none(0.81, 1.0, rule))
        self.assertFalse(selector.decide_none(0.0, 0.0, None))

    def test_assemble(self) -> None:
        names, slots = selector.assemble(
            ["read_file"], ["web_fetch"], ["a", "tool_search", "b", "c", "d"],
            is_none=True, soft_keep=3, tool_search_visible=True,
        )
        self.assertEqual(slots, ["a", "b", "c", "tool_search"])
        self.assertEqual(names, ["read_file", "web_fetch", "a", "b", "c", "tool_search"])
        names, slots = selector.assemble([], [], ["a", "b", "c", "d"], is_none=True, soft_keep=3, tool_search_visible=False)
        self.assertEqual(slots, ["a", "b", "c", "d"])  # tool_search가 안 보이면 줄이지도 붙이지도 않음
        names, _ = selector.assemble(["x"], ["x"], ["x", "y"], is_none=False, tool_search_visible=True)
        self.assertEqual(names, ["x", "y"])


class RetrieverIndexTest(unittest.TestCase):
    def test_fingerprint_changes_with_description_and_schema(self) -> None:
        a = _Tool("alpha", "first")
        fp1 = registry_fingerprint([a], embedder_fingerprint="e", feedback_version="none")
        a.description = "changed"
        fp2 = registry_fingerprint([a], embedder_fingerprint="e", feedback_version="none")
        self.assertNotEqual(fp1, fp2)

        class _In2(BaseModel):
            path: str
            extra: int = 0

        b = _Tool("alpha", "changed")
        b.input_model = _In2
        self.assertNotEqual(fp2, registry_fingerprint([b], embedder_fingerprint="e", feedback_version="none"))
        self.assertNotEqual(fp2, registry_fingerprint([a], embedder_fingerprint="other", feedback_version="none"))

    def test_shared_index_is_not_rebuilt_across_candidate_sets(self) -> None:
        emb = FakeEmbedder()
        retr = make_retriever(emb)
        reg = core_registry()
        names = [t.name for t in reg.list_tools()]
        retr.retrieve_sync("파일 읽어줘", reg, candidates=names)
        texts_after_first = emb.texts_encoded
        for cands in (names[:10], names[5:], ["read_file", "tool_search"], names):
            retr.retrieve_sync("다른 질의 " + str(len(cands)), reg, candidates=cands)
        # 질의 4개만 새로 인코딩(인덱스 재구축 없음)
        self.assertEqual(emb.texts_encoded, texts_after_first + 4)

    def test_registry_change_reencodes_only_new_tool(self) -> None:
        emb = FakeEmbedder()
        retr = make_retriever(emb)
        reg = core_registry()
        retr.get_index(reg)
        before = emb.texts_encoded
        reg.register(_Tool("my_custom_weather", "Get the weather forecast for a city."))
        retr.get_index(reg)
        self.assertEqual(emb.texts_encoded, before + 2)  # 새 도구의 passage + anchor

    def test_candidates_are_never_exceeded(self) -> None:
        retr = make_retriever()
        reg = core_registry()
        allowed = ["read_file", "glob", "grep", "web_search", "tool_search", "brief"]
        res = retr.retrieve_sync("bash로 테스트 실행하고 파일 수정해줘", reg, candidates=allowed)
        self.assertTrue(set(res.names) <= set(allowed))
        self.assertTrue({"read_file", "glob", "grep"} <= set(res.names))  # 필수 ∩ 후보
        self.assertNotIn("bash", res.names)

    def test_history_tools_are_pinned_and_soft_none_fallback(self) -> None:
        reg = core_registry()
        names = [t.name for t in reg.list_tools()]
        history = [{"role": "assistant", "content": [{"type": "tool_use", "name": "task_get", "id": "1", "input": {}}]}]
        always_none = NoneRule(0.0, 0.0, 1.0)
        retr = make_retriever(none_rule=always_none, none_mode="soft")
        res = retr.retrieve_sync("노션 페이지 만들어줘", reg, candidates=names, history_messages=history)
        self.assertIn("task_get", res.history_names)
        self.assertTrue(res.is_none)
        self.assertEqual(res.slot_names[-1], "tool_search")
        self.assertLessEqual(len(res.slot_names), 4)
        self.assertTrue(ESSENTIAL_TOOL_NAMES <= set(res.names))

    def test_compat_retrieve_top_k(self) -> None:
        import asyncio

        retr = make_retriever()
        tools = asyncio.run(retr.retrieve_top_k("웹에서 검색해줘", core_registry(), k=3))
        self.assertTrue(ESSENTIAL_TOOL_NAMES <= {t.name for t in tools})


class EmbeddingCacheTest(unittest.TestCase):
    def test_disk_cache_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emb = FakeEmbedder()
            cache = EmbeddingCache(tmp)
            mat, keys, new = cache.get_or_encode("fp", ["a", "b"], emb.encode, emb.dim)
            self.assertEqual(new, 2)
            cache.flush("fp", keys)
            again = EmbeddingCache(tmp)
            mat2, _, new2 = again.get_or_encode("fp", ["b", "a"], emb.encode, emb.dim)
            self.assertEqual(new2, 0)
            np.testing.assert_array_equal(mat2, mat[::-1])
            # 다른 모델 fingerprint와는 섞이지 않습니다.
            _, _, new3 = again.get_or_encode("fp2", ["a"], emb.encode, emb.dim)
            self.assertEqual(new3, 1)


class FeedbackLoggerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(os.environ, {"THESEUS_DATA_DIR": self._tmp.name})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmp.cleanup()

    def test_filters_and_dedup(self) -> None:
        from theseus_engine.core import tool_usage_logger as tul

        self.assertFalse(tul.record_tool_call("이 파일 읽어줘", "read_file", provenance="slot"))  # 필수
        self.assertFalse(tul.record_tool_call("도구 찾아줘", "tool_search", provenance="slot"))
        self.assertFalse(tul.record_tool_call("웹에서 찾아줘", "web_search", provenance=None))  # 출처 없음
        self.assertFalse(tul.record_tool_call("abc", "web_search", provenance="slot"))  # 너무 짧음
        self.assertFalse(tul.record_tool_call("/etc/passwd 읽어", "web_fetch", provenance="slot"))
        self.assertFalse(tul.record_tool_call("src/main.py 정리해", "brief", provenance="slot"))
        self.assertFalse(tul.record_tool_call("키 sk-abcdefghijklmnop 확인", "web_fetch", provenance="slot"))
        for i in range(8):
            self.assertTrue(tul.record_tool_call(f"최신 뉴스 검색 {i}", "web_search", provenance="slot"))
        self.assertTrue(tul.record_tool_call("최신  뉴스 검색 7", "web_search", provenance="hook"))  # 중복(정규화)
        fb, version = tul.load_feedback_queries(5)
        self.assertEqual(len(fb["web_search"]), 5)
        self.assertEqual(fb["web_search"][0], "최신 뉴스 검색 7")
        self.assertEqual(len(set(q.lower() for q in fb["web_search"])), 5)
        self.assertNotEqual(version, "none")

    def test_legacy_records_without_provenance_are_ignored(self) -> None:
        from theseus_engine.core import tool_usage_logger as tul

        path = Path(self._tmp.name) / "tool_usage.jsonl"
        path.write_text(
            json.dumps({"query": "파일 읽어줘", "tool": "read_file"}, ensure_ascii=False) + "\n"
            + json.dumps({"query": "웹 검색해줘", "tool": "web_search"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(tul.load_feedback_queries(5)[0], {})

    def test_feedback_reaches_passage_but_not_anchor(self) -> None:
        from theseus_engine.core import tool_usage_logger as tul

        from theseus_engine.core.tool_rag.index import build_texts

        reg = core_registry()
        retr = make_retriever(feedback="cli")
        fp_before = retr.get_index(reg).fingerprint
        tul.record_tool_call("주간 회의록 요약해줘", "brief", provenance="tool_search")
        self.assertNotEqual(fp_before, retr.get_index(reg).fingerprint)  # 피드백이 바뀌면 재인덱싱

        fb, _ = tul.load_feedback_queries(5)
        built = build_texts(reg.list_tools(), feedback=fb, passage_prefix="passage: ")
        idx = [t.name for t in reg.list_tools()].index("brief")
        self.assertIn("주간 회의록 요약해줘", built.passages[idx])
        self.assertNotIn("주간 회의록 요약해줘", built.anchors[idx])

    def test_log_rotation(self) -> None:
        from theseus_engine.core import tool_usage_logger as tul

        with patch.object(tul, "MAX_LOG_BYTES", 200):
            for i in range(10):
                tul.record_tool_call(f"최신 뉴스 검색 {i}", "web_search", provenance="slot")
        self.assertTrue((Path(self._tmp.name) / "tool_usage.jsonl.1").exists())


if __name__ == "__main__":
    unittest.main()
