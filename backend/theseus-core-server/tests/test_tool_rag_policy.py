"""Tool RAG 가시성/RBAC 보안 테스트.

v1에서는 서버 사후 훅이 full_registry 전체에서 도구를 골라 active_registry에 주입했습니다. 그래서 ASK 모드나
낮은 user_level에서도 bash·write_file·edit_file 같은 도구가 다음 턴 스키마에 들어갔습니다(가시성/RBAC 우회).
v2는 서버 조립·tool_search·훅 모두 "보이는 도구" 안에서만 고르고 주입합니다.
"""

import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixtures.tool_rag_fakes import FakeEmbedder, make_retriever
from src.builder.engine import EngineBuildContext, get_query_engine
from src.remote_workspace.schemas import RemoteWorkspaceConnectionConfig
from theseus_engine.config import get_tool_rag_settings
from theseus_engine.core.tool_rag import ESSENTIAL_TOOL_NAMES, set_tool_retriever
from theseus_engine.core.tool_rag.assembly import inject_visible_tool
from theseus_engine.models.modes import AgentMode
from theseus_engine.tools.core.base_tools import ToolExecutionContext, ToolRegistry
from theseus_engine.tools.core.tool_search_tool import ToolSearchInput, ToolSearchTool
from theseus_engine.wrappers.hooks.theseus_hook_executor import HookEvent

FORBIDDEN_LOW_LEVEL = {"bash", "write_file", "edit_file", "remote_run_command", "remote_write_file", "remote_edit_file"}
ASK_FORBIDDEN = FORBIDDEN_LOW_LEVEL | {"task_create", "agent", "todo_write", "memory_write", "skill_save"}

# 훅 재검색 질의를 쓰기·실행 도구 쪽으로 끌어당기는 출력들
HOOK_PAYLOADS = [
    ("grep", {"pattern": "TODO"}, "src/app.py:3: TODO fix error\nTraceback (most recent call last): failed"),
    ("read_file", {"path": "a.py"}, "def main():\n    raise Exception('error')  # run tests then edit file"),
    ("web_fetch", {"url": "x"}, "permission denied when executing command; timeout retry; write file failed"),
    ("glob", {"pattern": "*.sh"}, "build.sh deploy.sh run.sh missing not found"),
]


class _DummyClient:
    model_name = "dummy"


def _remote_config(
    allow_write: bool, host: str = "example.internal", username: str = "bench", base_path: str = "/srv/app"
) -> RemoteWorkspaceConnectionConfig:
    return RemoteWorkspaceConnectionConfig.model_validate(
        {
            "remoteWorkspaceId": 1,
            "projectId": 10,
            "host": host,
            "port": 22,
            "username": username,
            "password": "unused",
            "basePath": base_path,
            "allowWriteExecution": allow_write,
            "status": "ACTIVE",
        }
    )


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.embedder = FakeEmbedder()
        self.retriever = make_retriever(self.embedder, none_mode="off")
        set_tool_retriever(self.retriever)
        self._client = patch("src.builder.engine.TheseusLLMClient", lambda name: _DummyClient())
        self._client.start()

    def tearDown(self) -> None:
        self._client.stop()
        set_tool_retriever(None)

    def build(self, *, mode=AgentMode.AGENT, level=5, query="웹에서 최신 뉴스 검색해줘", remote=None, history=None):
        return get_query_engine(
            EngineBuildContext(
                user_level=level,
                project_tool_permissions={},
                mode=mode,
                user_query=query,
                remote_workspace=remote,
                history_messages=history,
            )
        )

    @staticmethod
    def sent(assembly) -> set[str]:
        return {t.name for t in assembly.engine._tool_registry.list_tools()}

    def fire_hooks(self, assembly) -> None:
        hook = assembly.engine._hook_executor
        for tool_name, tool_input, output in HOOK_PAYLOADS * 3:
            asyncio.run(
                hook.execute(
                    HookEvent.POST_TOOL_USE,
                    {"tool_name": tool_name, "tool_input": tool_input, "tool_output": output},
                )
            )

    def run_tool_search(self, assembly, query: str) -> str:
        context = ToolExecutionContext(cwd=Path.cwd(), metadata=assembly.engine._tool_metadata)
        result = asyncio.run(ToolSearchTool().execute(ToolSearchInput(query=query, top_k=10), context))
        return str(result.output)


