"""Tool RAG 회귀 테스트(네트워크 없음).

1. 어휘 경로(모델 불필요, 항상 실행): 평가셋에 없는 고정 질의에서 BM25 상위 3에 기대 도구가 있어야 합니다.
   tool_search의 lexical fallback이 이 경로를 씁니다.
2. 전체 v2(ONNX 모델이 있을 때만): 같은 고정 질의 + 평가셋 dev 분할 하네스 지표가 기준 이상이고,
   커밋된 results/v2_dev.json과 질의별 순위·전달 집합이 같아야 합니다. test 분할은 여기서 쓰지 않습니다.
"""

import json
import unittest
from pathlib import Path

from tests.fixtures.tool_rag_fakes import real_model_dir
from theseus_engine.core.tool_rag.examples import ESSENTIAL_TOOL_NAMES
from theseus_engine.core.tool_rag.index import merged_examples
from theseus_engine.core.tool_rag.lexical import BM25
from theseus_engine.core.tool_rag.text import bm25_document, tool_input_schema
from theseus_engine.tools.core import ALL_CORE_TOOLS
from theseus_engine.tools.core.base_tools import ToolRegistry

RESULTS = Path(__file__).resolve().parents[1] / "benchmarks" / "tool_rag" / "results"
EVAL_SET = Path(__file__).resolve().parents[1] / "benchmarks" / "tool_rag" / "eval_set.jsonl"

# (질의, 상위 3 안에 있어야 할 도구). 평가셋 질의와 겹치지 않게 새로 쓴 질의입니다.
FIXED_QUERIES = [
    ("웹에서 파이썬 3.13 릴리스 노트 검색해줘", "web_search"),
    ("이 링크 페이지 내용 가져와줘", "web_fetch"),
    ("할 일 체크리스트 업데이트해줘", "todo_write"),
    ("이 내용 메모리에 저장해둬", "memory_write"),
    ("실험용 워크트리 하나 만들어줘", "enter_worktree"),
    ("백그라운드 작업 로그 출력 보여줘", "task_output"),
    ("저장된 스킬 목록 알려줘", "skill_list"),
    ("MCP 서버 리소스 목록 보여줘", "list_mcp_resources"),
    ("이 함수 정의 위치 찾아줘", "lsp"),
    ("긴 대화 요약해서 줄여줘", "brief"),
    ("서브 에이전트한테 이 작업 맡겨", "agent"),
    ("find references to this symbol", "lsp"),
    ("stop the running background task", "task_stop"),
    ("save this workflow as a reusable skill", "skill_save"),
]

# 커밋된 베이스라인(v1) dev 결과(results/baseline_dev.json)보다 확실히 나아야 하는 하한(설계서 기준)
DEV_FLOORS = {"r3": 0.88, "set_recall_delivered": 0.95}
# tool_search(약 140 토큰)를 일부만 보내는 턴마다 고정으로 넣은 뒤(R2) dev 평균은 1761.7입니다.
DEV_TOKEN_CEILING = 1800.0


def core_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for cls in ALL_CORE_TOOLS:
        reg.register(cls())
    return reg


class FixedQueriesAreNewTest(unittest.TestCase):
    def test_fixed_queries_are_not_in_eval_set(self) -> None:
        queries = {json.loads(line)["query"] for line in EVAL_SET.read_text(encoding="utf-8").splitlines() if line}
        for q, _ in FIXED_QUERIES:
            self.assertNotIn(q, queries)


class LexicalRegressionTest(unittest.TestCase):
    def test_bm25_top3_contains_expected_tool(self) -> None:
        tools = core_registry().list_tools()
        bm = BM25([bm25_document(t, merged_examples(t, {}), tool_input_schema(t)) for t in tools])
        for query, expected in FIXED_QUERIES:
            with self.subTest(query=query):
                s = bm.normalized_scores(query)
                ranked = [tools[i].name for i in sorted(range(len(tools)), key=lambda i: -s[i])]
                top3 = [n for n in ranked if n not in ESSENTIAL_TOOL_NAMES][:3]
                self.assertIn(expected, top3)


