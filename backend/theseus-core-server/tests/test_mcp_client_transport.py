"""실제 MCP 서버(HTTP와 stdio)에 연결합니다.

예전에는 _connect_http가 streamablehttp_client에 없는 http_client 인자를 넘겨 연결이 항상 실패했고,
MCP 연결을 다루는 테스트가 없어 아무도 몰랐습니다(#46). 이 테스트는 로컬 포트에 FastMCP 서버를 띄워
연결, 헤더 전달, 도구 목록, 도구 호출을 확인합니다.
"""

from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
import unittest

import uvicorn
from mcp.server.fastmcp import FastMCP

from theseus_engine.mcp.client import McpClientManager, McpServerNotConnectedError
from theseus_engine.mcp.types import McpHttpServerConfig, McpStdioServerConfig

_TOKEN_HEADER = b"x-test-token"
_TOKEN = "test-token"


def _build_app():
    server = FastMCP("theseus-test")

    @server.tool()
    def echo(text: str) -> str:
        """입력을 그대로 돌려줍니다."""
        return f"echo:{text}"

    inner = server.streamable_http_app()

    async def require_token(scope, receive, send):
        # 헤더가 실제로 전달되는지 확인하려고, 토큰이 없는 HTTP 요청은 401로 막습니다.
        if scope["type"] == "http" and dict(scope["headers"]).get(_TOKEN_HEADER) != _TOKEN.encode():
            await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"unauthorized"})
            return
        await inner(scope, receive, send)

    return require_token


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class McpHttpTransportTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.port = _free_port()
        config = uvicorn.Config(_build_app(), host="127.0.0.1", port=cls.port, log_level="warning", lifespan="on")
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 15
        while not cls.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("test MCP server did not start")
            time.sleep(0.05)
        cls.url = f"http://127.0.0.1:{cls.port}/mcp"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.thread.join(timeout=10)

    async def _connect(self, headers: dict[str, str]) -> McpClientManager:
        manager = McpClientManager({"remote": McpHttpServerConfig(url=self.url, headers=headers)})
        await asyncio.wait_for(manager.connect_all(), timeout=30)
        self.addAsyncCleanup(manager.close)
        return manager

    async def test_connects_lists_and_calls_tools_with_headers(self) -> None:
        manager = await self._connect({"X-Test-Token": _TOKEN})

        (status,) = manager.list_statuses()
        self.assertEqual(status.state, "connected", status.detail)
        self.assertEqual(status.transport, "http")
        self.assertTrue(status.auth_configured)
        self.assertEqual([tool.name for tool in manager.list_tools()], ["echo"])

        result = await asyncio.wait_for(manager.call_tool("remote", "echo", {"text": "hi"}), timeout=30)
        self.assertEqual(result, "echo:hi")

    async def test_rejected_request_marks_server_failed(self) -> None:
        manager = await self._connect({})

        (status,) = manager.list_statuses()
        self.assertEqual(status.state, "failed")
        self.assertIn("401", status.detail or "")
        self.assertFalse(manager.list_tools())
        with self.assertRaises(McpServerNotConnectedError):
            await manager.call_tool("remote", "echo", {"text": "hi"})

    async def test_unreachable_server_marks_failed(self) -> None:
        manager = McpClientManager({"down": McpHttpServerConfig(url=f"http://127.0.0.1:{_free_port()}/mcp")})
        await asyncio.wait_for(manager.connect_all(), timeout=30)
        self.addAsyncCleanup(manager.close)

        (status,) = manager.list_statuses()
        self.assertEqual(status.state, "failed")
        self.assertTrue(status.detail)



_STDIO_SERVER = """
from mcp.server.fastmcp import FastMCP
server = FastMCP("theseus-stdio-test")

@server.tool()
def echo(text: str) -> str:
    return f"stdio:{text}"

server.run("stdio")
"""


class McpStdioTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_connects_and_calls_tool(self) -> None:
        manager = McpClientManager(
            {"local": McpStdioServerConfig(command=sys.executable, args=["-c", _STDIO_SERVER])}
        )
        await asyncio.wait_for(manager.connect_all(), timeout=60)
        self.addAsyncCleanup(manager.close)

        (status,) = manager.list_statuses()
        self.assertEqual(status.state, "connected", status.detail)
        self.assertEqual([tool.name for tool in manager.list_tools()], ["echo"])
        result = await asyncio.wait_for(manager.call_tool("local", "echo", {"text": "hi"}), timeout=30)
        self.assertEqual(result, "stdio:hi")

class McpStdioFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_command_marks_failed(self) -> None:
        manager = McpClientManager({"local": McpStdioServerConfig(command="theseus-missing-mcp-server-cmd")})
        await asyncio.wait_for(manager.connect_all(), timeout=30)
        self.addAsyncCleanup(manager.close)

        (status,) = manager.list_statuses()
        self.assertEqual(status.state, "failed")
        self.assertTrue(status.detail)


if __name__ == "__main__":
    unittest.main()
