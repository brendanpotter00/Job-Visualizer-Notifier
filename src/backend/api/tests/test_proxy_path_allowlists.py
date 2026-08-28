"""Keeps the Vercel proxies' ``?path=`` allowlists honest against the backend.

WHY THIS FILE EXISTS. Five proxies — ``api/users.ts``, ``api/companies.ts``,
``api/feedback.ts``, ``api/features.ts``, ``api/admin.ts`` — spliced an
attacker-controlled ``?path=`` straight into the upstream URL while attaching
``X-Internal-Key`` unconditionally. Node's ``fetch`` parses with WHATWG URL,
which collapses dot segments, so an ANONYMOUS

    GET /api/feedback?path=..%2Finternal%2Fenrichment%2Fpending

resolved to ``/api/internal/enrichment/pending`` — internal-key-only, no JWT,
and MUTATING (it flips rows to ``enrichment_status='claimed'``). The sibling
``POST /results`` writes arbitrary enrichment data onto up to 500 rows a call.
That was live in production.

The fix is a per-proxy allowlist. An allowlist only stays correct if something
compares it to the real route table, which is what this file does — the exact
role ``TestProxyAllowlistInvariant`` (test_scraper_health.py) plays for
``api/jobs-qa.ts``. Two directions, both asserted:

  1. Nothing allowlisted that is not a real backend route under that prefix.
     A typo'd or stale entry is a path the proxy will forward with the internal
     key attached to whatever answers it later.
  2. Nothing on the backend that the proxy silently cannot reach. A route the
     SPA needs but the proxy refuses is a dead feature that no frontend test
     catches, because the frontend tests mock ``fetch``.

Direction 2 is the one that will fail on you: add a backend route under one of
these prefixes and this test stops the build until you either allowlist it or
record in ``NOT_PROXIED`` that it must never be publicly reachable. That is the
intended friction — it is the decision the original bug skipped.

No database: this reads router objects and TypeScript source, nothing else.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from api.routers import (
    admin,
    companies,
    features,
    feedback,
    saved_filters,
    user_companies,
    users,
)

API_DIR = Path(__file__).resolve().parents[4] / "api"

# Backend routers mounted under each proxy's prefix, with the sub-prefix
# ``main.py`` gives them. ``/api/users`` is three routers, which is why that
# proxy's allowlist is the widest of the five.
PROXIES: dict[str, list[tuple[object, str]]] = {
    "users": [(users, ""), (saved_filters, "saved-filters"), (user_companies, "companies")],
    "companies": [(companies, "")],
    "feedback": [(feedback, "")],
    "features": [(features, "")],
    "admin": [(admin, "")],
}

# Backend routes deliberately NOT reachable through the public proxy, each with
# the reason. Empty today: every route under these five prefixes is called by
# the SPA. An internal-key-only route must be added HERE, never to a proxy.
NOT_PROXIED: dict[str, set[str]] = {}


def _proxy_allowlist(name: str) -> list[str]:
    """The ``PROXIED_ROUTES`` literal from ``api/<name>.ts``."""
    src = (API_DIR / f"{name}.ts").read_text()
    match = re.search(r"const PROXIED_ROUTES = \[(.*?)\] as const;", src, re.S)
    assert match, (
        f"PROXIED_ROUTES is missing from api/{name}.ts. If it was replaced by a "
        f"denylist or removed, read this module's docstring first — that shape "
        f"is what shipped the production traversal."
    )
    # Only quoted entries; the trailing `// comment` on each line is ignored.
    return re.findall(r"'([^']*)'", match.group(1))


def _shape(path: str) -> tuple[str, ...]:
    """Reduce a route to comparable segments.

    A dynamic segment collapses to a marker so the proxy's ``:id`` and the
    backend's ``{company_id}`` compare equal, while a ``{param:path}``
    converter collapses to ``*`` — distinct on purpose. ``*`` is the one form
    that spans several segments, so the proxy may only use it where the backend
    actually declared a ``:path`` converter (admin's alias key, which carries
    literal slashes: "EMEA / Remote").
    """
    out = []
    for seg in path.strip("/").split("/"):
        if not seg:
            continue
        if seg == "*" or (seg.startswith("{") and seg.endswith(":path}")):
            out.append("*")
        elif seg.startswith(":") or (seg.startswith("{") and seg.endswith("}")):
            out.append(":")
        else:
            out.append(seg)
    return tuple(out)


def _backend_routes(name: str) -> dict[tuple[str, ...], str]:
    """Every route under the proxy's prefix, keyed by shape."""
    found: dict[tuple[str, ...], str] = {}
    for module, sub_prefix in PROXIES[name]:
        for route in module.router.routes:  # type: ignore[attr-defined]
            raw = f"{sub_prefix}/{route.path.lstrip('/')}".strip("/")
            found[_shape(raw)] = raw
    return found