class ServerAssemblyTest(_Base):
    def test_sent_tools_are_a_bounded_subset_of_allowed(self) -> None:
        assembly = self.build()
        self.assertEqual(assembly.tool_selection_mode, "retrieved")
        sent = self.sent(assembly)
        self.assertEqual(sent, set(assembly.sent_tools))
        self.assertTrue(sent <= set(assembly.allowed_tools))
        cap = len(ESSENTIAL_TOOL_NAMES) + get_tool_rag_settings().max_candidates + 1
        self.assertLessEqual(len(sent), cap)
        self.assertLess(len(sent), len(assembly.allowed_tools))
        self.assertTrue(ESSENTIAL_TOOL_NAMES <= sent)
        # tool_search·훅은 보이는 도구 전체 안에서만 넓힐 수 있습니다.
        self.assertEqual(
            set(assembly.engine._tool_metadata["search_injectable_tool_names"]), set(assembly.allowed_tools)
        )

    def test_tool_search_is_always_sent_with_a_subset(self) -> None:
        from theseus_engine.core.tool_rag.retriever import TOOL_SEARCH_REMINDER

        for mode, query in ((AgentMode.AGENT, "웹에서 최신 뉴스 검색해줘"), (AgentMode.ASK, "이 저장소 구조 설명해줘")):
            with self.subTest(mode=mode):
                assembly = self.build(mode=mode, query=query)
                self.assertEqual(assembly.tool_selection_mode, "retrieved")
                sent = self.sent(assembly)
                self.assertLess(len(sent), len(assembly.allowed_tools))
                self.assertIn("tool_search", assembly.allowed_tools)
                self.assertIn("tool_search", sent)
                self.assertIn(TOOL_SEARCH_REMINDER, assembly.engine._system_prompt)

    def test_history_tools_are_kept(self) -> None:
        history = [{"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "skill_list", "input": {}}]}]
        self.assertIn("skill_list", self.sent(self.build(history=history)))

    def test_retrieval_failure_falls_back_to_visible_not_full(self) -> None:
        class _Broken(FakeEmbedder):
            def encode(self, texts):
                raise RuntimeError("onnx exploded")

        set_tool_retriever(make_retriever(_Broken()))
        assembly = self.build(level=1)
        self.assertEqual(assembly.tool_selection_mode, "all_visible")
        self.assertEqual(self.sent(assembly), set(assembly.allowed_tools))
        self.assertFalse(self.sent(assembly) & FORBIDDEN_LOW_LEVEL)

    def test_not_warm_sends_visible_and_starts_background_warmup(self) -> None:
        from tests.fixtures.tool_rag_fakes import fake_settings
        from theseus_engine.core.tool_rag.retriever import ToolRetriever

        cold = ToolRetriever(settings=fake_settings())  # 임베더 미주입 → is_ready()는 실제 로드 여부
        set_tool_retriever(cold)
        with patch.object(cold, "is_ready", return_value=False), patch(
            "theseus_engine.core.tool_rag.assembly.start_background_warmup"
        ) as warm:
            assembly = self.build()
        warm.assert_called_once()
        self.assertEqual(assembly.tool_selection_mode, "all_visible")
        self.assertEqual(set(assembly.sent_tools), set(assembly.allowed_tools))

    def test_disabled_by_env(self) -> None:
        with patch.dict("os.environ", {"THESEUS_SERVER_TOOL_RAG": "false"}):
            assembly = self.build()
        self.assertEqual(assembly.tool_selection_mode, "all_visible")


class InjectionPolicyTest(_Base):
    def test_level1_agent_never_gets_write_or_exec_tools(self) -> None:
        for remote in (None, _remote_config(allow_write=True)):
            with self.subTest(remote=remote is not None):
                assembly = self.build(level=1, query="테스트 돌리고 실패하면 코드 고쳐줘", remote=remote)
                allowed = set(assembly.allowed_tools)
                self.assertFalse(allowed & FORBIDDEN_LOW_LEVEL)
                self.fire_hooks(assembly)
                for q in ("run a shell command", "bash로 테스트 실행", "write a new file", "remote command execute"):
                    self.run_tool_search(assembly, q)
                sent = self.sent(assembly)
                self.assertTrue(sent <= allowed, sent - allowed)
                self.assertFalse(sent & FORBIDDEN_LOW_LEVEL)

    def test_ask_mode_schema_never_grows_beyond_ask_tools(self) -> None:
        assembly = self.build(mode=AgentMode.ASK, query="이 저장소 구조 설명해줘")
        allowed = set(assembly.allowed_tools)
        self.assertFalse(allowed & ASK_FORBIDDEN)
        before = self.sent(assembly)
        self.fire_hooks(assembly)
        after_hooks = self.sent(assembly)
        self.assertTrue(before <= after_hooks <= allowed)
        cap = get_tool_rag_settings().hook_max_inject
        self.assertLessEqual(len(after_hooks - before), cap)
        out = self.run_tool_search(assembly, "execute bash command and write file")
        sent = self.sent(assembly)
        self.assertTrue(sent <= allowed, sent - allowed)
        self.assertFalse(sent & ASK_FORBIDDEN)
        self.assertNotIn("**bash**", out)
        self.assertNotIn("**write_file**", out)

    def test_hook_without_policy_injects_nothing(self) -> None:
        from theseus_engine.wrappers.hooks.theseus_hook_executor import TheseusHookExecutor

        full = ToolRegistry()
        from theseus_engine.tools.core import ALL_CORE_TOOLS

        for cls in ALL_CORE_TOOLS:
            full.register(cls())
        active = ToolRegistry()
        active.register(full.get("read_file"))
        hook = TheseusHookExecutor(active_registry=active, full_registry=full, injectable_names=None)
        asyncio.run(hook.execute(HookEvent.POST_TOOL_USE, {"tool_name": "grep", "tool_input": {}, "tool_output": "error x" * 5}))
        self.assertEqual([t.name for t in active.list_tools()], ["read_file"])

    def test_inject_visible_tool_refuses_hidden(self) -> None:
        from theseus_engine.tools.core import ALL_CORE_TOOLS

        tools = {cls().name: cls() for cls in ALL_CORE_TOOLS}
        active = ToolRegistry()
        prov: dict[str, str] = {}
        self.assertFalse(inject_visible_tool(active, tools["bash"], ("read_file",), provenance=prov))
        self.assertFalse(inject_visible_tool(active, tools["bash"], None))
        self.assertTrue(inject_visible_tool(active, tools["read_file"], ("read_file",), provenance=prov))
        self.assertFalse(inject_visible_tool(active, tools["read_file"], ("read_file",)))  # 이미 있음
        self.assertEqual(prov, {"read_file": "tool_search"})


class InstanceIsolationTest(_Base):
    """캐시된 인덱스가 다른 요청의 도구 인스턴스를 돌려주지 않는지(세션 간 Remote Workspace 설정 혼용 방지).

    remote_* 도구는 설명·스키마가 같고 접속 정보(self.config)만 다르므로 레지스트리 fingerprint가 같습니다.
    """

    QUERY = "원격 서버 로그 파일 읽어줘 remote read file tail log grep"

    def _remote_sent(self, assembly) -> dict[str, object]:
        return {t.name: t for t in assembly.engine._tool_registry.list_tools() if t.name.startswith("remote_")}

    def test_server_turns_get_their_own_remote_config(self) -> None:
        workspaces = [
            ("tenant-a.internal", "u1", "/srv/a"),
            ("tenant-b.internal", "u2", "/srv/b"),
            ("tenant-a.internal", "u1", "/srv/a"),
        ]
        for host, user, base in workspaces:
            with self.subTest(host=host):
                assembly = self.build(
                    query=self.QUERY,
                    remote=_remote_config(allow_write=True, host=host, username=user, base_path=base),
                )
                self.assertEqual(assembly.tool_selection_mode, "retrieved")
                remote = self._remote_sent(assembly)
                self.assertTrue(remote, "remote_* 도구가 하나도 선택되지 않았습니다")
                full = assembly.engine._tool_metadata["tool_registry"]
                for name, tool in remote.items():
                    self.assertIs(tool, full.get(name), name)
                    self.assertEqual(tool.config.host, host, name)
                    self.assertEqual(tool.config.username, user, name)
                # 같은 인덱스를 공유해야 합니다(재인덱싱이 아니라 인스턴스 해석으로 해결).
        self.assertEqual(len(self.retriever._indexes), 1)

    def test_retrieve_sync_returns_callers_instances(self) -> None:
        from src.remote_workspace.read_primitives import build_remote_read_analysis_tools
        from theseus_engine.tools.core import ALL_CORE_TOOLS

        def registry_for(host: str) -> ToolRegistry:
            registry = ToolRegistry()
            for cls in ALL_CORE_TOOLS:
                registry.register(cls())
            for tool in build_remote_read_analysis_tools(_remote_config(allow_write=False, host=host)):
                registry.register(tool)
            return registry

        for host in ("tenant-a.internal", "tenant-b.internal"):
            registry = registry_for(host)
            result = self.retriever.retrieve_sync(self.QUERY, registry)
            self.assertTrue(result.tools)
            for tool in result.tools:
                self.assertIs(tool, registry.get(tool.name))

    def test_hook_injects_current_request_instance(self) -> None:
        for host in ("tenant-a.internal", "tenant-b.internal"):
            with self.subTest(host=host):
                assembly = self.build(query="웹에서 최신 뉴스 검색해줘", remote=_remote_config(allow_write=False, host=host))
                before = set(self._remote_sent(assembly))
                hook = assembly.engine._hook_executor
                allowed_remote = {n for n in assembly.allowed_tools if n.startswith("remote_")} - before
                self.assertTrue(allowed_remote)
                hook._delegate.set_injectable_names(allowed_remote)  # 주입이 remote_* 도구로만 가도록 좁힘
                asyncio.run(
                    hook.execute(
                        HookEvent.POST_TOOL_USE,
                        {
                            "tool_name": "web_search",
                            "tool_input": {"query": "x"},
                            "tool_output": "remote server log file tail read grep remote_read_file remote_tail_log",
                        },
                    )
                )
                full = assembly.engine._tool_metadata["tool_registry"]
                injected = {n: t for n, t in self._remote_sent(assembly).items() if n not in before}
                self.assertTrue(injected, "훅이 remote_* 도구를 주입하지 않았습니다")
                for name, tool in injected.items():
                    self.assertIs(tool, full.get(name), name)
                    self.assertEqual(tool.config.host, host, name)


class StreamAssemblyOffLoopTest(unittest.TestCase):
    """서버 SSE 경로가 엔진 조립(질의 인코딩·인덱스 구축)을 이벤트 루프 밖에서 하는지."""

    def test_get_query_engine_runs_in_worker_thread(self) -> None:
        import threading

        from src.auth.schemas import SessionContext
        from src.builder.engine import EngineInitializationError
        from src.routes import stream

        seen: dict[str, object] = {}

        def fake_get_query_engine(context):
            seen["thread"] = threading.current_thread()
            raise EngineInitializationError("stop here")

        async def drive() -> list[str]:
            seen["loop_thread"] = threading.current_thread()
            context = EngineBuildContext(user_level=5, project_tool_permissions={}, user_query="hi")
            session = SessionContext(user_id=1, project_id=1, permission_level=5, token="t")
            return [event async for event in stream.stream_agent_response(session, 1, "hi", context, db=None)]

        with patch.object(stream, "get_query_engine", fake_get_query_engine):
            events = asyncio.run(drive())
        self.assertIsNot(seen["thread"], seen["loop_thread"])
        self.assertTrue(any("ENGINE_INIT_FAILED" in e for e in events))


if __name__ == "__main__":
    unittest.main()
