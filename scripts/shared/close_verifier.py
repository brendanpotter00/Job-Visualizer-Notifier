"""URL-verification gate between ``consecutive_misses >= threshold`` and CLOSED.

This module is the load-bearing fix for the 2026-05-21 Apple + Eightfold
false-close incident. Before this gate existed, the close path was:

    1. Compute ``missing_ids = active_in_db - seen_in_scrape``
    2. Increment ``consecutive_misses`` for missing_ids
    3. ``mark_jobs_closed`` for any row at threshold

That sequence converts "missing from scrape" directly into CLOSED — which
is wrong for any source whose scrape returns a slightly different *set*
each tick (Eightfold offset pagination, Apple HTML pagination). 10 jobs
were confirmed false-closed by Playwright probe; ``jobs_seen`` was normal
on the runs that closed them, so the existing 10% ``SAFETY_GUARD_RATIO``
did not fire.

The gate inserts URL re-verification between step (2) and step (3):

  - alive   → call ``update_last_seen`` (resets ``consecutive_misses=0``
              and bumps ``last_seen_at``); job stays OPEN.
  - dead    → call ``mark_jobs_closed``.
  - unknown → no DB write; ``consecutive_misses`` stays at threshold so
              the next tick re-evaluates. If the verifier keeps returning
              "unknown" forever the row stays in this limbo, which is the
              correct fail-safe stance — false-OPEN is cheaper than
              false-CLOSED, and an alert on persistent-unknown is the
              right longer-term remediation.

Microsoft has no public URL we can probe (auth wall) and registers no
verifier; its ``"unknown"`` resolves to the legacy close-on-threshold
behavior via ``process_missing_ids(unknown_policy_for_unverified="close")``
(the default).
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Iterable, Literal

import httpx

from . import database as db
from .source_registry import VerifierResult, _unknown_verifier, get_verifier

logger = logging.getLogger(__name__)

UnknownPolicy = Literal["skip", "close"]
"""Policy for ``"unknown"`` verifier results.

- ``"skip"`` (recommended): treat as inconclusive; do not close this tick.
  ``consecutive_misses`` stays at threshold; the row is re-evaluated next
  tick. Use for sources where a verifier IS registered — an "unknown" then
  is a genuine ambiguity (network blip, parse failure) worth deferring.
- ``"close"``: treat "unknown" as "close anyway" — legacy behavior.
  Use ONLY for sources without a registered verifier (Microsoft today),
  where the close-on-threshold rule is the only signal we have.
