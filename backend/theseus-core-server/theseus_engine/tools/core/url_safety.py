"""외부 URL을 가져오는 도구(web_fetch, deep_research)의 SSRF 방어.

Core 컨테이너는 내부 네트워크(docker-proxy, api, DB, Kafka)와 호스트 터널에 닿을 수 있으므로,
LLM이 고른 URL로 내부 주소를 읽지 못하게 막는다.

- 호스트 이름을 미리 해석해 공인(global) 주소가 아니면 거부한다(loopback, RFC1918, link-local,
  CGNAT, 예약 대역, IPv4-mapped IPv6 포함).
- 점이 없는 단일 라벨 이름(docker-proxy, api, mysql 같은 compose 서비스 이름)과 localhost,
  .internal/.local 같은 내부 접미사는 해석하기 전에 거부한다.
- 리다이렉트는 httpx에 맡기지 않고 한 단계씩 따라가며 매번 다시 검사한다.
- 실제로 연결된 상대 IP도 본문을 읽기 전에 확인해 DNS rebinding으로 검사를 우회하지 못하게 한다.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

_BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "host.docker.internal"})
_BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".localdomain",
    ".internal",
    ".home.arpa",
)


class UnsafeUrlError(ValueError):
    """내부 주소를 가리키는 등 가져오면 안 되는 URL."""


def is_public_ip(value: str) -> bool:
    """공인 인터넷 주소(unicast global)이면 True."""
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


async def _resolve(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def ensure_public_url(url: str) -> None:
    """URL이 공인 주소의 http(s) 리소스가 아니면 UnsafeUrlError를 던진다."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError(f"Invalid URL: {url}") from exc

    if parts.scheme not in ("http", "https"):
        raise UnsafeUrlError("URL must start with http:// or https://")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeUrlError(f"URL has no host: {url}")
    if port is None:
        port = 443 if parts.scheme == "https" else 80

    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        is_ip_literal = False
    else:
        is_ip_literal = True

    if is_ip_literal:
        if not is_public_ip(host):
            raise UnsafeUrlError(f"Blocked non-public address: {host}")
        return

    if (
        "." not in host
        or host in _BLOCKED_HOSTNAMES
        or host.endswith(_BLOCKED_HOST_SUFFIXES)
    ):
        raise UnsafeUrlError(f"Blocked internal host name: {host}")

    try:
        addresses = await _resolve(host, port)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise UnsafeUrlError(f"Could not resolve host: {host}") from exc
    if not addresses:
        raise UnsafeUrlError(f"Could not resolve host: {host}")
    blocked = [address for address in addresses if not is_public_ip(address)]
    if blocked:
        raise UnsafeUrlError(f"Blocked host {host} resolving to non-public address {blocked[0]}")


def ensure_public_peer(response: httpx.Response) -> None:
    """실제로 연결된 서버 IP가 공인 주소가 아니면 UnsafeUrlError를 던진다."""
    stream = response.extensions.get("network_stream")
    if stream is None:
        return
    server_addr = stream.get_extra_info("server_addr")
    if not server_addr:
        return
    peer = str(server_addr[0])
    if not is_public_ip(peer):
        raise UnsafeUrlError(f"Blocked connection to non-public address {peer}")


def create_public_http_client(timeout: float) -> httpx.AsyncClient:
    """SSRF 검사용 클라이언트. 리다이렉트는 fetch_public_url이 직접 따라간다.

    환경 변수 프록시를 쓰면 연결 상대가 프록시가 되어 상대 IP 검사가 무의미해지므로 끈다.
    """
    return httpx.AsyncClient(follow_redirects=False, timeout=timeout, trust_env=False)


async def fetch_public_url(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_redirects: int = 5,
) -> httpx.Response:
    """공인 주소만 거치며 GET한다. 리다이렉트마다 대상 URL과 연결 IP를 다시 검사한다.

    Raises:
        UnsafeUrlError: 내부 주소로 향하는 URL이나 리다이렉트
        httpx.TooManyRedirects: 리다이렉트가 max_redirects를 넘을 때
        httpx.RequestError: 그 밖의 요청 실패
    """
    current = url
    for _ in range(max_redirects + 1):
        await ensure_public_url(current)
        request = client.build_request("GET", current, headers=headers)
        response = await client.send(request, stream=True)
        try:
            ensure_public_peer(response)
            if response.is_redirect and "location" in response.headers:
                current = str(response.url.join(response.headers["location"]))
                continue
            await response.aread()
            return response
        finally:
            await response.aclose()
    raise httpx.TooManyRedirects(f"Exceeded {max_redirects} redirects", request=request)
