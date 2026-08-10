"""Execution-time SSRF boundary for the deterministic replay path (E7 Phase 3b).

``recipe_runner`` replays STORED, LLM-authored URLs (the entrypoint ``fetch``,
every pagination page, the ``facet_values`` probe, the ``sitemap`` oracle GET).
Those URLs are attacker-influenceable — a user adds a real public careers page
(passes the add-time guard), discovery authors ``fetch.url=https://evil.com/api``,
and the nightly worker would GET it. Without a guard, ``evil.com`` can 302 to
``http://169.254.169.254/latest/meta-data/…`` (cloud metadata) or an internal
host, ``httpx(follow_redirects=True)`` follows it, and the response is served back
to the attacker under ``custom:<id>``.

This module builds the **sync** ``httpx.Client`` the replay runs through, so every
request is guarded *at the transport layer* — ``recipe_runner`` needs no change and
never imports this module (its agent-free import-guard closure is unaffected):

* ``follow_redirects=False`` on the client; the transport follows redirects
  **manually and re-validates every hop** with ``url_guard.validate_public_url``
  (https-only; rejects IP literals, RFC1918/loopback/link-local ``169.254/16``
  incl. metadata/ULA/``0.0.0.0``; resolves DNS and rejects a private answer)
  BEFORE a socket is opened;
* **host-pin** within a request — a redirect to a different host is refused, so a
  vanity board cannot silently relay a scrape to another host;
* **IP-pin** — it connects to the DNS-validated IP while preserving the hostname
  for TLS SNI + certificate verification, closing the DNS-rebind TOCTOU that
  ``url_guard`` documents as an accepted v1 gap;
* TLS ``verify=True`` throughout.

``url_guard``'s own import closure pulls only ATS-host constants (no agent/browser
imports), so nothing forbidden reaches the replay worker.
"""

from __future__ import annotations

from typing import Callable

import httpx

from .recipe_runner import USER_AGENT, RecipeExecutionError
from .url_guard import GuardedUrl, UrlGuardError, validate_public_url

# 301/302/303/307/308. We re-issue the same method on every hop (recipes use GET,
# and the one POST target — Meta's pinned GraphQL doc_id — does not redirect).
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_HOPS = 5
_DEFAULT_TIMEOUT_S = 30.0

Validator = Callable[[str], GuardedUrl]


class GuardedTransport(httpx.BaseTransport):
    """A sync transport that validates + host-pins + IP-pins every request.

    ``validator`` is injectable so tests exercise the redirect / host-pin / reject
    logic against a fixture classifier + a ``MockTransport`` inner, with zero real
    DNS or sockets. In production it is ``url_guard.validate_public_url`` (real DNS)
    over ``httpx.HTTPTransport(verify=True)``.
    """

    def __init__(
        self,
        *,
        validator: Validator = validate_public_url,
        inner: httpx.BaseTransport | None = None,
        max_hops: int = _MAX_HOPS,
    ) -> None:
        self._validate = validator
        self._inner = inner if inner is not None else httpx.HTTPTransport(verify=True)
        self._max_hops = max_hops

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        content = request.read()  # buffer the body so it can be re-sent on a redirect
        base_extensions = {
            k: v for k, v in request.extensions.items() if k != "sni_hostname"
        }
        # Drop the caller's Host header; we set it per hop after IP-pinning so it
        # names the hostname (not the pinned IP).
        base_headers = [
            (k, v) for k, v in request.headers.raw if k.lower() != b"host"
        ]

        current = str(request.url)
        origin_host: str | None = None

        for hop in range(self._max_hops):
            try:
                guarded = self._validate(current)
            except UrlGuardError as exc:
                # Fail closed as a RecipeExecutionError so run_recipe honours its
                # "RAISES, never returns []" contract and NO internal socket opens.
                raise RecipeExecutionError(
                    f"replay blocked a request to {current!r} "
                    f"(SSRF guard: {exc.reason}): {exc}"
                ) from exc

            host = httpx.URL(guarded.url).host
            if origin_host is None:
                origin_host = host
            elif host != origin_host:
                raise RecipeExecutionError(
                    f"replay blocked a cross-host redirect {origin_host!r} -> {host!r} "
                    f"(SSRF host-pin) — a scrape must stay on the discovered board host"
                )

            response = self._inner.handle_request(
                self._pin_request(
                    method, guarded, base_headers, content, base_extensions, host
                )
            )

            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                if location:
                    response.read()
                    response.close()
                    if hop == self._max_hops - 1:
                        raise RecipeExecutionError(
                            f"replay exceeded the {self._max_hops}-hop redirect limit"
                        )
                    current = str(httpx.URL(guarded.url).join(location))
                    continue

            return response

        # Unreachable: the loop returns or raises on the final hop.
        raise RecipeExecutionError(  # pragma: no cover
            f"replay exceeded the {self._max_hops}-hop redirect limit"
        )

    @staticmethod
    def _pin_request(
        method: str,
        guarded: GuardedUrl,
        base_headers: list[tuple[bytes, bytes]],
        content: bytes,
        base_extensions: dict[str, object],
        host: str,
    ) -> httpx.Request:
        """Build the actual outbound request: connect to the validated IP, but keep
        the hostname for the ``Host`` header AND for TLS SNI + cert verification."""
        pinned_ip = guarded.resolved_ips[0]  # all resolved IPs already passed the public check
        url = httpx.URL(guarded.url).copy_with(host=pinned_ip)
        request = httpx.Request(
            method,
            url,
            headers=httpx.Headers(base_headers),
            content=content,
            extensions={**base_extensions, "sni_hostname": host},
        )
        request.headers["Host"] = host
        return request

    def close(self) -> None:
        self._inner.close()


def guarded_sync_client(
    *,
    validator: Validator = validate_public_url,
    inner_transport: httpx.BaseTransport | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> httpx.Client:
    """The SSRF-guarded sync client both the replay leaf task and discovery use."""
    return httpx.Client(
        transport=GuardedTransport(validator=validator, inner=inner_transport),
        timeout=timeout,
        follow_redirects=False,   # the transport follows + re-validates hops itself
        headers={"User-Agent": USER_AGENT},
    )