@pytest.mark.parametrize("name", sorted(PROXIES))
class TestProxyPathAllowlists:
    def test_every_allowlisted_path_is_a_real_backend_route(self, name: str) -> None:
        """Direction 1. A stale or typo'd entry is a public door onto whatever
        occupies that path next."""
        backend = _backend_routes(name)
        for entry in _proxy_allowlist(name):
            assert _shape(entry) in backend, (
                f"api/{name}.ts allowlists {entry!r}, which is not a route on "
                f"the backend router(s) mounted at /api/{name}. Known routes: "
                f"{sorted(backend.values())}"
            )

    def test_every_backend_route_is_reachable_or_explicitly_refused(
        self, name: str
    ) -> None:
        """Direction 2. A route the SPA needs but the proxy refuses is a dead
        feature; a route that must stay private belongs in NOT_PROXIED."""
        allowlisted = {_shape(e) for e in _proxy_allowlist(name)}
        refused = {_shape(p) for p in NOT_PROXIED.get(name, set())}
        missing = {
            raw
            for shape, raw in _backend_routes(name).items()
            if shape not in allowlisted and shape not in refused
        }
        assert not missing, (
            f"these /api/{name} routes exist on the backend but the proxy will "
            f"404 them: {sorted(missing)}. Add each to PROXIED_ROUTES in "
            f"api/{name}.ts, or to NOT_PROXIED in this file with the reason it "
            f"must never be publicly reachable."
        )

    def test_no_allowlist_entry_can_leave_its_prefix(self, name: str) -> None:
        """The allowlist is the last line; an entry containing a dot segment or
        a scheme would defeat it before the canonicalizer ever runs."""
        for entry in _proxy_allowlist(name):
            segments = [s for s in entry.split("/") if s]
            assert ".." not in segments and "." not in segments, (
                f"api/{name}.ts allowlists {entry!r}, which contains a dot "
                f"segment — the canonicalizer would refuse it, so it is dead "
                f"weight at best and a traversal template at worst"
            )
            assert "://" not in entry, f"{entry!r} carries a scheme"
            for hazard in ("\\", "?", "#"):
                assert hazard not in entry, (
                    f"api/{name}.ts allowlists {entry!r}, which contains "
                    f"{hazard!r} — a character that restructures the upstream "
                    f"URL and that the canonicalizer refuses outright"
                )
            assert "internal" not in segments, (
                f"api/{name}.ts allowlists {entry!r}, which names the "
                f"internal-key-only surface"
            )

    def test_wildcards_only_where_the_backend_declared_a_path_converter(
        self, name: str
    ) -> None:
        """``*`` spans multiple segments, so it is the only entry shape that can
        widen the reachable surface by accident. It is legitimate solely where
        the backend route itself is ``{param:path}``."""
        backend = _backend_routes(name)
        for entry in _proxy_allowlist(name):
            shape = _shape(entry)
            if "*" in shape:
                assert shape[-1] == "*", (
                    f"{entry!r}: a wildcard is only meaningful as the final "
                    f"segment"
                )
                assert shape in backend, (
                    f"{entry!r} uses a multi-segment wildcard but no backend "
                    f"route under /api/{name} declares a {{param:path}} "
                    f"converter there"
                )


# Every proxy that injects X-Internal-Key. A superset of ``PROXIES`` above:
# ``jobs``, ``jobs-qa`` and ``locations`` were already allowlisted and are not
# route-table-checked here (their allowlists are hand-picked subsets, not the
# full router), but they must use the same mechanism as everything else.
ALL_KEY_INJECTING_PROXIES = sorted(PROXIES) + ["jobs", "jobs-qa", "locations"]


def test_every_proxy_uses_the_shared_allowlist() -> None:
    """The shape of the bug, pinned directly.

    ``users``/``companies``/``feedback``/``features``/``admin`` each used to
    build the upstream URL from ``pathParts.join('/')`` — the raw, unvalidated
    ``?path=``. ``jobs`` and ``locations`` compared the raw capture against a
    single literal, which could not be traversed but also could not normalize.
    All eight now share one implementation, and this is what notices if one
    drifts back off it.
    """
    for name in ALL_KEY_INJECTING_PROXIES:
        src = (API_DIR / f"{name}.ts").read_text()
        assert "pathParts.join" not in src, (
            f"api/{name}.ts is splicing the raw ?path= into the upstream URL "
            f"again — see this module's docstring"
        )
        assert "resolveProxyPath" in src, (
            f"api/{name}.ts must resolve ?path= through the shared allowlist "
            f"in api/utils/proxyPath.ts, not a private check"
        )
        assert "redirect: 'manual'" in src or 'redirect: "manual"' in src, (
            f"api/{name}.ts must not follow redirects: Node's fetch preserves "
            f"the injected X-Internal-Key across a same-origin 3xx, and "
            f"Starlette's redirect_slashes=True turns a trailing slash into one"
        )
