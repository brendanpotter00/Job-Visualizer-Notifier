"""HTTP client for the pull integration with JVN.

The laptop makes only OUTBOUND HTTPS calls, authenticated with the existing
`X-Internal-Key` middleware on JVN. Five endpoints (all under
/api/internal/enrichment, added by the JVN PR):

  GET  /pending?limit=N          claim a batch of unenriched OPEN jobs
  POST /results                  idempotent upsert of enrichment results
  POST /subcategories            D2's slim bulk subcategory write-back (SCHEMA-14)
  GET  /health                   trivial liveness GET — BF-16's RTT baseline
  GET  /sample?n=&stratify=      stratified raw sample for the eval golden set
  POST /metrics                  per-tick observability push (idempotent on tick_uuid)
  GET  /corrections?since=&limit= human admin corrections (feed for golden-merge)

There is no heartbeat endpoint here: the "laptop is alive" heartbeat is a LOCAL
SQLite write (`store.heartbeat()`) the `cli pull` command makes after a
successful pull — but its AGE does ride along on the /metrics push.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx

from job_enricher.config import settings

logger = logging.getLogger(__name__)


class JVNClient:
    def __init__(
        self,
        base_url: str | None = None,
        internal_key: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.jvn_base_url).rstrip("/")
        self.internal_key = internal_key or settings.internal_api_key
        self.timeout = timeout or settings.http_timeout_seconds

    def _headers(self) -> dict[str, str]:
        if not self.internal_key:
            raise RuntimeError("internal_api_key is not configured; cannot call JVN")
        return {"X-Internal-Key": self.internal_key, "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/internal/enrichment/{path.lstrip('/')}"

    def pull_pending(self, limit: int | None = None, client: httpx.Client | None = None) -> list[dict[str, Any]]:
        """Claim up to `limit` jobs from JVN's /pending and normalize them into
        inbox rows. JVN claims the rows server-side so concurrent polls don't
        hand out the same jobs (the exact server-side status is JVN-internal and
        not part of this contract).

        The `/pending` response is `{"jobs": [...], "enabled": bool}`. When
        `enabled` is false the provider integration is switched OFF — that is
        logged distinctly from an empty queue (E12). Rows missing a usable
        `job_listing_id` (neither `job_id` nor `id`) or with an empty
        `source_id` are skipped with a warning rather than aborting the whole
        batch (E5/E10) — an empty id would be rejected by JVN's `min_length=1`
        and silently dropped anyway."""
        limit = limit or settings.pull_limit
        owns = client is None
        client = client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.get(
                self._url("pending"),
                params={"limit": limit},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        finally:
            if owns:
                client.close()
        if isinstance(data, dict):
            jobs = data.get("jobs", [])
            enabled = data.get("enabled", True)
        else:
            jobs = data
            enabled = True
        if not enabled:
            logger.warning(
                "JVN reports the enrichment provider is DISABLED (enabled=false); "
                "no jobs will be claimed this tick"
            )
        return self._valid_rows(jobs)

    @classmethod
    def _valid_rows(cls, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        skipped = 0
        for j in jobs:
            # Guard non-dict elements FIRST: _to_inbox_row calls j.get(...), so a
            # string/None element would raise AttributeError and abort the whole
            # batch. Skip it like any other malformed row (E17).
            if not isinstance(j, dict):
                skipped += 1
                logger.warning(
                    "pull: skipping non-dict jobs[] element (type=%s)", type(j).__name__
                )
                continue
            row = cls._to_inbox_row(j)
            jid = row.get("job_listing_id")
            src = row.get("source_id")
            if not (jid and str(jid).strip()):
                skipped += 1
                logger.warning(
                    "pull: skipping row with no usable job id (keys=%s)",
                    sorted(j.keys()),
                )
                continue
            if not (src and str(src).strip()):
                skipped += 1
                logger.warning("pull: skipping job_listing_id=%s with empty source_id", jid)
                continue
            rows.append(row)
        if skipped:
            logger.warning("pull: skipped %d malformed row(s) of %d received", skipped, len(jobs))
        return rows

    def post_results(self, results: list[dict[str, Any]], client: httpx.Client | None = None) -> dict[str, Any]:
        """Idempotent upsert. Returns {"written": n, "failed": [...]}."""
        owns = client is None
        client = client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.post(
                self._url("results"),
                content=json.dumps({"results": results}),
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if owns:
                client.close()

    def post_subcategories(
        self, items: list[dict[str, Any]], client: httpx.Client | None = None
    ) -> dict[str, Any]:
        """D2's slim bulk write-back (`SCHEMA-14`).

        ⚠ The endpoint is `extra='forbid'` — it has ONE client and no legacy
        fleet, so an unknown key must 422 loudly rather than be dropped. Send the
        six contract keys and nothing else. Max 500 items; above that the endpoint
        422s. Returns {"written": n, "skipped": [...], "failed": [...],
        "warnings": [...]}."""
        owns = client is None
        client = client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.post(
                self._url("subcategories"),
                content=json.dumps({"items": items}),
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if owns:
                client.close()

    def get_health(self, client: httpx.Client | None = None) -> dict[str, Any]:
        """A trivial GET used as the network-RTT baseline in `BF-16`'s probe.

        Reached through the same `_url` helper as everything else, so it carries
        the same internal-key header."""
        owns = client is None
        client = client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.get(self._url("health"), headers=self._headers())
            resp.raise_for_status()
            return resp.json()
        finally:
            if owns:
                client.close()

    def post_metrics(self, payload: dict[str, Any], client: httpx.Client | None = None) -> dict[str, Any]:
        """Push one tick's metrics to JVN (idempotent on payload['tick_uuid']).
        Uses a short dedicated timeout — metrics must never stall a tick."""
        owns = client is None
        client = client or httpx.Client(timeout=min(self.timeout, 10.0))
        try:
            resp = client.post(
                self._url("metrics"),
                content=json.dumps(payload),
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if owns:
                client.close()

    def get_corrections(
        self,
        since: str | None = None,
        limit: int | None = None,
        client: httpx.Client | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch human admin corrections from JVN.

        RESPONSE SHAPE (the contract this client depends on):

            {"corrections": [{
                 "job_listing_id": str, "source_id": str,
                 "title": str, "company": str,
                 "category": str, "level": str, "tags": list[str],
                 "decision": str, "corrected_at": str,
                 # --- added by ADM-5 (v7) ---
                 "subcategories": list[str] | None,
                 "taxonomy_version": str,
             }], "count": int}

        ⚠ THERE IS NO `description_html` IN THIS FEED, and that is why
        `merge_corrections` does NOT append unmatched corrections as new seed
        rows: an appended row would be classified TITLE-ONLY, which SKILL.md
        answers at confidence <= 0.5 and `cli.TITLE_ONLY_MAX_CONFIDENCE` clamps
        in code. See `merge_corrections`' docstring for all three reasons.

        ⚠ THE `tags` HERE ARE ENRICHER-ORIGIN (JVN's job_tags is 100% written
        by this pipeline), so they are not an independent signal.

        `missing_v7_correction_keys` reports when `subcategories` /
        `taxonomy_version` are absent — the shape ADM-5 must supply. A missing
        key is a SILENT no-op otherwise: the merge would run, report matches,
        and write no subcategory gold at all.
        """
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if limit is not None:
            params["limit"] = limit
        owns = client is None
        client = client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.get(
                self._url("corrections"),
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        finally:
            if owns:
                client.close()
        if isinstance(data, dict):
            corrections = data.get("corrections", [])
        else:
            corrections = data
        return [c for c in corrections if isinstance(c, dict)]

    def sample(self, n: int = 150, stratify: str = "company", client: httpx.Client | None = None) -> list[dict[str, Any]]:
        owns = client is None
        client = client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.get(
                self._url("sample"),
                params={"n": n, "stratify": stratify},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        finally:
            if owns:
                client.close()
        jobs = data.get("jobs", []) if isinstance(data, dict) else data
        return [self._to_inbox_row(j) for j in jobs]

    @staticmethod
    def _to_inbox_row(j: dict[str, Any]) -> dict[str, Any]:
        """Normalize a JVN job payload into the inbox row shape + content_hash.

        Tolerant to a missing id: if neither `job_id` nor `id` is present the
        `job_listing_id` comes back falsy (None) so `pull_pending` can skip the
        row instead of raising `KeyError` and aborting the whole batch (E5)."""
        details = j.get("details")
        details_json = json.dumps(details, sort_keys=True) if details is not None else None
        desc = j.get("description_html") or j.get("description") or ""
        content_hash = hashlib.sha256(
            (j.get("title", "") + "\x1f" + desc).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "job_listing_id": j.get("job_id") or j.get("id"),
            "source_id": j.get("source_id", ""),
            "title": j.get("title", ""),
            "company": j.get("company", ""),
            "raw_location": j.get("location"),
            "description_html": desc,
            "details_json": details_json,
            "content_hash": content_hash,
            # Posting-recency signal (JVN /pending orders first_seen_at DESC);
            # persisted so the local queues stay newest-first. Absent on older
            # JVN builds -> None -> row sorts last, same as a legacy row.
            "first_seen_at": j.get("first_seen_at"),
        }


# --- the /corrections contract (EV-16) --------------------------------------
# ⚠ These two keys arrive with ADM-5. Until they do, `golden-merge` runs green
# and writes NO subcategory gold — a perfect silent no-op. `missing_v7_correction_keys`
# is what a test uses to turn that into a red build.
CORRECTION_V7_KEYS: frozenset[str] = frozenset({"subcategories", "taxonomy_version"})


def missing_v7_correction_keys(correction: dict[str, Any]) -> list[str]:
    """Sorted list of v7 contract keys absent from one correction (empty = ok)."""
    return sorted(k for k in CORRECTION_V7_KEYS if k not in correction)