"""


async def verify_close_candidates(
    conn,
    source_id: str,
    candidate_ids: list[str],
    timestamp: str,
    unknown_policy: UnknownPolicy = "skip",
) -> tuple[list[str], list[str], list[str]]:
    """Gate ``mark_jobs_closed`` on per-job URL verification.

    For each candidate, look up its URL in ``job_listings`` and call the
    registered verifier for ``source_id``. Apply the DB write that
    matches the verdict (update_last_seen / mark_jobs_closed / nothing).
    Returns the three partitions so callers can log + record metrics
    without re-querying.

    Parameters
    ----------
    conn
        Open psycopg2 connection.
    source_id
        Source namespace (``SourceId.EIGHTFOLD`` etc.). All ``candidate_ids``
        must belong to this source.
    candidate_ids
        Job ids that exceeded ``MISSED_RUN_THRESHOLD``. Caller already ran
        ``increment_consecutive_misses`` for them.
    timestamp
        ISO-8601 timestamp for ``mark_jobs_closed`` / ``update_last_seen``
        writes.
    unknown_policy
        See ``UnknownPolicy`` docstring above. Default ``"skip"`` is the
        fail-safe stance for sources with a registered verifier.

    Returns
    -------
    tuple[list[str], list[str], list[str]]
        ``(closed_ids, kept_alive_ids, skipped_ids)``. The three lists
        partition ``candidate_ids`` exactly.
    """
    if not candidate_ids:
        return [], [], []

    verifier = get_verifier(source_id)

    closed_ids: list[str] = []
    kept_alive_ids: list[str] = []
    skipped_ids: list[str] = []

    counts: Counter[VerifierResult] = Counter()

    # DB ops are synchronous psycopg2 calls; offload them to a thread so the
    # async event loop isn't blocked while the verifier's HTTP requests run.
    # Matches the pattern used in src/backend/api/tasks/fetch_*_company.py.
    for job_id in candidate_ids:
        row = await asyncio.to_thread(db.get_job_by_id, conn, source_id, job_id)
        if row is None:
            logger.warning(
                "verify_close_candidates: source_id=%s job_id=%s not found in "
                "DB during verify (race with another writer?). Skipping.",
                source_id, job_id,
            )
            skipped_ids.append(job_id)
            counts["unknown"] += 1
            continue

        url = row.get("url")
        if not url:
            logger.warning(
                "verify_close_candidates: source_id=%s job_id=%s has empty "
                "url. Skipping URL verify; applying unknown_policy=%s.",
                source_id, job_id, unknown_policy,
            )
            result: VerifierResult = "unknown"
        else:
            try:
                result = await verifier(url, source_id, job_id)
            except (httpx.HTTPError, asyncio.TimeoutError, OSError, ValueError):
                # Transient verifier failure (network blip, timeout,
                # OS-level socket error, expected ValueError from the
                # verifier's own input sanity-checks). Degrade to
                # ``"unknown"`` so ``unknown_policy`` decides. WARN, not
                # ERROR — these are expected in steady-state operation.
                logger.warning(
                    "verify_close_candidates: transient verifier failure for "
                    "source_id=%s job_id=%s url=%s — treating as unknown",
                    source_id, job_id, url,
                    exc_info=True,
                )
                result = "unknown"
                # Programming bugs (TypeError, AttributeError, NameError,
                # ImportError, etc.) are NOT caught — they propagate up to
                # Procrastinate's retry/error handler, surface in Sentry,
                # and fail loudly so the bug gets fixed instead of silently
                # masquerading as "ambiguous network conditions."

        counts[result] += 1

        if result == "alive":
            # Scrape was lying — reset misses + last_seen, keep OPEN.
            await asyncio.to_thread(
                db.update_last_seen, conn, source_id, [job_id], timestamp,
            )
            kept_alive_ids.append(job_id)
        elif result == "dead":
            await asyncio.to_thread(
                db.mark_jobs_closed, conn, source_id, [job_id], timestamp,
            )
            closed_ids.append(job_id)
        else:
            # "unknown"
            if unknown_policy == "close":
                await asyncio.to_thread(
                    db.mark_jobs_closed, conn, source_id, [job_id], timestamp,
                )
                closed_ids.append(job_id)
            else:
                # Fail-safe: leave consecutive_misses at threshold, row stays
                # OPEN. Next tick re-evaluates. If the row reappears in a
                # scrape, the upsert resets misses=0 (see _UPSERT_ON_CONFLICT
                # in database.py). If not, this branch fires again next tick.
                skipped_ids.append(job_id)

    logger.info(
        "verify_close_candidates source_id=%s candidates=%d → "
        "closed=%d kept_alive=%d skipped=%d (verifier verdicts: %s)",
        source_id, len(candidate_ids),
        len(closed_ids), len(kept_alive_ids), len(skipped_ids),
        dict(counts),
    )

    return closed_ids, kept_alive_ids, skipped_ids


async def process_missing_ids(
    conn,
    source_id: str,
    missing_ids: list[str],
    timestamp: str,
    threshold: int,
    unknown_policy_for_unverified: UnknownPolicy = "close",
) -> int:
    """Encapsulate the full close path: increment → threshold-check → verify → close.

    Each backend ATS task (``src/backend/api/tasks/fetch_*_company.py``)
    used to inline these four steps; they now share this helper so the
    URL-verification gate is added uniformly and the close logic stays
    consistent across sources.

    Behavior:
      1. ``increment_consecutive_misses`` for every id in ``missing_ids``.
      2. Look up the ids whose ``consecutive_misses >= threshold``.
      3. For each such candidate, dispatch to ``verify_close_candidates``,
         which runs the registered per-source verifier.
      4. Mark CLOSED only the ids the verifier confirmed dead (or that
         resolve to ``"unknown"`` under
         ``unknown_policy_for_unverified="close"``).

    The ``unknown_policy`` argument selects between fail-safe and legacy
    behavior for sources WITHOUT a registered verifier (Microsoft today,
    and the four API-based ATSes until per-source verifiers ship):

    - ``"close"`` (default) — preserves observable close-on-threshold
      behavior for unverified sources. The control flow still routes
      through this helper (so the verifier hook IS exercised), but the
      no-op fallback's ``"unknown"`` collapses back to a close.
    - ``"skip"`` — fail-safe; never close without a verifier. Reserve
      for environments where false-CLOSED is unacceptable and
      false-OPEN is fine.

    Sources WITH a registered verifier always get ``unknown_policy="skip"``,
    overriding ``unknown_policy_for_unverified`` — if you went through the
    trouble of writing a verifier, ambiguity means "ask again next tick."
    """
    if not missing_ids:
        return 0

    await asyncio.to_thread(
        db.increment_consecutive_misses, conn, source_id, list(missing_ids)
    )
    to_close = await asyncio.to_thread(
        db.get_jobs_exceeding_miss_threshold,
        conn,
        source_id,
        list(missing_ids),
        threshold,
    )
    if not to_close:
        return 0

    has_verifier = get_verifier(source_id) is not _unknown_verifier
    unknown_policy: UnknownPolicy = "skip" if has_verifier else unknown_policy_for_unverified

    closed_ids, _alive_ids, _skipped_ids = await verify_close_candidates(
        conn,
        source_id,
        list(to_close),
        timestamp,
        unknown_policy=unknown_policy,
    )
    return len(closed_ids)


__all__ = [
    "verify_close_candidates",
    "process_missing_ids",
    "UnknownPolicy",
]
