"""E7 Phase 3b review — execution-time SSRF guard on the replay client. $0.

The nightly replay (and the discovery add-time replay) fetch STORED, LLM-authored
URLs. ``guarded_sync_client`` is the SSRF boundary those replays run through. These
tests prove, with a fixture validator + a recording/Mock inner transport (no real
DNS, no real sockets):

* a direct ``https://169.254.169.254/…`` / ``https://10.0.0.5/…`` fetch (or sitemap
  URL) is rejected BEFORE any socket opens;
* a fetch that 302-redirects to an internal host is blocked and the internal
  request is NEVER issued;
* a cross-host redirect is blocked by the host-pin;
* a legitimate same-host redirect + a normal public fetch still work;
* the request is IP-pinned (connects to the validated IP) with the hostname kept
  for the ``Host`` header + TLS SNI (cert verification), closing the DNS-rebind
  TOCTOU;
* end-to-end through ``run_recipe``, a script pointing ``fetch.url`` at an internal
  address RAISES ``RecipeExecutionError`` and issues no internal request.
"""

from __future__ import annotations

import httpx
import pytest

from api.services.guarded_client import GuardedTransport, guarded_sync_client
from api.services.recipe_runner import RecipeExecutionError, run_recipe
from api.services.url_guard import REASON_PRIVATE_ADDRESS, GuardedUrl, UrlGuardError

_PUBLIC_IP = "93.184.216.34"
_PUBLIC_HOSTS = {"good.com", "evil.com", "other-public.com"}


def _fake_validate(url: str) -> GuardedUrl:
    """Classify hosts without real DNS: the test's public hosts 'resolve' to a
    fixed public IP; everything else is 'private'."""
    parsed = httpx.URL(url)
    host = parsed.host
    if host in _PUBLIC_HOSTS:
        return GuardedUrl(url=str(parsed), host=host, resolved_ips=(_PUBLIC_IP,))
    raise UrlGuardError(REASON_PRIVATE_ADDRESS, f"{host!r} is not public")


