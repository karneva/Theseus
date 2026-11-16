"""Tool RAG 검색기의 첫 모델 로드·인덱스 구축이 이벤트 루프를 막지 않는지 검증합니다.

첫 로드를 이벤트 루프에서 바로 돌리면 같은 루프의 Kafka consumer heartbeat가 끊겨 group에서 빠지고
/health와 다른 스트림도 멈춥니다. v2에서는 retrieve()가 retrieve_sync를 스레드에서 돌립니다.
"""

import asyncio
import threading
import time
import unittest
from unittest.mock import patch

from tests.fixtures.tool_rag_fakes import FakeEmbedder, fake_settings
from theseus_engine.core.tool_rag import embedding
from theseus_engine.core.tool_rag.cache import EmbeddingCache
from theseus_engine.core.tool_rag.retriever import ToolRetriever
from theseus_engine.tools.core import ALL_CORE_TOOLS
from theseus_engine.tools.core.base_tools import ToolRegistry


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    for cls in ALL_CORE_TOOLS[:6]:
        reg.register(cls())
    return reg


class _SlowEmbedder(FakeEmbedder):
    instances = 0
    init_threads: list[int] = []

    def __init__(self) -> None:
        super().__init__()
        type(self).instances += 1
        type(self).init_threads.append(threading.get_ident())
        time.sleep(0.3)


class ToolRetrieverModelLoadTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        embedding.reset_embedders()
        _SlowEmbedder.instances = 0
        _SlowEmbedder.init_threads = []
        self._patch = patch.object(embedding, "OnnxE5Embedder", lambda *a, **k: _SlowEmbedder())
        self._patch.start()
        self.retriever = ToolRetriever(settings=fake_settings(none_mode="off"), cache=EmbeddingCache(None))

    def tearDown(self) -> None:
        self._patch.stop()
        embedding.reset_embedders()

    async def test_first_model_load_runs_off_the_event_loop(self) -> None:
        loop_thread = threading.get_ident()
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        ticker_task = asyncio.create_task(ticker())
        try:
            result = await self.retriever.retrieve("파일 읽어줘", _registry())
        finally:
            ticker_task.cancel()

        self.assertEqual(_SlowEmbedder.instances, 1)
        self.assertNotEqual(_SlowEmbedder.init_threads[0], loop_thread)
        # 로드하는 0.3초 동안 루프가 계속 돌았어야 합니다(막혔다면 0~1회).
        self.assertGreaterEqual(ticks, 5)
        self.assertTrue(result.names)

    async def test_concurrent_first_calls_load_model_and_build_index_once(self) -> None:
        reg = _registry()
        await asyncio.gather(*(self.retriever.retrieve(f"질의 {i}", reg) for i in range(4)))
        self.assertEqual(_SlowEmbedder.instances, 1)
        self.assertEqual(len(self.retriever._indexes), 1)

    async def test_model_failure_is_remembered(self) -> None:
        embedding.reset_embedders()

        def boom(*_a, **_k):
            raise embedding.EmbedderUnavailableError("no model")

        with patch.object(embedding, "OnnxE5Embedder", boom) as _:
            with self.assertRaises(embedding.EmbedderUnavailableError):
                self.retriever.retrieve_sync("x", _registry())
            self.assertFalse(self.retriever.is_ready())
            with self.assertRaises(embedding.EmbedderUnavailableError):
                self.retriever.retrieve_sync("x", _registry())


if __name__ == "__main__":
    unittest.main()
