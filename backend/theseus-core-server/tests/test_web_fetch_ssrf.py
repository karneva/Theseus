"""web_fetch / deep_research의 SSRF 방어(url_safety) 테스트."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from theseus_engine.tools.core import url_safety
from theseus_engine.tools.core.base_tools import ToolExecutionContext
from theseus_engine.tools.core.url_safety import (
    UnsafeUrlError,
    ensure_public_url,
    fetch_public_url,
    is_public_ip,
)
from theseus_engine.tools.core.web_fetch_tool import WebFetchInput, WebFetchTool

PUBLIC_IP = "93.184.215.14"


class _FakeStream:
    def __init__(self, server_addr: tuple[str, int]) -> None:
        self._server_addr = server_addr

    def get_extra_info(self, name: str):
        return self._server_addr if name == "server_addr" else None


def _fake_dns(mapping: dict[str, list[str]]):
    async def resolve(host: str, port: int) -> list[str]:
        del port
        return mapping[host]

    return patch.object(url_safety, "_resolve", side_effect=resolve)


class IsPublicIpTest(unittest.TestCase):
    def test_blocks_internal_ranges(self) -> None:
        for address in (
            "127.0.0.1",
            "10.0.0.5",
            "172.17.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "100.64.0.1",
            "0.0.0.0",
            "::1",
            "fd00::1",
            "fe80::1",
            "::ffff:172.17.0.1",
            "224.0.0.1",
        ):
            with self.subTest(address=address):
                self.assertFalse(is_public_ip(address))

    def test_allows_public_addresses(self) -> None:
        self.assertTrue(is_public_ip(PUBLIC_IP))
        self.assertTrue(is_public_ip("2606:4700:4700::1111"))


class EnsurePublicUrlTest(unittest.TestCase):
    def test_blocks_service_names_and_internal_hosts_without_resolving(self) -> None:
        with _fake_dns({}) as resolver:
            for url in (
                "http://docker-proxy:2375/containers/json",
                "http://api:8080/api/internal/auth/verify",
                "http://localhost:8086/health",
                "http://host.docker.internal:11434/api/tags",
                "http://metadata.google.internal/computeMetadata/v1/",
                "http://169.254.169.254/latest/meta-data/",
                "http://[::1]/",
                "file:///etc/passwd",
            ):
                with self.subTest(url=url):
                    with self.assertRaises(UnsafeUrlError):
                        asyncio.run(ensure_public_url(url))
            resolver.assert_not_called()

    def test_blocks_public_name_resolving_to_private_address(self) -> None:
        with _fake_dns({"rebind.example.com": [PUBLIC_IP, "172.18.0.4"]}):
            with self.assertRaises(UnsafeUrlError):
                asyncio.run(ensure_public_url("https://rebind.example.com/"))

    def test_allows_public_name(self) -> None:
        with _fake_dns({"example.com": [PUBLIC_IP]}):
            asyncio.run(ensure_public_url("https://example.com/page"))


class FetchPublicUrlTest(unittest.TestCase):
    def test_rejects_redirect_to_internal_service(self) -> None:
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            return httpx.Response(
                302, headers={"location": "http://docker-proxy:2375/containers/theseus-api-1/json"}
            )

        async def run() -> None:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await fetch_public_url(client, "https://example.com/start")

        with _fake_dns({"example.com": [PUBLIC_IP]}):
            with self.assertRaises(UnsafeUrlError):
                asyncio.run(run())
        self.assertEqual(requested, ["https://example.com/start"])

    def test_follows_public_redirects(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/start":
                return httpx.Response(301, headers={"location": "/final"})
            return httpx.Response(200, text="done")

        async def run() -> httpx.Response:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await fetch_public_url(client, "https://example.com/start")

        with _fake_dns({"example.com": [PUBLIC_IP]}):
            response = asyncio.run(run())
        self.assertEqual(response.text, "done")
        self.assertEqual(str(response.url), "https://example.com/final")

    def test_rejects_connection_that_landed_on_private_peer(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(
                200,
                text="secret",
                extensions={"network_stream": _FakeStream(("172.18.0.4", 443))},
            )

        async def run() -> None:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await fetch_public_url(client, "https://example.com/")

        with _fake_dns({"example.com": [PUBLIC_IP]}):
            with self.assertRaises(UnsafeUrlError):
                asyncio.run(run())

    def test_limits_redirect_count(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(302, headers={"location": "/again"})

        async def run() -> None:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await fetch_public_url(client, "https://example.com/", max_redirects=2)

        with _fake_dns({"example.com": [PUBLIC_IP]}):
            with self.assertRaises(httpx.TooManyRedirects):
                asyncio.run(run())


class WebFetchToolSsrfTest(unittest.TestCase):
    def test_web_fetch_refuses_docker_proxy(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError(f"internal request must not be sent: {request.url}")

        def client_factory(timeout: float) -> httpx.AsyncClient:
            del timeout
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

        with patch(
            "theseus_engine.tools.core.web_fetch_tool.create_public_http_client",
            side_effect=client_factory,
        ):
            result = asyncio.run(
                WebFetchTool().execute(
                    WebFetchInput(url="http://docker-proxy:2375/containers/theseus-api-1/json"),
                    ToolExecutionContext(cwd=Path.cwd()),
                )
            )

        self.assertTrue(result.is_error)
        self.assertIn("URL not allowed", result.output)


if __name__ == "__main__":
    unittest.main()
