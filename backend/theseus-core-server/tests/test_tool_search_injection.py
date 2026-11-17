import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel, Field

from theseus_engine.models.modes import AgentMode, PlanPhase
from theseus_engine.tools.core.base_tools import (
    BaseTool,
    ToolExecutionContext,
    ToolRegistry,
    ToolResult,
)
from theseus_engine.tools.core.tool_search_tool import (
    ToolSearchInput,
    ToolSearchTool,
)


class _DummyInput(BaseModel):
    value: str = Field(default="")


class _DummyTool(BaseTool):
    input_model = _DummyInput
    permission_level = 1
    is_destructive = False

    def __init__(self, name: str, description: str = "dummy tool") -> None:
        self.name = name
        self.description = description

    async def execute(
        self,
        arguments: _DummyInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        del arguments, context
        return ToolResult(output="ok")


class ToolSearchInjectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_tool_is_not_injected_in_agent_mode(self) -> None:
        create_tool = _DummyTool(
            "create_tool",
            "Create a new Python tool.",
        )
        full_registry = ToolRegistry()
        full_registry.register(create_tool)
        active_registry = ToolRegistry()

        output = await self._run_search(
            matched_tools=[create_tool],
            full_registry=full_registry,
            active_registry=active_registry,
            agent_mode=AgentMode.AGENT.value,
            plan_phase=None,
            injectable_tool_names=("tool_search",),
        )

        self.assertIsNone(active_registry.get("create_tool"))
        self.assertIn("Not injectable", output)
        self.assertIn("requires approved PLAN Executing phase", output)

    async def test_create_tool_is_injected_in_plan_executing(self) -> None:
        create_tool = _DummyTool(
            "create_tool",
            "Create a new Python tool.",
        )
        full_registry = ToolRegistry()
        full_registry.register(create_tool)
        active_registry = ToolRegistry()

        output = await self._run_search(
            matched_tools=[create_tool],
            full_registry=full_registry,
            active_registry=active_registry,
            agent_mode=AgentMode.PLAN.value,
            plan_phase=PlanPhase.EXECUTING.value,
            injectable_tool_names=("create_tool", "tool_search"),
        )

        self.assertIs(active_registry.get("create_tool"), create_tool)
        self.assertIn("Newly added", output)

    async def test_mode_hidden_tool_is_not_injected(self) -> None:
        hidden_tool = _DummyTool(
            "dangerous_tool",
            "A mode-restricted tool.",
        )
        full_registry = ToolRegistry()
        full_registry.register(hidden_tool)
        active_registry = ToolRegistry()

        output = await self._run_search(
            matched_tools=[hidden_tool],
            full_registry=full_registry,
            active_registry=active_registry,
            agent_mode=AgentMode.AGENT.value,
            plan_phase=None,
            injectable_tool_names=("tool_search",),
        )

        self.assertIsNone(active_registry.get("dangerous_tool"))
        self.assertIn("Not injectable", output)
        self.assertIn("mode, plan phase, or RBAC policy", output)

    async def _run_search(
        self,
        *,
        matched_tools: list[BaseTool],
        full_registry: ToolRegistry,
        active_registry: ToolRegistry,
        agent_mode: str,
        plan_phase: str | None,
        injectable_tool_names: tuple[str, ...],
    ) -> str:
        tool = ToolSearchTool()
        context = ToolExecutionContext(
            cwd=Path.cwd(),
            metadata={
                "tool_search_registry": full_registry,
                "active_registry": active_registry,
                "agent_mode": agent_mode,
                "plan_phase": plan_phase,
                "search_injectable_tool_names": injectable_tool_names,
                "project_id": "test-project",
            },
        )
        # 검색기가 후보 밖 도구를 돌려주는 상황(계약 위반)을 흉내 내 주입 단계의 방어를 확인합니다.
        with patch(
            "theseus_engine.tools.core.tool_search_tool._semantic_search",
            new=AsyncMock(return_value=matched_tools),
        ):
            result = await tool.execute(
                ToolSearchInput(query="create a new custom tool"),
                context,
            )

        self.assertFalse(result.is_error)
        return str(result.output)


class ToolSearchCandidateFilterTest(unittest.IsolatedAsyncioTestCase):
    """실제 검색 경로(가짜 임베더): 후보(search_injectable_tool_names) 밖 도구는 찾지도 주입하지도 않습니다."""

    async def asyncSetUp(self) -> None:
        from tests.fixtures.tool_rag_fakes import make_retriever
        from theseus_engine.core.tool_rag import set_tool_retriever

        set_tool_retriever(make_retriever())

    async def asyncTearDown(self) -> None:
        from theseus_engine.core.tool_rag import set_tool_retriever

        set_tool_retriever(None)

    async def _search(self, query: str, injectable: tuple[str, ...], *, break_semantic: bool = False):
        full_registry = ToolRegistry()
        for name, desc in (
            ("bash", "Run a shell command in the terminal."),
            ("web_search", "Search the web for information."),
            ("web_fetch", "Fetch a web page by URL."),
        ):
            full_registry.register(_DummyTool(name, desc))
        active_registry = ToolRegistry()
        metadata = {
            "tool_registry": full_registry,
            "active_registry": active_registry,
            "agent_mode": AgentMode.ASK.value,
            "search_injectable_tool_names": injectable,
        }
        ctx = ToolExecutionContext(cwd=Path.cwd(), metadata=metadata)
        if break_semantic:
            with patch(
                "theseus_engine.tools.core.tool_search_tool._semantic_search",
                new=AsyncMock(side_effect=RuntimeError("no model")),
            ):
                result = await ToolSearchTool().execute(ToolSearchInput(query=query), ctx)
        else:
            result = await ToolSearchTool().execute(ToolSearchInput(query=query), ctx)
        return str(result.output), {t.name for t in active_registry.list_tools()}

    async def test_semantic_search_respects_candidates(self) -> None:
        output, injected = await self._search("run a shell command", ("web_search", "web_fetch"))
        self.assertNotIn("bash", output)
        self.assertTrue(injected <= {"web_search", "web_fetch"})

    async def test_lexical_fallback_respects_candidates(self) -> None:
        output, injected = await self._search("shell command web", ("web_search",), break_semantic=True)
        self.assertIn("lexical_fallback", output)
        self.assertNotIn("bash", output)
        self.assertEqual(injected, {"web_search"})


if __name__ == "__main__":
    unittest.main()
