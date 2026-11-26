"""서버 세션의 ask_user 처리(#59).

웹 채팅에는 모델의 질문을 사용자에게 보내고 답을 받아 오는 경로가 없습니다. 예전에는 서버가 승인용
permission_prompt(tool_name, reason)를 도구 metadata에 넣었고, AskUserTool이 그것을 인자 하나로 불러
TypeError로 끝났습니다. 이제 서버는 ask_user를 보이지 않게 하고, AskUserTool은 ask_user_prompt만 씁니다.
"""

import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src.builder.engine import EngineBuildContext, _deny_permission_prompt, get_query_engine
from tests.fixtures.tool_rag_fakes import FakeEmbedder, make_retriever
from theseus_engine.core.tool_rag import set_tool_retriever
from theseus_engine.models.modes import AgentMode
from theseus_engine.tools.core.base_tools import ToolExecutionContext
from theseus_engine.tools.core.interactive_tools import AskUserInput, AskUserTool


class _DummyClient:
    model_name = "dummy"


class ServerAskUserVisibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        set_tool_retriever(make_retriever(FakeEmbedder(), none_mode="off"))
        self._client = patch("src.builder.engine.TheseusLLMClient", lambda name: _DummyClient())
        self._client.start()

    def tearDown(self) -> None:
        self._client.stop()
        set_tool_retriever(None)

    def build(self, query: str = "이 설정을 어떻게 바꿀지 나한테 물어보고 진행해줘"):
        return get_query_engine(
            EngineBuildContext(user_level=5, project_tool_permissions={}, mode=AgentMode.AGENT, user_query=query)
        )

    @staticmethod
    def sent(assembly) -> set[str]:
        return {t.name for t in assembly.engine._tool_registry.list_tools()}

    def test_agent_session_hides_ask_user(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("THESEUS_SERVER_EXPOSE_ASK_USER", None)
            assembly = self.build()
        self.assertNotIn("ask_user", assembly.allowed_tools)
        self.assertNotIn("ask_user", self.sent(assembly))
        # tool_search·사후 훅도 보이는 도구 안에서만 넓히므로 다시 들어올 수 없습니다.
        self.assertNotIn("ask_user", assembly.engine._tool_metadata["search_injectable_tool_names"])
        # 다른 필수 도구는 그대로 갑니다.
        self.assertTrue({"read_file", "write_file", "edit_file", "glob", "grep", "bash"} <= self.sent(assembly))

    def test_expose_flag_restores_ask_user(self) -> None:
        with patch.dict(os.environ, {"THESEUS_SERVER_EXPOSE_ASK_USER": "true"}):
            assembly = self.build()
        self.assertIn("ask_user", assembly.allowed_tools)
        self.assertIn("ask_user", self.sent(assembly))

    def test_permission_prompt_is_not_tool_metadata(self) -> None:
        assembly = self.build()
        self.assertNotIn("permission_prompt", assembly.engine._tool_metadata)
        # 민감 도구 승인을 거부하는 경로(QueryEngine 인자)는 그대로입니다.
        self.assertIs(assembly.engine._permission_prompt, _deny_permission_prompt)


class AskUserToolTest(unittest.TestCase):
    @staticmethod
    def run_tool(metadata: dict):
        context = ToolExecutionContext(cwd=Path.cwd(), metadata=metadata)
        return asyncio.run(AskUserTool().execute(AskUserInput(question="어느 브랜치에 배포할까요?"), context))

    def test_uses_ask_user_prompt(self) -> None:
        asked: list[str] = []

        async def ask(prompt: str) -> str:
            asked.append(prompt)
            return " dev "

        result = self.run_tool({"ask_user_prompt": ask})
        self.assertFalse(result.is_error)
        self.assertEqual(result.output, "User's response: dev")
        self.assertEqual(len(asked), 1)
        self.assertIn("어느 브랜치에 배포할까요?", asked[0])

    def test_empty_answer(self) -> None:
        async def ask(prompt: str) -> str:
            return "   "

        result = self.run_tool({"ask_user_prompt": ask})
        self.assertFalse(result.is_error)
        self.assertEqual(result.output, "(User provided an empty response)")

    def test_ignores_permission_prompt(self) -> None:
        calls: list[tuple] = []

        async def permission_prompt(tool_name: str, reason: str) -> bool:
            calls.append((tool_name, reason))
            return True

        result = self.run_tool({"permission_prompt": permission_prompt})
        self.assertEqual(calls, [])
        self.assertTrue(result.is_error)
        self.assertIn("not available", result.output)
        self.assertIn("in your reply", result.output)

    def test_without_prompt(self) -> None:
        result = self.run_tool({"ask_user_prompt": None})
        self.assertTrue(result.is_error)
        self.assertIn("not available", result.output)


if __name__ == "__main__":
    unittest.main()
