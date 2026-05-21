"""Per-source verifier registry for the close-detection path.

The close-detection algorithm in ``scripts/shared/incremental.py`` and the
inline close logic in ``src/backend/api/tasks/fetch_*_company.py`` use
"missing from this scrape's output for ``MISSED_RUN_THRESHOLD`` consecutive
runs" as a proxy for "this job no longer exists upstream." That proxy is
noisy on any source whose scrape returns a slightly different *set* each
tick (Eightfold offset pagination, Apple HTML pagination, etc.) — see
``docs/incidents/2026-05-21-apple-eightfold-false-close/`` for the prod
incident this module exists to address.

This registry maps ``source_id`` to a per-source ``verify_url_alive``
callable that probes the job's public URL **before** the close decision
fires. The close path takes:

  - ``"alive"``  → reset ``consecutive_misses=0`` and bump ``last_seen_at``;
                   DO NOT close (scrape was lying)
  - ``"dead"``   → proceed with ``mark_jobs_closed`` (URL agrees the job
                   is gone)
  - ``"unknown"``→ skip the close decision for this tick (fail-safe —
                   re-evaluate next run)

Sources that never registered a verifier resolve to a no-op fallback that
always returns ``"unknown"``. Today the close path can choose to treat
``"unknown"`` as "close anyway" (legacy behavior, preserved for
Microsoft, where the public URL can't be probed without auth) or to skip
(fail-safe). See ``close_verifier.verify_close_candidates`` for the
policy.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Literal

logger = logging.getLogger(__name__)

VerifierResult = Literal["alive", "dead", "unknown"]
"""Three-valued URL liveness signal.

- ``"alive"``: URL returns a recognizable role page (per-source signal —
  for Eightfold the posting-api JSON has a non-empty ``title`` +
  ``descriptionText``; for Apple the detail API returns a populated
  ``res`` object; for Lever the apply page renders normally; etc.).
- ``"dead"``: URL returns 404/410, redirects to a "closed" sentinel, or
  the per-source JSON shape explicitly marks the role as closed.
- ``"unknown"``: ambiguous — network error, timeout, auth wall (Microsoft),
  or no verifier registered. The close path must NOT use this to make a
  CLOSED decision unilaterally.
"""

Verifier = Callable[[str, str, str], Awaitable[VerifierResult]]
"""Per-source verifier signature: ``(url, source_id, job_id) -> result``.

The ``source_id`` and ``job_id`` are passed in addition to the URL because
some verifiers need to construct the canonical detail URL from the id
rather than trusting the ``url`` column (which may be stale or
locale-specific).

Contract for implementers:

- MUST resolve transient errors (network, timeout, parse-fail, HTTP error,
  cancellation other than asyncio.CancelledError) to ``"unknown"`` —
  do NOT raise them up to the caller. The caller's discriminated catch in
  ``close_verifier.verify_close_candidates`` is httpx-specific
  (``httpx.HTTPError, asyncio.TimeoutError, OSError, ValueError``); a
  verifier built on another HTTP client (aiohttp, urllib) that raises a
  client-specific exception WOULD be reclassified as a programming bug
  and re-raised to Sentry. Verifiers own their own transient-error
  swallowing.
- MAY propagate ``asyncio.CancelledError`` (and SHOULD — cancellation
  must never be suppressed).
- MAY raise programming bugs (TypeError, AttributeError, etc.) — the
  caller deliberately does NOT catch these, so they reach Sentry and
  get fixed.
"""


async def _unknown_verifier(url: str, source_id: str, job_id: str) -> VerifierResult:
    """Fallback verifier used when a source hasn't registered one.

    Returns ``"unknown"`` so the close path falls back to whatever
    legacy-behavior policy ``close_verifier.verify_close_candidates``
    encodes for unregistered sources. Microsoft uses this today (no
    public URL we can probe without auth).
    """
    return "unknown"


_VERIFIERS: dict[str, Verifier] = {}


def register_verifier(source_id: str, verifier: Verifier) -> None:
    """Register a ``verify_url_alive`` callable for ``source_id``.

    Called once at import time by each ATS service module. Idempotent —
    re-registering the same ``source_id`` overwrites the previous entry
    (useful in tests).
    """
    if not source_id:
        raise ValueError("register_verifier requires a non-empty source_id")
    if not callable(verifier):
        raise TypeError(
            f"register_verifier({source_id!r}): verifier must be callable, "
            f"got {type(verifier).__name__}"
        )
    _VERIFIERS[source_id] = verifier
    logger.debug("Registered URL verifier for source_id=%s", source_id)


def unregister_verifier(source_id: str) -> None:
    """Remove ``source_id`` from the registry; subsequent ``get_verifier``
    calls return the no-op fallback.

    Production callers: use this when a verifier's preconditions can't be
    met for the current run (e.g., Apple's verifier needs a Playwright
    page; if the page can't be created, the verifier would return
    ``"unknown"`` for every call and — combined with ``unknown_policy="skip"``
    — silently disable close-detection entirely. Unregistering lets the
    close path fall through to legacy close-on-threshold instead.

    Idempotent — no-op if ``source_id`` is not registered.
    """
    if not source_id:
        # Mirror register_verifier's guard. An empty source_id can't
        # validly be in the registry, but accepting it silently would
        # mask typos (e.g., a renamed SourceId constant collapsed to "").
        raise ValueError(
            "unregister_verifier requires a non-empty source_id"
        )
    if _VERIFIERS.pop(source_id, None) is not None:
        logger.debug("Unregistered URL verifier for source_id=%s", source_id)


def get_verifier(source_id: str) -> Verifier:
    """Return the registered verifier for ``source_id``, or the no-op fallback.

    The no-op fallback always returns ``"unknown"``. Source-specific
    verifiers should be added by importing the relevant service module —
    registration happens at module import time.
    """
    return _VERIFIERS.get(source_id, _unknown_verifier)


def clear_verifiers_for_testing() -> None:
    """Test-only: wipe the registry. Do not call from production code.

    Tests that register a stub verifier on a real ``source_id`` must clear
    afterwards (or use the autouse fixture pattern) or they'll leak into
    sibling tests via the module-global ``_VERIFIERS`` dict.
    """
    _VERIFIERS.clear()
