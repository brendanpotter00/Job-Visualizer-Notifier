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


# --- the opt-in cross-host mode: ONE check dropped, and only one ---------------
#
# ``allow_cross_host=True`` exists for the discovery LINK PROBE and nothing else.
# Measured 2026-08-30, two correct recipes were thrown away over a plain 301 to the
# same company's own board — ``boards.greenhouse.io`` -> ``job-boards.greenhouse.io``
# (SpaceX) and ``databricks.com`` -> ``www.databricks.com``. The probe reported
# "HTTP 0 — this link is not usable".
#
# The four tests below are the price of that flag: every OTHER guarantee has to still
# hold on the far side of the hop, or the flag is an SSRF hole wearing a bug fix's
# clothes.

def test_a_bare_GuardedTransport_still_refuses_a_cross_host_redirect() -> None:
    """The default is checked on the TRANSPORT, not only through the factory.

    Found by mutation: flipping ``GuardedTransport(allow_cross_host=True)``'s default
    left every test green, because ``guarded_sync_client`` passes the flag explicitly
    and its own default (False) masked it. Anyone building the transport directly —
    a future caller, a test helper — would silently have got the open behaviour.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("host") == "good.com":
            return httpx.Response(302, headers={"location": "https://other-public.com/api"})
        return httpx.Response(200, json={})

    client = httpx.Client(
        transport=GuardedTransport(
            validator=_fake_validate, inner=httpx.MockTransport(handler)
        ),
        follow_redirects=False,
    )
    with pytest.raises(RecipeExecutionError, match="cross-host"):
        client.get("https://good.com/api")
    client.close()


def test_cross_host_redirect_is_followed_when_the_caller_opts_in() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("host") == "good.com":
            return httpx.Response(301, headers={"location": "https://other-public.com/api"})
        return httpx.Response(200, json={"jobs": [{"id": "1"}]})

    client = guarded_sync_client(
        validator=_fake_validate, inner_transport=httpx.MockTransport(handler),
        allow_cross_host=True,
    )
    resp = client.get("https://good.com/api")
    assert resp.status_code == 200 and resp.json() == {"jobs": [{"id": "1"}]}
    client.close()


def test_cross_host_redirect_to_an_INTERNAL_host_is_still_refused() -> None:
    """THE ONE THAT MATTERS. Following cross-host hops must not become following
    ANY hop: the second host is put through the same validator as the first, so a
    board that 301s to the cloud metadata service is refused before its socket opens.
    """
    issued: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        issued.append(str(request.url))
        return httpx.Response(
            302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
        )

    client = guarded_sync_client(
        validator=_fake_validate, inner_transport=httpx.MockTransport(handler),
        allow_cross_host=True,
    )
    with pytest.raises(RecipeExecutionError, match="SSRF guard"):
        client.get("https://good.com/api")
    assert len(issued) == 1, "the metadata hop must never be issued"
    client.close()


def test_a_cross_host_hop_is_ip_pinned_like_every_other_hop() -> None:
    """The IP-pin (and therefore the DNS-rebind TOCTOU closure) is per-hop, so the
    host we were redirected TO gets the same treatment as the one we started on."""
    seen: list[tuple[str | None, str | None, object]] = []

    def validator(url: str) -> GuardedUrl:
        host = httpx.URL(url).host
        ips = {"good.com": "93.184.216.34", "other-public.com": "93.184.216.35"}
        if host not in ips:
            raise UrlGuardError(REASON_PRIVATE_ADDRESS, f"{host!r} is not public")
        return GuardedUrl(url=url, host=host, resolved_ips=(ips[host],))

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("host"),
                     request.extensions.get("sni_hostname")))
        if request.headers.get("host") == "good.com":
            return httpx.Response(301, headers={"location": "https://other-public.com/j"})
        return httpx.Response(200, json={})

    client = guarded_sync_client(
        validator=validator, inner_transport=httpx.MockTransport(handler),
        allow_cross_host=True,
    )
    client.get("https://good.com/j")
    assert seen == [
        ("93.184.216.34", "good.com", "good.com"),
        ("93.184.216.35", "other-public.com", "other-public.com"),
    ]
    client.close()


def test_cross_host_mode_still_honours_the_hop_cap() -> None:
    hosts = ["good.com", "other-public.com"]

    def handler(request: httpx.Request) -> httpx.Response:
        nxt = hosts[len(handler.calls) % 2]      # type: ignore[attr-defined]
        handler.calls.append(nxt)                # type: ignore[attr-defined]
        return httpx.Response(302, headers={"location": f"https://{nxt}/next"})

    handler.calls = []                           # type: ignore[attr-defined]
    client = guarded_sync_client(
        validator=_fake_validate, inner_transport=httpx.MockTransport(handler),
        allow_cross_host=True,
    )
    with pytest.raises(RecipeExecutionError, match="hop"):
        client.get("https://good.com/api")
    client.close()


def test_only_the_discovery_link_probe_opts_into_cross_host() -> None:
    """The flag is opt-in, the default is closed, and exactly ONE caller takes it.

    Checked by reading the source rather than by exercising each caller: the nightly
    replay's host-pin is a property of the whole codebase, not of one code path, and a
    new ``allow_cross_host=True`` anywhere else should fail a test rather than a review.

    Scoped to ``guarded_sync_client`` on purpose — ``url_guard.guarded_get`` has carried
    its own, older ``allow_cross_host`` since the add-time resolver, and that is a
    different surface with a different answer (a pasted careers URL is EXPECTED to
    redirect to another host).
    """
    import inspect
    import pathlib
    import re

    from api.services import guarded_client as module

    assert inspect.signature(module.guarded_sync_client).parameters[
        "allow_cross_host"
    ].default is False
    assert inspect.signature(module.GuardedTransport.__init__).parameters[
        "allow_cross_host"
    ].default is False

    backend = pathlib.Path(module.__file__).resolve().parents[2]
    call = re.compile(r"guarded_sync_client\([^)]*allow_cross_host\s*=\s*True")
    opted_in = {
        str(path.relative_to(backend))
        for path in (backend / "api").rglob("*.py")
        if "/tests/" not in str(path) and call.search(path.read_text())
    }
    assert opted_in == {"api/services/capture/discover.py"}, (
        "the SSRF host-pin is what stops a stored board silently relaying a nightly "
        f"scrape to another host. Only the discovery link probe may drop it; got "
        f"{sorted(opted_in)}"
    )


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

    Since the capture pivot, the discovery path no longer builds an
    httpx client of its own for the CAPTURE half — the browser child does the fetching
    and ``capture.network_capture`` guards SSRF via the entry ``url_guard``. (Its
    ACCEPTANCE half does use ``guarded_sync_client``, through the very same
    ``run_recipe`` path the nightly replay uses — which is the point of the acceptance
    gate, and is covered by the tests for that client here.)"""
    import api.tasks.fetch_custom_company as leaf

    client = leaf._recipe_http_client()
    assert client.follow_redirects is False
    assert isinstance(client._transport, GuardedTransport)
    client.close()
