from __future__ import annotations

import asyncio
import json
import logging

from src.config import settings
from src.db.postgres import SessionLocal
from src.db.repositories.core_runs import CoreRunRepositoryContext
from src.tool_build.processor import ToolBuildProcessor
from src.tool_build.publisher import KafkaToolBuildEventPublisher

logger = logging.getLogger(__name__)


class ToolBuildKafkaConsumer:
    """승인된 PLAN의 Tool 빌드 요청을 Kafka에서 비동기로 소비합니다.

    빌드와 결과 발행이 모두 끝난 뒤 offset을 수동 커밋해 처리 중 장애가 발생한 요청을
    유실하지 않도록 합니다.
    """

    def __init__(self) -> None:
        self.bootstrap_servers = settings.CORE_KAFKA_BOOTSTRAP_SERVERS
        self.group_id = settings.CORE_KAFKA_TOOL_BUILD_CONSUMER_GROUP_ID
        self.topic = settings.KAFKA_TOPIC_TOOL_BUILD_REQUEST
        self.publisher = KafkaToolBuildEventPublisher()
        self.processor = ToolBuildProcessor(
            publisher=self.publisher,
            checkpoint_repo_factory=lambda: CoreRunRepositoryContext(
                SessionLocal,
                lease_ttl_seconds=settings.CORE_RUN_LEASE_TTL_SECONDS,
            ),
        )
        self._consumer = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        from aiokafka import AIOKafkaConsumer

        self._consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
            key_deserializer=lambda value: value.decode("utf-8") if value else None,
        )
        await self._consumer.start()
        await self.publisher.start()
        # 프로세스 재시작 전에 발행하지 못한 결과 이벤트를 새 요청보다 먼저 복구합니다.
        await self.processor.republish_pending_events(
            limit=settings.CORE_RUN_EVENT_REPUBLISH_BATCH_SIZE
        )
        self._task = asyncio.create_task(self._consume_loop())
        logger.info(
            "Tool build Kafka consumer started. bootstrap=%s topic=%s group=%s",
            self.bootstrap_servers,
            self.topic,
            self.group_id,
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None
        await self.publisher.stop()
        logger.info("Tool build Kafka consumer stopped.")

    async def _consume_loop(self) -> None:
        assert self._consumer is not None
        async for message in self._consumer:
            try:
                await self.processor.process_message(message.value)
                # Tool 생성 결과까지 발행된 경우에만 요청 메시지 처리를 완료합니다.
                await self._consumer.commit()
            except Exception as exc:
                logger.error("Tool build Kafka message handling failed: %s", exc, exc_info=True)


async def start_tool_build_consumer() -> ToolBuildKafkaConsumer | None:
    if not settings.CORE_KAFKA_CONSUMER_ENABLED or not settings.CORE_TOOL_BUILD_CONSUMER_ENABLED:
        logger.info("Tool build Kafka consumer is disabled.")
        return None

    consumer = ToolBuildKafkaConsumer()
    await consumer.start()
    return consumer
