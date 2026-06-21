"""Pure Eightfold AI Job Board API client + transformer.

Three concerns, all queue-agnostic:

1. ``_is_allowed_eightfold_host(host)``: SSRF allowlist enforcement. Ported
   verbatim from ``api/eightfold.ts``. Restricts upstream hosts to
   ``*.eightfold.ai`` plus a small vanity-host set (today: only Netflix's
   ``explore.jobs.netflix.net``). Once Unit 7 deletes the Vercel proxy, this
   Python check becomes the only line of defense against an SSRF if a
   future seed migration's ``tenant_host`` is wrong.

2. ``fetch_jobs(tenant_host, domain, http)``: sequential paginated GET loop
   against Eightfold's public ``/api/apply/v2/jobs`` endpoint. Eightfold
   caps each page at 10 rows server-side (empirically verified 2026-04-18),
   so a Netflix-sized tenant requires ~60-100 round-trips. The loop breaks
   on the first of: ``fetchedSoFar >= total`` reported by the server, empty
   page, partial page (< 10 rows), or the ``MAX_PAGES`` safety cap. If we
   hit the cap we log an ERROR and **return the partial result** — the
   alternative (raising) would zero out the scrape and trip the safety
   guard in ``fetch_eightfold_company``, marking every existing job as
   "missing this run" which is the wrong correctness call when we *did*
   fetch hundreds of jobs.

3. ``transform_to_job_listings(company_id, raw_jobs)``: maps each raw
   Eightfold position dict to a :class:`scripts.shared.models.JobListing`
   row. Field semantics preserved from the deleted frontend
   ``eightfoldTransformer.ts``; see that file's git history for context.

The id stored on ``JobListing`` is ``str(position.id or position.ats_job_id
or position.display_job_id)``. If all three are falsy we drop the row
(mirroring the frontend's ``validPositions`` filter). Eightfold rows use
``source_id = 'eightfold_api'``, so cross-source id collisions are
prevented by the composite ``(source_id, id)`` PK on ``job_listings``.

Output shape note: the ``details`` JSONB column is populated with keys
that the frontend ``backendScraperTransformer.ts`` reads
(``experience_level``, ``is_remote_eligible``). Eightfold doesn't always
expose ``experience_level``, so we pass through whatever's there
(typically None). ``is_remote_eligible`` is coerced from
``raw.is_remote_eligible`` or ``raw.show_remote_eligibility`` via
``bool(...)`` so truthy/falsy/missing all map to a clean boolean.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from scripts.shared.constants import SourceId
from scripts.shared.models import JobListing
from scripts.shared.utils import get_iso_timestamp

logger = logging.getLogger(__name__)

SOURCE_ID = SourceId.EIGHTFOLD
DEFAULT_TIMEOUT_SECONDS = 30.0

# Eightfold caps each page at 10 rows server-side. Requesting ``num > 10``
# returns at most 10 positions. Verified empirically 2026-04-18 (and on the
# frontend client's ``EIGHTFOLD_MAX_PAGE_SIZE = 10`` since the same date).
EIGHTFOLD_PAGE_SIZE = 10

# Safety cap against runaway pagination loops. Netflix-sized tenants fit
# comfortably under this; the frontend uses 200 but the backend halves it
# because a runaway Eightfold tenant should be visible faster in a worker
# (and at 100 pages we've already fetched 1000 jobs — well past where
# returning a partial result is more useful than raising).
MAX_PAGES = 100

# -----------------------------------------------------------------------------
# SSRF allowlist — ported verbatim from ``api/eightfold.ts``.
#
# Restricts upstream hosts to ``*.eightfold.ai`` plus a small vanity-host set.
# Once Unit 7 deletes the Vercel proxy, this Python check is the ONLY defense
# against an SSRF caused by a wrong ``tenant_host`` in ``provider_config``.
#
# Adding a new vanity host requires updating BOTH the seed migration (so the
# row exists with the right tenant_host) AND this set (so the fetch task
# accepts it). The two were synchronized in ``api/eightfold.ts`` originally;
# now this file is the source of truth.
# -----------------------------------------------------------------------------
_EIGHTFOLD_HOST_PATTERN = re.compile(
    r"^(?:[a-z0-9-]+\.)*eightfold\.ai$", re.IGNORECASE
)
_EIGHTFOLD_VANITY_HOSTS: frozenset[str] = frozenset(
    {
        "explore.jobs.netflix.net",
    }
)


def _is_allowed_eightfold_host(host: str | None) -> bool:
    """Return True iff ``host`` is on the SSRF allowlist.

    Mirrors ``api/eightfold.ts::isAllowedEightfoldHost``. The lowercase
    normalization matches the TS proxy's behavior so a value that worked
    via the proxy continues to work via this backend port.

    Both the regex match and the vanity-host membership check tolerate
    leading/trailing whitespace via the trim in the call site, but for
    safety we also strip here.
    """
    if not host or not isinstance(host, str):
        return False
    normalized = host.strip().lower()
    if not normalized:
        return False
    if normalized in _EIGHTFOLD_VANITY_HOSTS:
        return True
    return bool(_EIGHTFOLD_HOST_PATTERN.match(normalized))


# -----------------------------------------------------------------------------
# Fetch
# -----------------------------------------------------------------------------


async def fetch_jobs(
    tenant_host: str,
    domain: str,
    http: httpx.AsyncClient,
) -> list[dict]:
    """Fetch all positions for an Eightfold tenant via sequential pagination.

    Issues GET requests to ``https://{tenant_host}/api/apply/v2/jobs`` with
    ``domain``, ``num``, ``start`` query params. Eightfold caps each page at
    10 rows, so this walks ``start=0, 10, 20, ...`` until one of the break
    conditions trips:

    - ``len(all_positions) >= count`` (server-reported total, captured on
      page 1)
    - empty positions array (defensive — Eightfold sometimes returns 0 rows
      before the reported ``count`` is exhausted; we still treat empty as
      "we're done")
    - partial page (< ``EIGHTFOLD_PAGE_SIZE`` rows — the real-world end-of-
      data signal, since Eightfold under-reports ``count`` more often than
      it over-reports)
    - ``MAX_PAGES`` cap — ERROR log + partial-return backstop (see module
      docstring for rationale)

    Raises
    ------
    ValueError
        - ``tenant_host`` is not on the SSRF allowlist. Raised BEFORE any
          outbound HTTP call. This is the load-bearing security check that
          replaced ``api/eightfold.ts``.
        - Any page is missing ``positions`` (non-list) or ``count``
          (non-int).
    httpx.HTTPStatusError
        Non-2xx on any page aborts the whole fetch (Eightfold pages don't
        compose well — a 500 mid-walk likely means subsequent pages are
        broken too, so we surface the failure to Procrastinate's retry).

    Returns
    -------
    list[dict]
        Aggregated raw positions across all pages. May be empty.
    """
    # SSRF check before any DNS resolution / TCP / TLS handshake.
    # This is the only defense after Unit 7 deletes the Vercel proxy.
    if not _is_allowed_eightfold_host(tenant_host):
        raise ValueError(
            f"Eightfold tenant_host {tenant_host!r} is not on the SSRF allowlist "
            f"(must match *.eightfold.ai or be in the explicit vanity host set; "
            f"see eightfold_client._EIGHTFOLD_VANITY_HOSTS)"
        )
    if not domain or not isinstance(domain, str):
        raise ValueError(
            f"Eightfold fetch requires a non-empty domain; got {domain!r}"
        )

    base_url = f"https://{tenant_host}/api/apply/v2/jobs"
    all_positions: list[dict] = []
    total: Optional[int] = None
    iterations = 0

    for iteration in range(1, MAX_PAGES + 1):
        iterations = iteration
        offset = (iteration - 1) * EIGHTFOLD_PAGE_SIZE
        params: dict[str, str | int] = {
            "domain": domain,
            "num": EIGHTFOLD_PAGE_SIZE,
            "start": offset,
        }
        logger.debug(
            "Eightfold page %d: GET %s domain=%s start=%d",
            iteration, base_url, domain, offset,
        )

        response = await http.get(
            base_url,
            params=params,
            headers={"Accept": "application/json"},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError(
                f"Eightfold response for {tenant_host!r} page {iteration} is "
                f"not a dict: got {type(payload).__name__}"
            )

        positions = payload.get("positions")
        if positions is None:
            raise ValueError(
                f"Eightfold response for {tenant_host!r} page {iteration} "
                f"missing 'positions' key"
            )
        if not isinstance(positions, list):
            raise ValueError(
                f"Eightfold response for {tenant_host!r} page {iteration} "
                f"'positions' is not a list: got {type(positions).__name__}"
            )

        # Capture total on page 1. Eightfold sometimes lies (over- or under-
        # reports), so we ALSO use partial-page detection below.
        if total is None:
            count_val = payload.get("count")
            if isinstance(count_val, int):
                total = count_val
            else:
                # Defensive: missing or non-int count. We can still walk via
                # partial-page detection — don't abort the fetch over a
                # missing/wrong count.
                logger.warning(
                    "Eightfold page 1 for %s missing or non-int 'count' "
                    "(got %r); falling back to partial-page detection",
                    tenant_host, count_val,
                )
                total = None

        all_positions.extend(positions)
        page_size = len(positions)

        # Break conditions, evaluated in priority order.
        if total is not None and len(all_positions) >= total:
            logger.debug(
                "Eightfold pagination done for %s: hit reported total %d "
                "after %d pages",
                tenant_host, total, iteration,
            )
            break
        if page_size == 0:
            logger.debug(
                "Eightfold pagination done for %s: empty page %d "
                "(server exhausted; total was %r)",
                tenant_host, iteration, total,
            )
            break
        if page_size < EIGHTFOLD_PAGE_SIZE:
            logger.debug(
                "Eightfold pagination done for %s: partial page %d "
                "(got %d rows; reported total was %r)",
                tenant_host, iteration, page_size, total,
            )
            break
    else:
        # MAX_PAGES reached without a natural break. Return partial result
        # rather than raising — see module docstring for rationale.
        # ERROR level so Railway routes it to stderr (where @level:error
        # is queryable).
        logger.error(
            "Eightfold pagination MAX_PAGES (%d) reached for %s: returning "
            "partial result of %d positions (server-reported total was %r). "
            "If this fires repeatedly, raise MAX_PAGES or investigate the "
            "tenant for unbounded growth.",
            MAX_PAGES, tenant_host, len(all_positions), total,
        )

    logger.info(
        "Eightfold fetched %d positions for %s in %d pages",
        len(all_positions), tenant_host, iterations,
    )
    return all_positions


# -----------------------------------------------------------------------------
# Transform
# -----------------------------------------------------------------------------


def transform_to_job_listings(
    company_id: str,
    raw_positions: list[dict],
) -> list[JobListing]:
    """Map a list of raw Eightfold positions to ``JobListing`` rows.

    Filters out:
      - positions with ``isPrivate == True`` (mirrors frontend client)
      - positions missing all three id candidates (id, ats_job_id,
        display_job_id)
      - positions missing ``name`` or ``canonicalPositionUrl``

    See module docstring for the id format and ``details`` shape contracts.
    """
    now = get_iso_timestamp()
    out: list[JobListing] = []
    skipped_private = 0
    skipped_invalid = 0

    # Dedup by job_id with a drift-vs-collision diagnostic. Eightfold paginates
    # by offset (start=0, 10, 20, ...) and on a live tenant new positions can
    # shift the window so a single underlying job appears on two adjacent
    # pages — same id, same (title, url). That's pagination drift and is
    # expected; we log INFO. The other case is an id-fallback chain collapse:
    # two genuinely different positions resolving to the same job_id because
    # one row's `id` was empty and we fell through to `ats_job_id` /
    # `display_job_id` that the other row was using as `id`. That's silent
    # data corruption — log WARN with both (title, url) pairs so it's
    # investigable from logs alone. See
    # `docs/incidents/2026-05-20-eightfold-upsert-cardinality-violation.md`.
    deduped: dict[str, JobListing] = {}
    drift = 0
    collisions = 0
    for raw in raw_positions:
        if not isinstance(raw, dict):
            skipped_invalid += 1
            continue
        if raw.get("isPrivate"):
            skipped_private += 1
            continue
        listing = _transform_one(company_id, raw, now)
        if listing is None:
            skipped_invalid += 1
            continue
        prev = deduped.get(listing.id)
        if prev is None:
            deduped[listing.id] = listing
            continue
        if prev.title == listing.title and prev.url == listing.url:
            drift += 1
        else:
            collisions += 1
            logger.warning(
                "Eightfold id collision for %s on id=%r: kept "
                "(title=%r, url=%r), dropped (title=%r, url=%r) — "
                "id fallback chain collapsed two distinct positions",
                company_id, listing.id,
                prev.title, prev.url, listing.title, listing.url,
            )
    out = list(deduped.values())

    if drift:
        logger.info(
            "Eightfold transform for %s: %d pagination-drift duplicate(s) "
            "dropped (expected on offset-paginated tenants)",
            company_id, drift,
        )
    if skipped_private or skipped_invalid:
        logger.debug(
            "Eightfold transform for %s: kept=%d, skipped_private=%d, "
            "skipped_invalid=%d",
            company_id, len(out), skipped_private, skipped_invalid,
        )
    return out


def _extract_eightfold_id(raw: dict[str, Any]) -> Optional[str]:
    """Pick the first non-empty id source. Returns None if all are falsy."""
    for key in ("id", "ats_job_id", "display_job_id"):
        val = raw.get(key)
        if val is None or val == "":
            continue
        return str(val)
    return None


def _extract_location(raw: dict[str, Any]) -> Optional[str]:
    """Resolve the row ``location`` from Eightfold's location/locations fields.

    Eightfold often returns location as a comma-delimited string with no
    spaces (e.g. ``"Los Angeles,California,United States"``). We re-join
    with ``", "`` for display consistency — matches the frontend
    transformer's behavior.

    Falls back to the first entry of ``raw.locations`` (an array) when
    ``raw.location`` is empty.
    """
    primary = raw.get("location")
    if isinstance(primary, str) and primary.strip():
        return _normalize_location_string(primary)
    secondary = raw.get("locations")
    if isinstance(secondary, list) and secondary:
        first = secondary[0]
        if isinstance(first, str) and first.strip():
            return _normalize_location_string(first)
    return None


def _normalize_location_string(value: str) -> str:
    """Split-trim-rejoin ``"A,B,C"`` → ``"A, B, C"``. Matches the frontend."""
    segments = [seg.strip() for seg in value.split(",") if seg.strip()]
    return ", ".join(segments) if segments else value.strip()


def _parse_eightfold_epoch(value: Any) -> Optional[str]:
    """Convert Eightfold's ``t_create`` (Unix epoch SECONDS) to UTC ISO 8601.

    Accepts int, float, or numeric-string forms. Returns ``None`` on any
    parse failure — the caller stores ``None`` so a corrupt source value
    never silently becomes a wrong timestamp (per
    ``feedback_correctness_over_dont_crash``).

    Eightfold's ``t_create`` is documented as seconds, but we defensively
    handle the "looks like milliseconds" case by checking if the value is
    implausibly large for seconds (> year 9999 in seconds ≈ 2.5e11) and
    dividing. This matters because the frontend transformer assumes
    seconds; if a future Eightfold response shipped milliseconds we'd
    silently store year-50000+ dates.
    """
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    # Defensive: if the value is too large to be plausible seconds-since-epoch
    # (a year >= 5000), treat as milliseconds.
    if numeric > 1e11:
        numeric = numeric / 1000.0
    try:
        dt = datetime.fromtimestamp(numeric, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.isoformat()


def _transform_one(
    company_id: str,
    raw: dict[str, Any],
    now: str,
) -> Optional[JobListing]:
    """Transform a single Eightfold position dict to a ``JobListing``.

    Returns ``None`` if the row is missing one of the required fields
    (id sources, name, canonicalPositionUrl) — these correspond to the
    frontend's ``validPositions`` filter.
    """
    job_id = _extract_eightfold_id(raw)
    if not job_id:
        return None

    title = raw.get("name")
    if not isinstance(title, str) or not title.strip():
        return None

    url = raw.get("canonicalPositionUrl")
    if not isinstance(url, str) or not url.strip():
        return None

    location = _extract_location(raw)
    posted_on = _parse_eightfold_epoch(raw.get("t_create"))

    # ``experience_level``: Eightfold's API sometimes exposes a string here,
    # sometimes nothing. Pass through whatever's there (frontend reads it
    # from ``details.experience_level``).
    experience_level = raw.get("experience_level")
    if experience_level is not None and not isinstance(experience_level, str):
        # Coerce non-string truthy values defensively — the frontend
        # expects a string or null.
        experience_level = str(experience_level)

    # ``is_remote_eligible``: bool() coercion mirrors frontend transformer's
    # behavior so missing/null/0/False all map to False.
    is_remote_eligible = bool(
        raw.get("is_remote_eligible") or raw.get("show_remote_eligibility")
    )

    details = {
        "experience_level": experience_level,
        "is_remote_eligible": is_remote_eligible,
        "department": raw.get("department"),
        "team": raw.get("team"),
        "canonical_position_url": url,
        # Preserve original ``locations`` array for debugging — distinct from
        # the joined ``location`` string emitted to the row column.
        "locations": raw.get("locations"),
        # Original Unix-epoch value so a future re-parse (or different
        # parser) doesn't need a re-fetch.
        "t_create_raw": raw.get("t_create"),
    }

    return JobListing(
        id=job_id,
        title=title,
        company=company_id,
        location=location,
        url=url,
        source_id=SOURCE_ID,
        details=details,
        posted_on=posted_on,
        created_at=now,
        first_seen_at=now,
        last_seen_at=now,
        consecutive_misses=0,
        details_scraped=True,
        status="OPEN",
        has_matched=False,
        ai_metadata={},
        closed_on=None,
    )
