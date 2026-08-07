"""Unit tests for the SSRF egress guard."""

from __future__ import annotations

import httpx
import pytest

from api.services import url_guard
from api.services.url_guard import BlockedURLError, safe_get, validate_public_url


class TestValidatePublicUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://8.8.8.8/",
            "http://1.1.1.1/careers",
            "https://93.184.216.34/",  # literal public IPv4
        ],
    )
    def test_public_literal_ip_allowed(self, url):
        # No exception == allowed.
        validate_public_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "https://127.0.0.1/",
            "http://10.0.0.5/",
            "https://192.168.1.1/",
            "http://172.16.0.1/",
            "https://[::1]/",
            "http://[::ffff:10.0.0.1]/",  # v4-mapped internal
            "http://0.0.0.0/",
        ],
    )
    def test_private_and_metadata_blocked(self, url):
        with pytest.raises(BlockedURLError):
            validate_public_url(url)

    @pytest.mark.parametrize(
        "url",
        ["ftp://8.8.8.8/", "file:///etc/passwd", "gopher://8.8.8.8/", "", "   "],
    )
    def test_bad_scheme_or_empty_blocked(self, url):
        with pytest.raises(BlockedURLError):
            validate_public_url(url)

    def test_no_host_blocked(self):
        with pytest.raises(BlockedURLError):
            validate_public_url("https:///path-only")

    def test_unresolvable_host_fails_closed(self, monkeypatch):
        import socket

        def _boom(*a, **k):
            raise socket.gaierror("nope")

        monkeypatch.setattr(socket, "getaddrinfo", _boom)
        with pytest.raises(BlockedURLError):
            validate_public_url("https://does-not-resolve.invalid/")

    def test_hostname_resolving_private_blocked(self, monkeypatch):
        import socket

        def _fake(host, *a, **k):
            return [(socket.AF_INET, None, None, "", ("10.1.2.3", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", _fake)
        with pytest.raises(BlockedURLError):
            validate_public_url("https://sneaky.example.com/")


pytestmark_async = pytest.mark.asyncio


class TestSafeGet:
    @pytest.mark.asyncio
    async def test_redirect_to_private_host_blocked(self, monkeypatch):
        # First hop is a public literal IP that 302s to a private host.
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "8.8.8.8":
                return httpx.Response(302, headers={"location": "http://10.0.0.1/x"})
            return httpx.Response(200, text="should not reach")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(BlockedURLError):
                await safe_get(client, "https://8.8.8.8/start")

    @pytest.mark.asyncio
    async def test_oversized_body_blocked(self, monkeypatch):
        monkeypatch.setattr(url_guard, "MAX_RESPONSE_BYTES", 10)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="x" * 100)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(BlockedURLError):
                await safe_get(client, "https://8.8.8.8/big")

    @pytest.mark.asyncio
    async def test_happy_path_returns_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>ok</html>")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            resp = await safe_get(client, "https://8.8.8.8/page")
        assert resp.status_code == 200
        assert "ok" in resp.text
