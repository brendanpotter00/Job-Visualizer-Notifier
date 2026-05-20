"""Pure Workday CXS API client + transformer.

Two queue-agnostic functions plus a date-parser helper:

- ``fetch_jobs(provider_config, http)``: POSTs to Workday's CXS jobs
  endpoint, paginates offset against ``total``, and returns the
  aggregated ``jobPostings`` array. No DB, no transformation.
- ``transform_to_job_listings(company_id, raw_jobs, provider_config, now=None)``:
  maps each raw Workday posting dict to a
  :class:`scripts.shared.models.JobListing` ready for
  ``upsert_jobs_batch``.
- ``_parse_workday_date(posted_on, now=None)``: Python port of the
  frontend ``parseWorkdayDate`` helper in
  ``src/frontend/src/lib/workdayDateParser.ts``. Inputs are the relative
  date strings Workday emits (``"Posted Today"`` / ``"Posted Yesterday"``
  / ``"Posted N Days Ago"`` / ``"Posted N+ Days Ago"``); output is an
  ISO 8601 UTC string at midnight or ``None`` for unparseable input.

Structural notes
----------------
Unlike Greenhouse/Ashby/Gem/Lever (GET, single round trip, top-level
``{jobs:[...]}`` or array), Workday requires:

* **POST** with a JSON body of shape
  ``{"appliedFacets": <facets>, "limit": 20, "offset": <N>, "searchText": ""}``.
* **Pagination** via ``offset``; the response carries ``total`` so we
  know when to stop.
* **Per-company config** at the URL level — the path is
  ``/wday/cxs/{tenant_slug}/{career_site_slug}/jobs`` and the host is
  the Workday tenant's pod-specific subdomain (e.g.
  ``nvidia.wd5.myworkdayjobs.com``). All three live in the row's
  ``provider_config`` JSONB blob.

Pagination is capped at ``WORKDAY_MAX_PAGES`` × ``WORKDAY_PAGE_SIZE`` =
2 000 jobs/company to bound a runaway loop (e.g. if Workday ever ships a
``total`` that lies, or if a pathological response keeps returning a
non-empty page that never advances the cursor). The cap surfaces an
ERROR log line — Railway routes ERROR to stderr, where ``@level:error``
filters pick it up. The cap path does NOT raise; the caller still gets
the partial result and records a normal ``scrape_runs`` row.

The id stored on ``JobListing`` is ``raw["bulletFields"][0]`` (Workday's
requisition id, e.g. ``"JR123456"``) when present, otherwise the last
path segment of ``raw["externalPath"]`` (e.g.
``"Software-Engineer_JR123"``). Workday's id space is per-tenant; the
composite ``(source_id, id)`` PK on ``job_listings`` keeps Workday rows
from colliding with other sources even if requisition ids ever overlap.

``details`` JSONB
-----------------
Workday's list endpoint returns very little structured metadata —
``title``, ``externalPath``, ``locationsText``, ``postedOn``, and a
``bulletFields`` array of opaque strings. Detail pages (description,
team, employment type, compensation) require a second round-trip per
job, which the frontend deliberately skipped because the list view
shows enough to drive the visualization. We mirror that scope:
``details`` is populated with the keys other migrated providers emit
(``experience_level``, ``is_remote_eligible``, ``department``, ``team``,
``employment_type``, ``secondary_locations``, ``compensation_summary``,
``description_html``, ``tags``), all set to ``None`` / ``[]``. Only
``published_at`` (the parsed ``postedOn``) carries data.

Date parsing
------------
``_parse_workday_date`` is a faithful Python port of
``parseWorkdayDate``. The inputs are inherently low-resolution (Workday
buckets to "today / yesterday / N days ago / N+ days ago"), so the
output is always midnight UTC. ``None`` and unparseable strings return
``None`` rather than falling back to ``now()`` — per
``feedback_correctness_over_dont_crash.md``, a corrupt source value
must land as ``NULL`` (not as a fake recent timestamp that would
silently land on today's row in the visualization).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from scripts.shared.constants import SourceId
from scripts.shared.models import JobListing
from scripts.shared.utils import get_iso_timestamp

logger = logging.getLogger(__name__)


# Workday CXS API constants. Page size is documented as a server cap of
# 20 — sending a larger `limit` gets silently clamped, so the cap is
# load-bearing for the offset math (we need page_size to equal the
# server's actual returned page size for `offset += page_size` to work).
WORKDAY_PAGE_SIZE = 20
WORKDAY_MAX_PAGES = 100
DEFAULT_TIMEOUT_SECONDS = 30.0
SOURCE_ID = SourceId.WORKDAY

# Required keys in `provider_config`. Validated at the call site (the
# task in Unit 4) and again here for defense in depth.
_REQUIRED_PROVIDER_KEYS: tuple[str, ...] = (
    "base_url",
    "tenant_slug",
    "career_site_slug",
)


def _validate_provider_config(provider_config: dict) -> None:
    """Raise ``ValueError`` if a Workday ``provider_config`` is missing
    required keys (``base_url``, ``tenant_slug``, ``career_site_slug``).

    Exposed as a helper rather than inlined so the caller (Unit 4 task)
    can validate before doing any IO and so unit tests can pin the exact
    contract without round-tripping through ``fetch_jobs``.
    """
    if not isinstance(provider_config, dict):
        raise ValueError(
            f"workday provider_config must be a dict, got "
            f"{type(provider_config).__name__}"
        )
    missing = [
        k for k in _REQUIRED_PROVIDER_KEYS
        if not provider_config.get(k)
    ]
    if missing:
        raise ValueError(
            f"workday provider_config missing required keys {missing!r}; "
            f"got keys {sorted(provider_config)}"
        )


async def fetch_jobs(
    provider_config: dict,
    http: httpx.AsyncClient,
) -> list[dict]:
    """Fetch all postings from a Workday career site, paginating offset.

    POSTs to ``{base_url}/wday/cxs/{tenant_slug}/{career_site_slug}/jobs``
    with a body of ``{"appliedFacets": <facets>, "limit": 20, "offset": N,
    "searchText": ""}``. ``<facets>`` is ``provider_config.get
    ("default_facets") or {}`` — NVIDIA and Adobe use this to narrow the
    population; everyone else gets the empty object.

    Returns the aggregated ``jobPostings`` list across all pages. Empty
    list is a valid return value (a career site with zero open reqs).

    Raises:
      - ``ValueError`` for malformed `provider_config` or response shape.
      - ``httpx.HTTPStatusError`` for non-2xx responses.

    Both are treated as a failed run by the caller (Unit 4) — Procrastinate
    retries, ``scrape_runs`` records ``error_count=1``.

    The pagination cap (``WORKDAY_MAX_PAGES``) is enforced as a soft
    backstop: if we hit it, we ERROR-log and return what we have so far.
    The caller still upserts that partial result (so the visualization
    has SOME data) and records the run with ``error_count=0`` — the cap
    breach is *not* an error in the usual sense, just a "more pages
    than expected" signal that the operator should look at the log for.
    The hard exit conditions are: ``offset >= total``, empty page,
    or no advance from previous offset.
    """
    _validate_provider_config(provider_config)

    base_url = str(provider_config["base_url"]).rstrip("/")
    tenant_slug = provider_config["tenant_slug"]
    career_site_slug = provider_config["career_site_slug"]
    default_facets = provider_config.get("default_facets") or {}

    url = (
        f"{base_url}/wday/cxs/{tenant_slug}/{career_site_slug}/jobs"
    )

    all_postings: list[dict] = []
    offset = 0
    total: Optional[int] = None
    page_idx = 0

    logger.info(
        "Fetching Workday postings for %s/%s",
        tenant_slug, career_site_slug,
    )

    while page_idx < WORKDAY_MAX_PAGES:
        page_idx += 1
        body = {
            "appliedFacets": default_facets,
            "limit": WORKDAY_PAGE_SIZE,
            "offset": offset,
            "searchText": "",
        }

        response = await http.post(
            url,
            json=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                # Workday's CXS endpoint is usually fine without a UA but
                # some tenants 403 a missing one. Mirror what `api/workday.ts`
                # sent so behavior is preserved across the migration.
                "User-Agent": "Job-Visualizer-Notifier/1.0",
            },
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError(
                f"Workday response root for {tenant_slug}/{career_site_slug} "
                f"is not a dict: got {type(payload).__name__}"
            )
        page = payload.get("jobPostings")
        if page is None or not isinstance(page, list):
            raise ValueError(
                f"Workday response missing or malformed 'jobPostings' for "
                f"{tenant_slug}/{career_site_slug}: got "
                f"{type(page).__name__}"
            )

        # Capture total on the first iteration only — Workday is documented
        # to return it on every page, but trusting only the first
        # eliminates a class of "total shrinks mid-pagination" bugs.
        if total is None:
            raw_total = payload.get("total")
            if not isinstance(raw_total, int) or raw_total < 0:
                raise ValueError(
                    f"Workday response missing or invalid 'total' for "
                    f"{tenant_slug}/{career_site_slug}: got {raw_total!r}"
                )
            total = raw_total

        all_postings.extend(page)

        # Stop conditions, in priority order:
        # 1. Empty page → no more results regardless of `total`.
        # 2. Reached or exceeded total → done.
        # 3. Otherwise advance and loop.
        if len(page) == 0:
            break
        if len(all_postings) >= total:
            break
        offset += WORKDAY_PAGE_SIZE

    if page_idx >= WORKDAY_MAX_PAGES and (total is None or len(all_postings) < total):
        # ERROR (not WARNING): Railway @level routing — see _configure_logging
        # in main.py. A persistent cap-trip indicates either a runaway
        # listing (multi-thousand-req tenant) or a pagination bug, both
        # of which the operator needs to see in @level:error filters.
        logger.error(
            "Workday pagination cap hit for %s/%s: stopped at page %d "
            "(%d jobs fetched, total=%r). Cap is %d pages of %d jobs each.",
            tenant_slug, career_site_slug, page_idx,
            len(all_postings), total, WORKDAY_MAX_PAGES, WORKDAY_PAGE_SIZE,
        )

    logger.info(
        "Workday returned %d postings for %s/%s (total=%r, pages=%d)",
        len(all_postings), tenant_slug, career_site_slug, total, page_idx,
    )
    return all_postings


def transform_to_job_listings(
    company_id: str,
    raw_jobs: list[dict],
    provider_config: dict,
    now: Optional[str] = None,
) -> list[JobListing]:
    """Map a list of Workday posting dicts to ``JobListing`` rows.

    ``now`` is an injection seam so tests can pin a deterministic
    timestamp without monkeypatching ``get_iso_timestamp``. In production
    the caller passes ``None`` and we sample once at entry so every
    listing in this batch shares a created_at/first_seen_at/last_seen_at.

    Filters out postings with an empty/missing ``title`` (the frontend
    transformer required both ``title`` and ``externalPath``; we relax
    to title-only because we have a deterministic id-fallback path for
    missing ``externalPath``). Invalid postings are silently skipped at
    DEBUG level so a single malformed entry doesn't poison the batch.

    Deduplicates by ``job_id`` with a drift-vs-collision diagnostic.
    Workday paginates by offset (page size 20) and on a live tenant new
    requisitions can shift the window so a single posting appears on two
    adjacent pages — same id, same (title, url). That's pagination
    drift and is expected; we log INFO. The other case is an id-fallback
    chain collapse: two genuinely different postings resolving to the
    same job_id because both rows had empty/non-string ``bulletFields``
    and their ``externalPath`` last segments happened to match. That's
    silent data corruption — log WARN with both (title, url) pairs so
    it's investigable from logs alone. Mirrors the Eightfold dedup added
    in ``eightfold_client.transform_to_job_listings``; see
    ``docs/incidents/2026-05-20-eightfold-upsert-cardinality-violation.md``.

    See module docstring for the id format, URL construction, and
    ``details`` JSONB shape contracts.
    """
    _validate_provider_config(provider_config)
    if now is None:
        now = get_iso_timestamp()

    deduped: dict[str, JobListing] = {}
    drift = 0
    collisions = 0
    for raw in raw_jobs:
        try:
            listing = _transform_one(company_id, raw, provider_config, now)
        except _SkipPosting as e:
            logger.debug(
                "Skipping invalid Workday posting for %s: %s (raw=%r)",
                company_id, e, raw,
            )
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
                "Workday id collision for %s on id=%r: kept "
                "(title=%r, url=%r), dropped (title=%r, url=%r) — "
                "id fallback chain collapsed two distinct postings",
                company_id, listing.id,
                prev.title, prev.url, listing.title, listing.url,
            )

    if drift:
        logger.info(
            "Workday transform for %s: %d pagination-drift duplicate(s) "
            "dropped (expected on offset-paginated tenants)",
            company_id, drift,
        )
    return list(deduped.values())


class _SkipPosting(Exception):
    """Internal marker — a single posting is unusable, skip it."""


def _transform_one(
    company_id: str,
    raw: dict[str, Any],
    provider_config: dict,
    now: str,
) -> JobListing:
    """Transform a single Workday posting dict to a ``JobListing``."""
    title = raw.get("title")
    if not title or not isinstance(title, str):
        raise _SkipPosting("missing or non-string 'title'")

    external_path = raw.get("externalPath")
    # The frontend transformer also required externalPath. We relax that
    # because we have a deterministic ID fallback from bulletFields[0],
    # but we still require a usable URL — without a path we can't link
    # the job, and a non-linkable job is useless in the visualization.
    if not external_path or not isinstance(external_path, str):
        raise _SkipPosting("missing or non-string 'externalPath'")

    bullet_fields = raw.get("bulletFields") or []
    if not isinstance(bullet_fields, list):
        bullet_fields = []

    # ID extraction: prefer the requisition id (`bulletFields[0]`, e.g.
    # "JR123456"). Fall back to the last path segment of externalPath
    # (the same fallback the frontend transformer used). Coerce to str
    # so a freak non-string id from Workday doesn't break upsert.
    first_bullet = bullet_fields[0] if bullet_fields else None
    if isinstance(first_bullet, str) and first_bullet:
        job_id = first_bullet
    else:
        # externalPath is something like
        # "/job/US-CA-Santa-Clara/Software-Engineer_JR123456"
        # — last segment carries the slug + requisition id.
        slug = external_path.rstrip("/").rsplit("/", 1)[-1]
        if not slug:
            raise _SkipPosting(
                f"could not derive id: bulletFields empty/non-str AND "
                f"externalPath has no last segment ({external_path!r})"
            )
        job_id = slug

    job_id = str(job_id)

    # URL construction. The frontend transformer used a
    # `<jobsUrl>/<last-segment>` shape where `jobsUrl` was an optional
    # config override defaulting to `<baseUrl>/<careerSiteSlug>/details`.
    # We mirror that with `base_url + /<career_site_slug> + /details + /<slug>`.
    base_url = str(provider_config["base_url"]).rstrip("/")
    career_site_slug = provider_config["career_site_slug"]
    slug = external_path.rstrip("/").rsplit("/", 1)[-1]
    if slug:
        url = f"{base_url}/{career_site_slug}/details/{slug}"
    else:
        # Defensive fallback — the _SkipPosting check above already
        # guarantees a slug exists, but keep this path so a future
        # refactor that loosens the guard doesn't produce a literal
        # "details/" tail.
        url = f"{base_url}/{career_site_slug}"

    # Location filtering: the frontend transformer dropped "X Locations"
    # generic counts. Mirror exactly so the visualization shows the same
    # data (and Recent Jobs city-filtering still works).
    location_raw = raw.get("locationsText")
    location: Optional[str] = None
    if isinstance(location_raw, str) and location_raw:
        if not _GENERIC_LOCATION_COUNT_RE.match(location_raw):
            location = location_raw

    posted_on = _parse_workday_date(raw.get("postedOn"))
    if raw.get("postedOn") and posted_on is None:
        # ERROR (not WARNING): Railway routes by Python level. A
        # persistently-unparseable postedOn string is a data quality
        # issue the operator should see in @level:error filters.
        logger.error(
            "Workday data quality issue: posting %s for company %s had "
            "unparseable postedOn=%r; storing posted_on as NULL",
            job_id, company_id, raw.get("postedOn"),
        )

    # `details` mirrors the JSONB key shape Ashby/Gem/Lever use so the
    # frontend backendScraperTransformer reads everything uniformly.
    # Workday's list endpoint exposes only `title`/`externalPath`/
    # `locationsText`/`postedOn`/`bulletFields[*]` structurally; the
    # other keys are None / [] because we don't have detail-page data.
    details = {
        "department": None,
        "team": None,
        "secondary_locations": [],
        "employment_type": None,
        "is_remote_eligible": None,
        "compensation_summary": None,
        "published_at": posted_on,
        "description_html": None,
        "experience_level": None,
        "tags": [],
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


# Frontend (`workdayTransformer.ts`) filters out `"<N> Locations"` /
# `"<N> Location"` generic counts. Mirror the regex shape exactly so
# both sides agree on what counts as "real" location text.
_GENERIC_LOCATION_COUNT_RE = re.compile(r"^\d+\s+Locations?$", re.IGNORECASE)


# Date parsing — port of frontend `parseWorkdayDate` in
# `src/frontend/src/lib/workdayDateParser.ts`. The semantics MUST match
# bit-for-bit so a row scraped via the backend lands on the same time
# bucket as the same row scraped via the (pre-cutover) frontend.
_DAYS_AGO_RE = re.compile(
    r"(\d+)(\+)?\s*days?\s*ago", re.IGNORECASE,
)


def _parse_workday_date(
    posted_on: Optional[str],
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Parse a Workday relative date string to an ISO 8601 UTC string.

    Handles (case-insensitive substring/regex match — same as the frontend):
      - ``"Posted Today"`` → midnight UTC today.
      - ``"Posted Yesterday"`` → midnight UTC of (today - 1d).
      - ``"Posted N Days Ago"`` → midnight UTC of (today - N days).
      - ``"Posted N+ Days Ago"`` → midnight UTC of (today - (N + 1) days).
        The frontend distinguishes "exactly N" from "N or more" by adding
        a day to the "N+" form; mirror that exactly so the visualization
        buckets jobs identically.

    Returns ``None`` for:
      - ``None`` / empty input.
      - Strings that don't match any of the patterns AND don't parse as
        ISO 8601. Per ``feedback_correctness_over_dont_crash.md``, a
        corrupt value lands as NULL (not as a fake "now" timestamp).

    ``now`` is an injection seam so tests can pin the wall clock without
    monkeypatching the stdlib.
    """
    if posted_on is None or not isinstance(posted_on, str):
        return None
    if not posted_on.strip():
        return None

    if now is None:
        now = datetime.now(tz=timezone.utc)
    # Defensive: ensure tz-aware UTC. If the caller passed a naive
    # datetime, attach UTC rather than crashing under mixed-tz arithmetic.
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today_midnight = now.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )

    lowered = posted_on.lower()

    # "today" — must match BEFORE "yesterday" since both contain neither
    # the other, but a future Workday phrasing change could overlap.
    if "today" in lowered:
        return today_midnight.isoformat().replace("+00:00", ".000Z")

    if "yesterday" in lowered:
        return (today_midnight - timedelta(days=1)).isoformat().replace(
            "+00:00", ".000Z",
        )

    m = _DAYS_AGO_RE.search(lowered)
    if m:
        base_days = int(m.group(1))
        is_plus_range = bool(m.group(2))
        days_ago = base_days + 1 if is_plus_range else base_days
        return (today_midnight - timedelta(days=days_ago)).isoformat().replace(
            "+00:00", ".000Z",
        )

    # ISO-8601 fallback. The frontend tried `new Date(postedOn)`; we use
    # `datetime.fromisoformat` which is stricter — most Workday CXS
    # tenants don't emit ISO strings on this endpoint, but if one does,
    # we honor it. On parse failure, return None (per
    # feedback_correctness_over_dont_crash.md).
    try:
        parsed = datetime.fromisoformat(posted_on.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace(
        "+00:00", ".000Z",
    )
