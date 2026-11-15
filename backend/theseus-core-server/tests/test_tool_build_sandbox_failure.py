"""sandbox 실패가 TOOL_BUILD_FAILED 이벤트로 원인 정보와 함께 발행되는지 검증합니다.

API/프론트가 실패 원인(errorType, exitCode, timeout, 리소스 제한)을 보여줄 수 있도록
ToolBuildError 메시지가 이벤트에 그대로 실려야 합니다.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.tool_build.builder import ToolBuildError
from src.tool_build.processor import ToolBuildProcessor
from src.tool_build.schemas import ToolBuildFailedEvent, ToolBuildRequestedEvent


class FakePublisher:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, key, event) -> None:
        self.events.append((key, event))


class FailingBuilder:
    async def build(self, event, *, progress_callback=None, chunk_callback=None):
        raise ToolBuildError(
            "SANDBOX_FAILED",
            (
                "Sandbox result.json was not produced. "
                "(errorType=result_missing, exitCode=1, "
                "timedOut=False, resourceLimited=False)"
            ),
        )


def _build_event() -> ToolBuildRequestedEvent:
    return ToolBuildRequestedEvent.model_validate(
        {
            "eventType": "TOOL_BUILD_REQUESTED",
            "runId": "sandbox-failure-test-run",
            "projectId": 1,
            "chatSessionId": 2,
            "toolPlanId": 3,
            "planGroupId": 4,
            "approvedByProjectMemberId": 5,
            "approvedPlan": {
                "rawMarkdown": "## Test",
                "structuredPlanJson": {},
                "planSnapshot": {"blocks": []},
            },
            "requestedAt": datetime.now(timezone.utc).isoformat(),
        }
    )


class ToolBuildSandboxFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_sandbox_failure_is_published_with_classification(self) -> None:
        publisher = FakePublisher()
        processor = ToolBuildProcessor(
            publisher=publisher,
            builder=FailingBuilder(),
            checkpoint_repo_factory=None,
        )

        await processor.process_build(_build_event())

        failed_events = [
            event for _, event in publisher.events if isinstance(event, ToolBuildFailedEvent)
        ]
        self.assertEqual(len(failed_events), 1)
        failed = failed_events[0]
        self.assertEqual(failed.code, "SANDBOX_FAILED")
        for fragment in (
            "errorType=result_missing",
            "exitCode=1",
            "timedOut=False",
            "resourceLimited=False",
        ):
            self.assertIn(fragment, failed.message)


if __name__ == "__main__":
    unittest.main()
