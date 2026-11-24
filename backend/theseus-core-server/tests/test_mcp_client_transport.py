"""실제 MCP 서버(HTTP와 stdio)에 연결합니다.

예전에는 _connect_http가 streamablehttp_client에 없는 http_client 인자를 넘겨 연결이 항상 실패했고,
MCP 연결을 다루는 테스트가 없어 아무도 몰랐습니다(#46). 로컬 포트에 FastMCP 서버를 띄워
연결, 헤더 전달, 도구 목록, 도구 호출과 실패·취소 처리를 확인합니다.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
import unittest
from unittest import mock

import uvicorn
from mcp.server.fastmcp import FastMCP

from theseus_engine.mcp.client import McpClientManager, McpServerNotConnectedError
from theseus_engine.mcp.types import McpHttpServerConfig, McpStdioServerConfig

_TOKEN_HEADER = b"x-test-token"
_TOKEN = "test-token"
_HANG_PATH = "/hang"


def _build_app():
    server = FastMCP("theseus-test")

    @server.tool()
    def echo(text: str) -> str:
        """입력을 그대로 돌려줍니다."""
        return f"echo:{text}"

    inner = server.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(_HANG_PATH):
            # 응답하지 않는 서버: 바깥 타임아웃이 연결 시도를 취소하는지 확인합니다.
            # 클라이언트가 연결을 끊으면 끝내서 서버 종료가 이 요청을 기다리지 않게 합니다.
            while (await receive())["type"] != "http.disconnect":
                pass
            return
        # 헤더가 실제로 전달되는지 확인하려고, 토큰이 없는 HTTP 요청은 401로 막습니다.
        if scope["type"] == "http" and dict(scope["headers"]).get(_TOKEN_HEADER) != _TOKEN.encode():
            await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"unauthorized"})
            return
        await inner(scope, receive, send)

    return app


def _unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class McpHttpTransportTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 포트를 고른 뒤 다시 바인딩하면 그 사이에 다른 프로세스가 가져갈 수 있어, 소켓을 직접 넘깁니다.
        cls.sock = socket.socket()
        cls.sock.bind(("127.0.0.1", 0))
        port = cls.sock.getsockname()[1]
        config = uvicorn.Config(_build_app(), log_level="warning", lifespan="on", timeout_graceful_shutdown=2)
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, kwargs={"sockets": [cls.sock]}, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 15
        while not cls.server.started:
            if not cls.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("test MCP server did not start")
            time.sleep(0.05)
        cls.base_url = f"http://127.0.0.1:{port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.thread.join(timeout=10)
        cls.sock.close()

    def setUp(self) -> None:
        # 개발 PC나 사내 러너에 프록시 변수가 있어도 루프백 요청은 직접 가게 합니다.
        patcher = mock.patch.dict(os.environ, {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _connect(self, url: str, headers: dict[str, str]) -> McpClientManager:
        manager = McpClientManager({"remote": McpHttpServerConfig(url=url, headers=headers)})
        self.addAsyncCleanup(manager.close)
        await asyncio.wait_for(manager.connect_all(), timeout=30)
        return manager

    async def test_connects_lists_and_calls_tools_with_headers(self) -> None:
        manager = await self._connect(f"{self.base_url}/mcp", {"X-Test-Token": _TOKEN})

        (status,) = manager.list_statuses()
        self.assertEqual(status.state, "connected", status.detail)
        self.assertEqual(status.transport, "http")
        self.assertTrue(status.auth_configured)
        self.assertEqual([tool.name for tool in manager.list_tools()], ["echo"])

        result = await asyncio.wait_for(manager.call_tool("remote", "echo", {"text": "hi"}), timeout=30)
        self.assertEqual(result, "echo:hi")

    async def test_rejected_request_marks_server_failed(self) -> None:
        manager = await self._connect(f"{self.base_url}/mcp", {})

        (status,) = manager.list_statuses()
        self.assertEqual(status.state, "failed")
        self.assertIn("401", status.detail or "")
        self.assertNotIn("\n", status.detail or "")
        self.assertFalse(manager.list_tools())
        with self.assertRaises(McpServerNotConnectedError):
            await manager.call_tool("remote", "echo", {"text": "hi"})

    async def test_unreachable_server_marks_failed(self) -> None:
        manager = await self._connect(f"http://127.0.0.1:{_unused_port()}/mcp", {})

        (status,) = manager.list_statuses()
        self.assertEqual(status.state, "failed")
        self.assertTrue(status.detail)

    async def test_outside_timeout_is_propagated_and_recorded(self) -> None:
        manager = McpClientManager({"slow": McpHttpServerConfig(url=f"{self.base_url}{_HANG_PATH}")})
        self.addAsyncCleanup(manager.close)

        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(manager.connect_all(), timeout=1)

        (status,) = manager.list_statuses()
        self.assertEqual(status.state, "failed")
        self.assertEqual(status.detail, "connection cancelled or timed out")


_STDIO_SERVER = """
from mcp.server.fastmcp import FastMCP
server = FastMCP("theseus-stdio-test")

@server.tool()
def echo(text: str) -> str:
    return f"stdio:{text}"

server.run("stdio")
"""


class McpStdioTransportTest(unittest.IsolatedAsyncioTestCase):
    """stdio 경로의 회귀 스모크입니다. #46과 무관하게 dev에서도 통과합니다."""

    async def test_connects_and_calls_tool(self) -> None:
        manager = McpClientManager(
            {"local": McpStdioServerConfig(command=sys.executable, args=["-c", _STDIO_SERVER])}
        )
        self.addAsyncCleanup(manager.close)
        await asyncio.wait_for(manager.connect_all(), timeout=60)

        (status,) = manager.list_statuses()
        self.assertEqual(status.state, "connected", status.detail)
        self.assertEqual([tool.name for tool in manager.list_tools()], ["echo"])
        result = await asyncio.wait_for(manager.call_tool("local", "echo", {"text": "hi"}), timeout=30)
        self.assertEqual(result, "stdio:hi")

    async def test_missing_command_marks_failed(self) -> None:
        manager = McpClientManager({"local": McpStdioServerConfig(command="theseus-missing-mcp-server-cmd")})
        self.addAsyncCleanup(manager.close)
        await asyncio.wait_for(manager.connect_all(), timeout=30)

        (status,) = manager.list_statuses()
        self.assertEqual(status.state, "failed")
        self.assertTrue(status.detail)


if __name__ == "__main__":
    unittest.main()
