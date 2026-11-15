"""ToolRetriever의 임베딩 모델 첫 로드가 이벤트 루프를 막지 않는지 검증합니다.

첫 로드(torch import, 모델 다운로드, 가중치 로드)는 수십 초가 걸립니다. 이벤트 루프에서 바로 돌리면
같은 루프의 Kafka consumer heartbeat가 끊겨 group에서 빠지고 /health와 다른 스트림도 멈춥니다.
"""

import asyncio
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from theseus_engine.core.tool_retriever import ToolRetriever


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"{name} description"


class _FakeRegistry:
    def __init__(self, names: list[str]) -> None:
        self._tools = [_FakeTool(n) for n in names]

    def list_tools(self):
        return list(self._tools)


class _FakeModel:
    def encode(self, texts, **_kwargs):
        return np.ones((len(texts), 4))


class ToolRetrieverModelLoadTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        ToolRetriever._instance = None

    def tearDown(self) -> None:
        ToolRetriever._instance = None

    async def test_first_model_load_runs_off_the_event_loop(self) -> None:
        retriever = ToolRetriever(_FakeRegistry(["glob", "grep"]))
        loop_thread = threading.get_ident()
        load_threads: list[int] = []

        def slow_load(self_: ToolRetriever) -> None:
            load_threads.append(threading.get_ident())
            time.sleep(0.3)
            self_._model = _FakeModel()

        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        with patch.object(ToolRetriever, "_load_model", slow_load):
            ticker_task = asyncio.create_task(ticker())
            try:
                await retriever._ensure_indexed()
            finally:
                ticker_task.cancel()

        self.assertEqual(len(load_threads), 1)
        self.assertNotEqual(load_threads[0], loop_thread)
        # 로드하는 0.3초 동안 루프가 계속 돌았어야 합니다(막혔다면 0~1회).
        self.assertGreaterEqual(ticks, 5)
        self.assertEqual(retriever._tool_names, ["glob", "grep"])
        self.assertEqual(retriever._tool_embeddings.shape, (2, 4))

    async def test_concurrent_first_calls_load_model_once(self) -> None:
        retriever = ToolRetriever(_FakeRegistry(["glob"]))
        calls = 0

        def slow_load(self_: ToolRetriever) -> None:
            nonlocal calls
            calls += 1
            time.sleep(0.1)
            self_._model = _FakeModel()

        with patch.object(ToolRetriever, "_load_model", slow_load):
            await asyncio.gather(retriever._ensure_indexed(), retriever._ensure_indexed())

        self.assertEqual(calls, 1)

    async def test_unbound_lock_is_reused_and_foreign_loop_lock_is_replaced(self) -> None:
        retriever = ToolRetriever(_FakeRegistry(["glob"]))
        first = retriever._get_index_lock()
        # 아직 경합한 적 없는 락은 _loop가 None이어도 같은 락을 돌려줘야 합니다.
        self.assertIs(retriever._get_index_lock(), first)

        other_loop = asyncio.new_event_loop()
        try:
            first._loop = other_loop  # 다른 루프에서 경합해 바인딩된 상태를 흉내 냅니다.
            replaced = retriever._get_index_lock()
        finally:
            other_loop.close()
        self.assertIsNot(replaced, first)


if __name__ == "__main__":
    unittest.main()
