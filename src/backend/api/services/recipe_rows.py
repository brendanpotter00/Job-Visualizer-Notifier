"""Map deterministic replay-runner rows → ``JobListing`` (E7 Phase 3b).

The replay runner (:mod:`api.services.recipe_runner`) emits plain ``dict`` rows
shaped by a script's ``fields`` map (``{id, title, url, location?, posted_at?,
department?, company?, …}``). This module turns those rows into ``JobListing``
objects, mirroring the ATS clients' ``transform_to_job_listings`` contract so the
custom-company leaf task's ``_remap_for_custom`` re-scoping path is reused
unchanged.

Deliberately **agent-free** — imported by the replay leaf task
(``tasks/fetch_custom_company``, both the http and the browser_fetch branch), by the
``browser_fetch`` runner, and by the capture discovery orchestrator
(``services/capture/discover``). It imports only ``scripts.shared`` + the stdlib, so the
import-guard AST walk of the leaf task's ``tasks/`` closure stays clean.
"""

from __future__ import annotations

from typing import Any

from scripts.shared.constants import custom
from scripts.shared.models import JobListing
from scripts.shared.utils import get_iso_timestamp

# Row keys the runner writes that map to first-class JobListing columns; anything
# else the script extracted (department, company_name, category, …) is preserved
# under ``details`` so the enrichment/read paths can still see it.
_PROMOTED_KEYS = frozenset({"id", "title", "url", "location", "posted_at", "posted_on"})


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def recipe_rows_to_job_listings(company_id: str, rows: list[dict]) -> list[JobListing]:
    """Map runner rows to ``JobListing`` scoped to ``custom:<company_id>``.

    The runner guarantees each row has a non-empty, stringified ``id`` and a
    non-empty ``title`` (``map_records`` drops the rest) and — because the schema
    requires an ``url`` field — a ``url``. ``location`` / ``posted_at`` are
    optional. ``posted_on`` is taken verbatim from the row (already ISO-normalized
    by a ``parse_date`` step, or ``None``); the leaf task's ``_validated_posted_on``
    applies the ±window sanity check on the nightly path, so nothing is synthesized
    here.
    """
    now = get_iso_timestamp()
    source_id = custom(company_id)
    out: list[JobListing] = []
    for row in rows:
        job_id = str(row["id"])
        title = str(row["title"])
        url = _as_optional_str(row.get("url")) or ""
        location = _as_optional_str(row.get("location"))
        posted_on = _as_optional_str(row.get("posted_at") or row.get("posted_on"))
        details = {k: v for k, v in row.items() if k not in _PROMOTED_KEYS}
        out.append(
            JobListing(
                id=job_id,
                title=title,
                company=company_id,
                location=location,
                url=url,
                source_id=source_id,
                details=details,
                posted_on=posted_on,
                created_at=now,
                first_seen_at=now,
                last_seen_at=now,
                consecutive_misses=0,
                details_scraped=False,
                status="OPEN",
                has_matched=False,
                ai_metadata={},
                closed_on=None,
            )
        )
    return out
