"""Pure Workday CXS API client + transformer.

Two queue-agnostic functions plus a date-parser helper:

- ``fetch_jobs(provider_config, http)``: POSTs to Workday's CXS jobs
  endpoint, paginates offset against ``total``, and returns the
  aggregated ``jobPostings`` array. No DB, no transformation.
- ``transform_to_job_listings(company_id, raw_jobs, provider_config, now=None)``:
  maps each raw Workday posting dict to a
  :class:`scripts.shared.models.JobListing` ready for
  ``upsert_jobs_batch``.
- ``_parse_workday_date(posted_on, now=None)``: parses the relative date
  strings Workday emits (``"Posted Today"`` / ``"Posted Yesterday"`` /
  ``"Posted N Days Ago"``); output is an ISO 8601 UTC string at midnight,
  or ``None`` for unparseable input **and for the ``"N+ Days Ago"``
  bucket**, which is a bucket label rather than a date.

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
(``experience_level``, ``is_remote_eligible``, ``team``,
``employment_type``, ``secondary_locations``, ``compensation_summary``,
``description_html``, ``tags``), all set to ``None`` / ``[]``. Only
``published_at`` (the parsed ``postedOn``) carries data.

Date parsing
------------
The inputs are inherently low-resolution (Workday buckets to "today /
yesterday / N days ago / N+ days ago"), so the output is always midnight
UTC. **``"N+ Days Ago"`` returns ``None``** — it names an open-ended
bucket and contains no date to recover; synthesising ``today - (N + 1)``
from it, as this module used to, fabricated a precise timestamp out of a
range boundary. ``None`` and unparseable strings likewise return
``None`` rather than falling back to ``now()`` — per
``feedback_correctness_over_dont_crash.md``, a corrupt source value
must land as ``NULL`` (not as a fake recent timestamp that would
silently land on today's row in the visualization).
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

from scripts.shared.constants import SourceId
from scripts.shared.models import JobListing
from scripts.shared.utils import get_iso_timestamp

from .harvest_meta import HarvestEvidence
from .job_details import has_description
from .posted_date import effective_posted_date

logger = logging.getLogger(__name__)


# Workday CXS API constants. Page size is documented as a server cap of
# 20 — sending a larger `limit` gets silently clamped, so the cap is
# load-bearing for the offset math (we need page_size to equal the
# server's actual returned page size for `offset += page_size` to work).
WORKDAY_PAGE_SIZE = 20
WORKDAY_MAX_PAGES = 100
DEFAULT_TIMEOUT_SECONDS = 30.0
SOURCE_ID = SourceId.WORKDAY

# 429 handling. Before this, a 429 raised straight out of fetch_jobs, the task
# re-raised it, and Procrastinate re-ran the whole company 5 more times within
# ~60s (exponential_wait=2 → 2/4/8/16/32s). 16 companies x 6 runs each, all
# from one Railway egress IP, kept Workday's limiter tripped.
#
# Now: a 429 is retried in place a couple of times (honoring Retry-After,
# else exponential backoff with full jitter). If it still 429s, the pod
# (``wd5.myworkdayjobs.com`` etc.) is put on cooldown and every other company
# on that pod fails fast without touching the network until it expires.
# Sleeps are capped so the worst case stays well inside the task's 120s
# wait_for.
WORKDAY_429_MAX_RETRIES = 2
WORKDAY_429_BACKOFF_BASE_SECONDS = 2.0
WORKDAY_429_MAX_SLEEP_SECONDS = 20.0
WORKDAY_COOLDOWN_SECONDS = 15 * 60
WORKDAY_MAX_COOLDOWN_SECONDS = 60 * 60
# Small gap between pages so one big tenant doesn't fire 50+ POSTs
# back-to-back. 0.25s x 100 pages (the cap) adds at most 25s.
WORKDAY_INTER_PAGE_DELAY_SECONDS = 0.25

# pod key -> monotonic deadline. Process-local: one worker process per Railway
# deploy, and a restart clearing it is fine (worst case is one more 429).
_cooldown_until: dict[str, float] = {}


class WorkdayRateLimitedError(httpx.HTTPError):
    """Workday answered 429 (after in-place retries) or its pod is cooling down.

    Subclasses ``httpx.HTTPError`` so existing ``except httpx.HTTPError``
    handlers still record a clean failed run. ``fetch_workday_company``'s retry
    strategy checks for this type and does NOT re-run the task — the next
    30-minute tick is the retry.
    """


def _pod_key(url: str) -> str:
    """Rate-limit key for a Workday URL: the pod, not the tenant.

    ``nvidia.wd5.myworkdayjobs.com`` -> ``wd5.myworkdayjobs.com``. Tenants on
    one pod share Workday's infrastructure, so a 429 for one is a signal for
    the rest. Non-``myworkdayjobs.com`` hosts key on the full host.
    """
    host = (urlsplit(url).hostname or "").lower()
    parts = host.split(".")
    if host.endswith(".myworkdayjobs.com") and len(parts) > 3:
        return ".".join(parts[1:])
    return host


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    """Parse ``Retry-After`` (delta-seconds or HTTP-date). None if absent/bad."""
    value = response.headers.get("Retry-After")
    if not value:
        return None
    value = value.strip()
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max((when - datetime.now(tz=timezone.utc)).total_seconds(), 0.0)


def _backoff_seconds(attempt: int, retry_after: Optional[float]) -> float:
    """Sleep before retry ``attempt`` (0-based). Retry-After wins; else full jitter."""
    if retry_after is not None:
        return min(retry_after, WORKDAY_429_MAX_SLEEP_SECONDS)
    ceiling = min(
        WORKDAY_429_BACKOFF_BASE_SECONDS * (2 ** attempt),
        WORKDAY_429_MAX_SLEEP_SECONDS,
    )
    return random.uniform(0, ceiling)


def _check_cooldown(pod: str) -> None:
    deadline = _cooldown_until.get(pod)
    if deadline is None:
        return
    remaining = deadline - time.monotonic()
    if remaining > 0:
        raise WorkdayRateLimitedError(
            f"Workday pod {pod} is rate-limited; cooling down for "
            f"another {remaining:.0f}s (skipping request)"
        )
    _cooldown_until.pop(pod, None)


def _trip_cooldown(pod: str, retry_after: Optional[float]) -> float:
    seconds = min(
        max(retry_after or 0.0, WORKDAY_COOLDOWN_SECONDS),
        WORKDAY_MAX_COOLDOWN_SECONDS,
    )
    _cooldown_until[pod] = time.monotonic() + seconds
    return seconds


# Diagnostics for non-2xx responses: who answered, Cloudflare or Workday?
# Workday sits behind Cloudflare, so ``Server: cloudflare`` and ``CF-RAY`` are
# on EVERY response, 200s included — they can't tell us who issued a 429.
# Only ``cf-mitigated`` or a Cloudflare challenge/error body means Cloudflare
# blocked us at the edge. ``x-wd-request-id`` means the request reached Workday.
_DIAG_BODY_CHARS = 1000
_SECRET_HEADER_HINTS = ("cookie", "authorization", "token", "secret", "api-key", "apikey")
_CLOUDFLARE_BODY_MARKERS = (
    "just a moment",
    "attention required! | cloudflare",
    "cf-chl",
    "challenge-platform",
    "cf-error-details",
    "error code: 1015",
    "you are being rate limited",
)


def _diag_blocker(response: httpx.Response, body: str) -> str:
    """Best guess at who issued a non-2xx: "cloudflare", "workday", or "unknown"."""
    if "cf-mitigated" in response.headers:
        return "cloudflare"
    lowered = body.lower()
    if any(marker in lowered for marker in _CLOUDFLARE_BODY_MARKERS):
        return "cloudflare"
    if "x-wd-request-id" in response.headers:
        return "workday"
    return "unknown"


def _diag_headers(response: httpx.Response) -> dict[str, str]:
    """All response headers, minus secret values. Set-Cookie keeps names only."""
    out: dict[str, str] = {}
    for name, value in response.headers.multi_items():
        key = name.lower()
        if key == "set-cookie":
            cookie_name = value.split("=", 1)[0].strip()
            out[key] = f"{out[key]}, {cookie_name}" if key in out else cookie_name
        elif any(hint in key for hint in _SECRET_HEADER_HINTS):
            out[key] = "<redacted>"
        else:
            out[key] = f"{out[key]}, {value}" if key in out else value
    return out


def _log_non_2xx(response: httpx.Response, url: str, label: str) -> None:
    """WARNING with status, host, headers, body head, and a blocker guess."""
    try:
        body = response.text[:_DIAG_BODY_CHARS]
    except Exception:  # pragma: no cover - undecodable body
        body = "<undecodable>"
    logger.warning(
        "Workday non-2xx for %s: status=%d blocker=%s host=%s url=%s "
        "headers=%r body=%r",
        label, response.status_code, _diag_blocker(response, body),
        urlsplit(url).hostname, url, _diag_headers(response), body,
    )


async def _post_page(
    http: httpx.AsyncClient,
    url: str,
    pod: str,
    body: dict,
    label: str,
) -> httpx.Response:
    """POST one page, retrying 429 in place. Other statuses pass through."""
    for attempt in range(WORKDAY_429_MAX_RETRIES + 1):
        _check_cooldown(pod)
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
        if not 200 <= response.status_code < 300:
            _log_non_2xx(response, url, label)
        if response.status_code != 429:
            return response

        retry_after = _retry_after_seconds(response)
        if attempt == WORKDAY_429_MAX_RETRIES:
            cooldown = _trip_cooldown(pod, retry_after)
            # ERROR: Railway @level routing (see _configure_logging in main.py).
            logger.error(
                "Workday 429 for %s after %d retries; pausing pod %s for %.0fs",
                label, WORKDAY_429_MAX_RETRIES, pod, cooldown,
            )
            raise WorkdayRateLimitedError(
                f"Workday returned 429 for {label} "
                f"(Retry-After={response.headers.get('Retry-After')!r})"
            )
        sleep_s = _backoff_seconds(attempt, retry_after)
        logger.warning(
            "Workday 429 for %s (Retry-After=%r); retry %d/%d in %.1fs",
            label, response.headers.get("Retry-After"),
            attempt + 1, WORKDAY_429_MAX_RETRIES, sleep_s,
        )
        await asyncio.sleep(sleep_s)
    raise AssertionError("unreachable")  # pragma: no cover

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


def _posting_key(raw: object) -> Optional[str]:
    """A stable per-posting identity for page-advance disjointness (check 6).

    Mirrors the id derivation in ``_transform_one``: prefer the requisition id
    (``bulletFields[0]``), fall back to ``externalPath``. Returns ``None`` for a
    posting from which neither can be read (it simply does not participate in the
    overlap test). Used only to detect Intel-style offset-wrap, where paging past
    ``total`` wraps to page 1 and re-serves ids already seen.
    """
    if not isinstance(raw, dict):
        return None
    bullet_fields = raw.get("bulletFields")
    if isinstance(bullet_fields, list) and bullet_fields:
        first = bullet_fields[0]
        if isinstance(first, str) and first:
            return first
    external_path = raw.get("externalPath")
    if isinstance(external_path, str) and external_path:
        return external_path
    return None


async def fetch_jobs_with_meta(
    provider_config: dict,
    http: httpx.AsyncClient,
) -> tuple[list[dict], HarvestEvidence]:
    """Fetch a Workday site AND the completeness evidence around it (E7).

    Same offset-paginated POST loop as the public path, but ALSO surfaces the
    three completeness signals the ``declared_probed`` gate needs:

    * ``declared_total`` = Workday's page-1 ``total`` (its own trusted count).
    * ``cap_hit`` = we stopped on ``WORKDAY_MAX_PAGES`` without reaching ``total``
      — the exact silent-partial condition behind the Target 11,960-vs-2,000
      trap. The gate maps ``cap_hit`` → UNVERIFIED (it does NOT raise, so the
      2,000 rows we *did* get are kept and never mislabeled a transport error).
    * ``page_advance_ok`` = every page's id-set was disjoint from the union so
      far. An Intel-style offset-wrap (page 2 repeats page 1) sets this ``False``.

    Empty list is a valid return (a site with zero open reqs) — evidence then
    carries ``declared_total=total`` (0) so the zero-proof chain can act on it.
    """
    _validate_provider_config(provider_config)

    base_url = str(provider_config["base_url"]).rstrip("/")
    tenant_slug = provider_config["tenant_slug"]
    career_site_slug = provider_config["career_site_slug"]
    default_facets = provider_config.get("default_facets") or {}

    url = (
        f"{base_url}/wday/cxs/{tenant_slug}/{career_site_slug}/jobs"
    )
    pod = _pod_key(url)
    label = f"{tenant_slug}/{career_site_slug}"

    all_postings: list[dict] = []
    offset = 0
    total: Optional[int] = None
    page_idx = 0
    seen_page_keys: set[str] = set()
    page_advance_ok = True

    logger.info(
        "Fetching Workday postings for %s/%s",
        tenant_slug, career_site_slug,
    )

    while page_idx < WORKDAY_MAX_PAGES:
        if page_idx > 0:
            await asyncio.sleep(WORKDAY_INTER_PAGE_DELAY_SECONDS)
        page_idx += 1
        body = {
            "appliedFacets": default_facets,
            "limit": WORKDAY_PAGE_SIZE,
            "offset": offset,
            "searchText": "",
        }

        response = await _post_page(http, url, pod, body, label)
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

        # Check 6 — this page's ids must be disjoint from every prior page.
        # An offset that wraps past `total` back to page 1 re-serves the same
        # ids; the intersection is then non-empty and completeness is unproven.
        page_keys = {k for k in (_posting_key(p) for p in page) if k is not None}
        if page_keys & seen_page_keys:
            page_advance_ok = False
        seen_page_keys |= page_keys

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

    cap_hit = page_idx >= WORKDAY_MAX_PAGES and (
        total is None or len(all_postings) < total
    )
    if cap_hit:
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
        "Workday returned %d postings for %s/%s (total=%r, pages=%d, cap_hit=%s)",
        len(all_postings), tenant_slug, career_site_slug, total, page_idx, cap_hit,
    )
    evidence = HarvestEvidence(
        declared_total=total,
        cap_hit=cap_hit,
        terminated_cleanly=not cap_hit,
        # A single-page fetch has no page N to compare, so advance is vacuously
        # ok; the flag only ever flips False on a real multi-page overlap.
        page_advance_ok=page_advance_ok,
        pages_fetched=page_idx,
    )
    return all_postings, evidence


async def fetch_jobs(
    provider_config: dict,
    http: httpx.AsyncClient,
) -> list[dict]:
    """Fetch all postings from a Workday career site, paginating offset.

    Thin delegator over :func:`fetch_jobs_with_meta` that discards the evidence,
    so the PUBLIC Workday cron keeps byte-identical behavior — including the
    "cap hit → ERROR-log and return the partial 2,000" backstop, which lives in
    ``fetch_jobs_with_meta`` and therefore still fires here. Only the custom path
    reads ``cap_hit`` and acts on it (UNVERIFIED).

    POSTs to ``{base_url}/wday/cxs/{tenant_slug}/{career_site_slug}/jobs``
    with a body of ``{"appliedFacets": <facets>, "limit": 20, "offset": N,
    "searchText": ""}``. Returns the aggregated ``jobPostings`` list across all
    pages. Empty list is a valid return value (a career site with zero reqs).

    Raises:
      - ``ValueError`` for malformed `provider_config` or response shape.
      - ``httpx.HTTPStatusError`` for non-2xx responses.
      - ``WorkdayRateLimitedError`` for a 429 that survived in-place retries,
        or when the pod is already cooling down from one.
    """
    postings, _ = await fetch_jobs_with_meta(provider_config, http)
    return postings


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
    if (
        raw.get("postedOn")
        and posted_on is None
        and not _is_open_ended_bucket(raw.get("postedOn"))
    ):
        # ERROR (not WARNING): Railway routes by Python level. A
        # persistently-unparseable postedOn string is a data quality
        # issue the operator should see in @level:error filters.
        #
        # "N+ Days Ago" is excluded: it is an expected bucket label that
        # correctly yields NULL, not a parse failure. Without the guard
        # this fires on 42.3% of open prod Workday rows every tick.
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
    details: dict[str, Any] = {
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
        # THE EFFECTIVE POSTED DATE (POSTED-DATE-PLAN.md §2, D9/D10). This is the
        # client the whole trust story is about, and the two halves meet here:
        #
        #   * ``"Posted Today"`` / ``"Yesterday"`` / ``"N Days Ago"`` are real
        #     dates (57.7% of open Workday rows) and become the sort key.
        #   * ``"Posted 30+ Days Ago"`` is a BUCKET BOUNDARY, not a date.
        #     ``_parse_workday_date`` returns None for it (U5a), so those 42.3%
        #     fall back to first sight. That fallback is the intended outcome —
        #     nothing downstream can tell a fabricated timestamp from a real one.
        #
        # Workday also re-derives its relative strings against today, so a
        # listing's ``posted_on`` walks forward on every scrape. That slide must
        # never reach this column, and cannot: ``first_seen_at`` is absent from
        # ``_UPSERT_ON_CONFLICT`` (scripts/shared/database.py), so this line only
        # ever decides an INSERT.
        first_seen_at=effective_posted_date(posted_on, now),
        last_seen_at=now,
        consecutive_misses=0,
        # Truthful, not hard-coded True: this claims we HAVE the job's detail
        # content. See ``job_details.has_description`` for what that means and
        # which rows were lying.
        details_scraped=has_description(details),
        status="OPEN",
        has_matched=False,
        ai_metadata={},
        closed_on=None,
    )


# Frontend (`workdayTransformer.ts`) filters out `"<N> Locations"` /
# `"<N> Location"` generic counts. Mirror the regex shape exactly so
# both sides agree on what counts as "real" location text.
_GENERIC_LOCATION_COUNT_RE = re.compile(r"^\d+\s+Locations?$", re.IGNORECASE)


# Date parsing. Originally a bit-for-bit port of the frontend's
# `parseWorkdayDate`; that file (`src/frontend/src/lib/workdayDateParser.ts`)
# no longer exists — the backend is the only Workday parser now, and this is
# deliberately no longer a mirror of it (see `_parse_workday_date` on the
# `"N+ Days Ago"` bucket).
_DAYS_AGO_RE = re.compile(
    r"(\d+)(\+)?\s*days?\s*ago", re.IGNORECASE,
)


def _iso_millis_z(moment: datetime) -> str:
    """``moment`` as ``YYYY-MM-DDTHH:MM:SS.mmmZ``. UTC, always exactly this shape.

    Replaces ``.isoformat().replace("+00:00", ".000Z")``, which was correct only for the
    three relative-date branches — their datetimes are midnight, so ``isoformat()`` emits
    no fractional part and the appended ``.000`` was the whole of it — and produced an
    INVALID timestamp on the ISO branch. ``datetime.fromisoformat`` keeps microseconds
    when the board sends them, so ``2026-08-01T12:34:56.789000+00:00`` came back out as
    ``2026-08-01T12:34:56.789000.000Z``: two fractional parts, which Postgres rejects.

    Why that was not merely an ugly string. ``upsert_jobs_batch`` writes the harvest in
    ONE statement with no per-row fallback, so a single malformed ``posted_on`` fails the
    whole batch — every job of that tenant, not the one row that carried it.

    Latent so far only because every Workday tenant we read answers this endpoint with
    the relative phrasing ("Posted Today", "Posted 5 Days Ago"): all 6,453 open
    ``workday_api`` rows in production sit exactly at midnight, so nothing has taken the
    ISO branch yet. One tenant changing format is all it would take, and it would present
    as a tenant that abruptly stops updating rather than as a date bug.

    ``isoformat(timespec="milliseconds")`` fixes the precision at the source instead of
    patching the tail, and ``removesuffix`` is anchored where ``replace`` was not — after
    ``astimezone(timezone.utc)`` the offset is always exactly ``+00:00``.
    """
    utc = moment.astimezone(timezone.utc)
    return utc.isoformat(timespec="milliseconds").removesuffix("+00:00") + "Z"


def _is_open_ended_bucket(posted_on: Any) -> bool:
    """True for Workday's ``"N+ Days Ago"`` open-ended bucket label.

    Shares ``_DAYS_AGO_RE`` with ``_parse_workday_date`` so the two can
    never disagree about what counts as a bucket.

    This exists purely so the caller can tell "we deliberately have no
    date" apart from "this string is corrupt". Both store NULL; only the
    second is worth an ERROR. 42.3% of open prod Workday rows are in this
    bucket, so logging them would be a per-tick ERROR flood that buries
    the real data-quality signal.
    """
    if not isinstance(posted_on, str):
        return False
    m = _DAYS_AGO_RE.search(posted_on.lower())
    return bool(m and m.group(2))


def _parse_workday_date(
    posted_on: Optional[str],
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Parse a Workday relative date string to an ISO 8601 UTC string.

    Handles (case-insensitive substring/regex match — same as the frontend):
      - ``"Posted Today"`` → midnight UTC today.
      - ``"Posted Yesterday"`` → midnight UTC of (today - 1d).
      - ``"Posted N Days Ago"`` → midnight UTC of (today - N days).

    Returns ``None`` for:
      - ``None`` / empty input.
      - ``"Posted N+ Days Ago"`` — see below.
      - Strings that don't match any of the patterns AND don't parse as
        ISO 8601. Per ``feedback_correctness_over_dont_crash.md``, a
        corrupt value lands as NULL (not as a fake "now" timestamp).

    **``"N+ Days Ago"`` is not a date.** It is the label of Workday's
    open-ended oldest bucket. This function used to answer
    ``today - (N + 1)`` for it, matching a since-deleted frontend parser;
    that number was invented here, not published by the board. It now
    returns ``None`` so the caller stores NULL and the row falls back to
    first sight (see
    ``docs/implementations/custom-company-sources/POSTED-DATE-PLAN.md`` §3).

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
        return _iso_millis_z(today_midnight)

    if "yesterday" in lowered:
        return _iso_millis_z(today_midnight - timedelta(days=1))

    m = _DAYS_AGO_RE.search(lowered)
    if m:
        # "N+ Days Ago" is a BUCKET BOUNDARY, not a date. Workday says
        # "30+" for everything older than 30 days; there is no date in
        # that string to recover. We used to answer `today - (N + 1)`,
        # which fabricated a precise-looking timestamp out of nothing —
        # on prod that was 42.3% of open Workday rows all claiming to
        # have been posted exactly 31 days ago, and it slid forward by a
        # day every day. Return None so the row falls back to first
        # sight instead. The plain "N Days Ago" form below IS a date and
        # is kept exactly as-is (the accurate 57.7%).
        if m.group(2):
            return None
        days_ago = int(m.group(1))
        return _iso_millis_z(today_midnight - timedelta(days=days_ago))

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
    return _iso_millis_z(parsed)