def _model_ready() -> bool:
    if real_model_dir() is None:
        return False
    try:
        import onnxruntime  # noqa: F401
        import sentencepiece  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(_model_ready(), "Tool RAG ONNX 모델 없음")
class V2RegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import dataclasses

        from tests.fixtures.tool_rag_fakes import fake_settings
        from theseus_engine.core.tool_rag.cache import EmbeddingCache
        from theseus_engine.core.tool_rag.retriever import ToolRetriever

        cls.reg = core_registry()
        cls.names = [t.name for t in cls.reg.list_tools()]
        settings = dataclasses.replace(fake_settings(), embed_model_dir=str(real_model_dir()))
        cls.retr = ToolRetriever(settings=settings, cache=EmbeddingCache(None))

    def test_fixed_queries(self) -> None:
        for query, expected in FIXED_QUERIES:
            with self.subTest(query=query):
                res = self.retr.retrieve_sync(query, self.reg, candidates=self.names)
                self.assertIn(expected, [n for n, _ in res.ranked][:3])
                self.assertIn(expected, res.names)  # 실제 전달 집합에도 들어감
                self.assertFalse(res.is_none)

    def test_packaged_calibration_applies_only_in_soft_mode(self) -> None:
        # none 판정은 기본으로 꺼져 있고(THESEUS_TOOL_RAG_NONE_MODE=off), soft로 켜면 동봉 보정 규칙이 실제 모델의
        # fingerprint·레시피와 맞아 적용됩니다. soft fallback 동작 자체는 단위 테스트(가짜 임베더)가 봅니다.
        query = "구글 캘린더에 일정 등록해줘"
        off = self.retr.retrieve_sync(query, self.reg, candidates=self.names)
        self.assertFalse(off.is_none)
        rule = self.retr.none_rule()
        self.assertIsNotNone(rule)
        res = self.retr.retrieve_sync(query, self.reg, candidates=self.names, none_mode="soft")
        self.assertEqual(res.is_none, rule.is_none(res.top1, res.coverage))
        if res.is_none:
            self.assertEqual(res.slot_names[-1], "tool_search")
            self.assertLessEqual(len(res.slot_names), 4)

    def test_dev_split_metrics_and_parity_with_committed_results(self) -> None:
        try:
            import tiktoken  # noqa: F401
        except ImportError:
            self.skipTest("tiktoken 없음(하네스 토큰 지표용)")
        from benchmarks.tool_rag import harness
        from benchmarks.tool_rag.v2 import V2Retriever

        result = harness.evaluate(
            V2Retriever(threads=2, model_dir=str(real_model_dir())), split="dev", latency_passes=0
        )
        s = result["summary"]
        baseline = json.loads((RESULTS / "baseline_dev.json").read_text(encoding="utf-8"))["summary"]
        for key, floor in DEV_FLOORS.items():
            self.assertGreaterEqual(s[key], floor, key)
            self.assertGreater(s[key], baseline[key], key)
        self.assertGreater(s["mrr"], baseline["mrr"])
        self.assertLessEqual(s["avg_selected_schema_tokens"], DEV_TOKEN_CEILING)
        self.assertLess(s["avg_selected_schema_tokens"], baseline["avg_selected_schema_tokens"])

        committed = RESULTS / "v2_dev.json"
        if not committed.is_file():
            self.skipTest("results/v2_dev.json 없음")
        ref = {x["id"]: x for x in json.loads(committed.read_text(encoding="utf-8"))["per_item"]}
        for item in result["per_item"]:
            with self.subTest(id=item["id"]):
                want = ref[item["id"]]
                self.assertEqual([n for n, _ in item["pred_sim_top8"]], [n for n, _ in want["pred_sim_top8"]])
                self.assertEqual(sorted(item["delivered"]), sorted(want["delivered"]))
                self.assertEqual(item["none_pred"], want["none_pred"])


if __name__ == "__main__":
    unittest.main()