class _RecordingTransport(httpx.BaseTransport):
    """Inner transport that records every request it is asked to issue."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"jobs": []})

    def close(self) -> None:  # pragma: no cover - trivial
        pass


def _script(fetch_url: str) -> dict:
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": 1,
        "steps": [
            {"op": "fetch", "method": "GET", "url": fetch_url, "headers": {}},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "title", "url": "url"}},
            {"op": "dedupe_key", "field": "id"},
        ],
        "oracle": {"kind": "self_consistent"},
    }


# --- direct internal targets rejected before any socket (real validator) ------

@pytest.mark.parametrize("url", [
    "https://169.254.169.254/latest/meta-data/",  # cloud metadata
    "https://10.0.0.5/api",                        # RFC1918
    "https://127.0.0.1/x",                          # loopback
    "https://[::1]/x",                              # IPv6 loopback
])
def test_direct_internal_url_rejected_before_any_socket(url: str) -> None:
    inner = _RecordingTransport()
    client = guarded_sync_client(inner_transport=inner)  # real validate_public_url
    with pytest.raises(RecipeExecutionError, match="SSRF guard"):
        client.get(url)
    assert inner.requests == []   # no socket ever opened
    client.close()


def test_sitemap_style_internal_url_rejected_before_any_socket() -> None:
    inner = _RecordingTransport()
    client = guarded_sync_client(inner_transport=inner)
    with pytest.raises(RecipeExecutionError, match="SSRF guard"):
        client.get("https://10.0.0.5/sitemap.xml")
    assert inner.requests == []
    client.close()


# --- redirect to an internal host: blocked, internal request never issued -----

def test_redirect_to_internal_host_is_blocked_and_never_issued() -> None:
    issued: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        issued.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    client = guarded_sync_client(
        validator=_fake_validate, inner_transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RecipeExecutionError, match="SSRF guard"):
        client.get("https://evil.com/api")
    # Only the initial public request was issued; the metadata hop never was.
    assert len(issued) == 1
    client.close()


# --- cross-host redirect blocked by the host-pin ------------------------------

def test_cross_host_redirect_is_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("host") == "good.com":
            return httpx.Response(302, headers={"location": "https://other-public.com/api"})
        return httpx.Response(200, json={"jobs": []})

    client = guarded_sync_client(
        validator=_fake_validate, inner_transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RecipeExecutionError, match="cross-host"):
        client.get("https://good.com/api")
    client.close()


# --- legitimate same-host redirect + normal fetch still work ------------------

def test_same_host_redirect_and_normal_fetch_still_work() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://good.com/final"})
        return httpx.Response(200, json={"jobs": [{"id": "1"}]})

    client = guarded_sync_client(
        validator=_fake_validate, inner_transport=httpx.MockTransport(handler)
    )
    resp = client.get("https://good.com/start")
    assert resp.status_code == 200
    assert resp.json() == {"jobs": [{"id": "1"}]}
    client.close()


# --- IP-pin mechanics: connect to the IP, keep the hostname for Host + SNI -----

def test_request_is_ip_pinned_with_hostname_preserved_for_sni() -> None:
    def validator(url: str) -> GuardedUrl:
        return GuardedUrl(url=url, host="good.com", resolved_ips=("93.184.216.34",))

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url_host"] = request.url.host
        seen["host_header"] = request.headers.get("host")
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, json={"jobs": []})

    client = guarded_sync_client(
        validator=validator, inner_transport=httpx.MockTransport(handler)
    )
    client.get("https://good.com/api")
    # Socket goes to the validated IP; the hostname rides Host + TLS SNI (so the
    # cert is verified against the hostname, not the IP) — DNS-rebind TOCTOU closed.
    assert seen["url_host"] == "93.184.216.34"
    assert seen["host_header"] == "good.com"
    assert seen["sni"] == "good.com"
    client.close()


# --- hop cap ------------------------------------------------------------------

def test_redirect_hop_cap_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Always redirect back to the same host — an infinite same-host loop.
        return httpx.Response(302, headers={"location": "https://good.com/next"})

    client = guarded_sync_client(
        validator=_fake_validate, inner_transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RecipeExecutionError, match="hop"):
        client.get("https://good.com/api")
    client.close()


# --- end-to-end through run_recipe --------------------------------------------

def test_run_recipe_blocks_a_direct_internal_fetch_url() -> None:
    inner = _RecordingTransport()
    client = guarded_sync_client(inner_transport=inner)
    with pytest.raises(RecipeExecutionError):
        run_recipe(_script("https://169.254.169.254/api"), client)
    assert inner.requests == []   # the runner never issued the internal request
    client.close()


def test_run_recipe_blocks_a_redirect_to_internal_via_the_guarded_client() -> None:
    issued: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        issued.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/x"})

    client = guarded_sync_client(
        validator=_fake_validate, inner_transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RecipeExecutionError):
        run_recipe(_script("https://evil.com/api"), client)
    assert len(issued) == 1   # only the public hop; the metadata hop was never issued
    client.close()


def test_guarded_transport_default_inner_is_verified_https() -> None:
    # Defense-in-depth sanity: the real transport verifies TLS.
    t = GuardedTransport()
    assert isinstance(t._inner, httpx.HTTPTransport)
    t.close()


def test_leaf_task_http_replay_uses_the_guarded_client() -> None:
    """The nightly http_json/http_html replay leaf task builds the SSRF-guarded
    client (no plain ``httpx.Client(follow_redirects=True)`` survives).

    Since the Stagehand pivot, the discovery + browser-agent path no longer builds an
    httpx client at all — it drives a bounded Browserbase session in a subprocess and
    guards SSRF via the entry ``url_guard`` (``browser_agent.runner`` +
    ``_stagehand_main``), so there is no discovery httpx factory left to assert here."""
    import api.tasks.fetch_custom_company as leaf

    client = leaf._recipe_http_client()
    assert client.follow_redirects is False
    assert isinstance(client._transport, GuardedTransport)
    client.close()
