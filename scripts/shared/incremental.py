"""
5-phase incremental scraping algorithm

This module implements the incremental scraping logic that minimizes scraping time
by only fetching details for NEW jobs, while tracking job lifecycle (open/closed).

Algorithm phases:
1. Quick list scrape (IDs + basic info only)
2. Compare current_ids vs database active_ids
3. Fetch details ONLY for new job IDs (variable time, depends on new jobs)
4. Update last_seen for existing, increment misses for missing
5. Mark as closed if consecutive_misses >= 2

Safety guard
------------
Phases 3-5 are gated (4-5 are destructive — they can mark thousands of
jobs CLOSED), so they run only when the scrape result passes
``evaluate_safety_guard`` — the one shared, pure helper every caller uses
(this module AND the six ``src/backend/api/tasks/fetch_*_company.py`` leaf
tasks). ``resolve_safety_guard`` wraps it with the bounded auto-release.

Two rules, both keyed off the count of currently-OPEN rows:

  (a) ``jobs_seen < 0.10 * active``                     -> "empty_scrape"
  (b) ``jobs_seen < 0.85 * active`` AND
      ``(active - jobs_seen) >= 15``                    -> "partial_scrape"

Rule (b) was added after a prod audit found Apple truncating **7 times in
21 days** (2026-07-07 -> 2026-07-28) — returning 5%, 21%, 22%, 29%, 31%,
73% and 80% of its normal board — while the 0.1-only guard caught only the
5% run. The other six executed the close phase against partial data; only
a lucky clean run landing between two truncations kept ~2,800 Apple jobs
from being mass-closed.

WHAT A GUARD TRIP ACTUALLY SKIPS (be precise — this is wider than
"update/close"): the caller returns before Phase 3 as well, so on a
tripped run **no new jobs are ingested and no ``last_seen_at`` is
refreshed**, in addition to no misses being incremented and nothing being
closed. The run is a complete no-op against ``job_listings``.

That is deliberate, not an oversight: leaving ``last_seen_at`` frozen is
what lets the Unit-3 staleness probe
(``src/backend/api/services/scraper_health.py``) see a latched company at
all. If a tripped run still refreshed ``last_seen_at`` for the jobs it did
return, a frozen company would look freshly-scraped and the daily alert
would go green on it.

See the constant block below for the calibration and the bounded
auto-release that keeps a *permanent* board shrink from latching forever.
"""

import logging
import os
import uuid
from typing import Any, Dict, List, Literal, NamedTuple, Optional, Set, Tuple

from .models import JobListing, ScrapeRun
from . import database as db
from .batch_writer import BatchWriter
from .utils import get_iso_timestamp

logger = logging.getLogger(__name__)

# Closed set of safety-guard reason codes. A Literal rather than a bare
# ``str`` so mypy rejects a typo'd or invented reason at the call site —
# these strings are persisted to ``scrape_runs.guard_reason`` AND compared
# for equality by the release counter, so a silent typo would disable the
# auto-release rather than fail loudly.
GuardReason = Literal["empty_scrape", "partial_scrape"]

# Threshold for marking jobs as closed (number of consecutive misses)
MISSED_RUN_THRESHOLD = 2

# Miss threshold applied ONLY on a run let through by the bounded
# auto-release. One higher than the normal threshold, which is what makes
# "a single released run cannot close anything" a provable statement
# instead of a hopeful one — see the long note in the constant block below.
RELEASED_RUN_MISS_THRESHOLD = MISSED_RUN_THRESHOLD + 1

# Safety guard rule (a) — "empty scrape". If scraped jobs fall below this
# ratio of active DB jobs, skip update/close phases. Catches full failures
# (0 jobs) and catastrophic partial failures. With 0.1, a company with 5000
# active jobs must return at least 500 to proceed.
#
# Kept at 0.1 deliberately. It is NOT the primary guard any more (rule (b)
# below subsumes it numerically), but it survives as the distinct
# "empty_scrape" reason code so operators can tell a total scraper outage
# apart from a partial truncation in logs and in scrape_runs.
SAFETY_GUARD_RATIO = 0.1

# Safety guard rule (b) — "partial scrape", plus the bounded auto-release.
#
# Read HERE, in this module, so the scraper subprocess
# (scripts/run_scraper.py) and the backend Procrastinate worker
# (src/backend/api/tasks/fetch_*_company.py) share ONE source of truth.
#
# Calibration (empirical, do NOT retune without re-running the numbers).
# Two passes agree:
#   * 3-week window (134,777 successful runs, 129 companies, 2026-07-07 ->
#     07-28): the pair `jobs_seen < 0.85 * active AND
#     (active - jobs_seen) >= 15` trips exactly 7 times, and all 7 are the
#     real Apple truncations. Zero false positives.
#   * Full history (455,317 runs, 2026-01-04 -> 07-29): 33 trips total —
#     27 apple, 6 google, and ZERO for the other 128 companies.
#
# 0.85 is the knee: it is the last threshold at which no company other than
# apple/google trips at all. The tightest REAL truncation in the full
# history is apple 3111/3798 on 2026-05-14 = 0.8191, so the working margin
# is 3.1 points, not the ~4.5 an "0.805 worst case" reading suggests. 0.80
# is unusable: 0.80 * 3565 = 2852 < 2859, i.e. it misses a real Apple
# truncation outright.
#
# Microsoft is the instructive non-trip. Its board ratio reaches 0.616 over
# 30 days and sits below 0.85 in 72 of 115 windows — yet it never trips,
# because `active_count` tracks the shrink down with a ~2-run lag, so no
# SINGLE run ever presents a >15% drop. The guard measures per-run deltas,
# not multi-day drift. That is the whole reason it can be this tight.
#
# The two conditions are ANDed on purpose:
#   * the ratio alone would fire constantly on small boards (a 30-job board
#     dropping to 22 is 73% — noise, not a truncation);
#   * the absolute drop alone would fire on large healthy boards.
#
# Why this matters: the OLD 0.1-only guard let SIX of those seven Apple
# truncations run the destructive close phase against partial data. Closure
# needs MISSED_RUN_THRESHOLD (2) *consecutive* misses, and prod was saved
# only because a clean run happened to land between two truncations. Two
# back-to-back truncations would have mass-closed ~2,800 Apple jobs.
#
# BOUNDED AUTO-RELEASE (SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS)
# ---------------------------------------------------------
# Rule (b) alone cannot tell a *transient* truncation (scraper crashed
# mid-pagination; the next run is fine) from a *permanent* board shrink (a
# company really did cut 25% of its reqs). Both look identical on any
# single run. Without a release, the permanent case latches FOREVER: the
# stale OPEN rows keep `active_count` high, so every subsequent run trips,
# and the company is frozen out of ingestion and lifecycle entirely.
#
# That is not a rare corner. Measured on prod, the probability that a
# company's first recovered run latches (i.e. its board legitimately
# shrank while the scraper was down) is 0.9% at 7 days dead, 4.3% at 14,
# 10.8% at 30 and 18.5% at 56. It also interacts perversely with Unit 3:
# the daily stale-scraper alert exists to get a human to repair a dead
# scraper, and on the very first repaired run this guard would have had a
# ~10-18% chance of instantly re-latching it — looking, to the alert,
# exactly like "still broken". `appliedintuition` (228 open, 56d dead) and
# `unity3d` (173 open, 28d) are live instances of that shape today.
#
# Resolution: repetition is the signal that separates the two cases. A
# transient truncation is followed by a healthy run; a permanent shrink
# returns the SAME reduced number over and over. So after
# SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS consecutive `partial_scrape` trips
# for the same company, we let ONE run through — and that released run
# closes jobs using a STRICTER miss threshold
# (RELEASED_RUN_MISS_THRESHOLD, see below).
#
# Rule (a) is NEVER released, and — critically — rule (a) skips do not
# even COUNT toward the release. The streak is counted on
# ``scrape_runs.guard_reason = 'partial_scrape'``, not on the
# ``skipped_update`` boolean, which BOTH rules set. Counting the boolean
# meant a total outage (0, 0, 0) followed by one truncated run released
# that run immediately — precisely the repaired-dead-scraper case
# (appliedintuition / unity3d) the release exists to protect, firing with
# zero repetition evidence behind it.
#
# WHAT A RELEASED RUN CAN AND CANNOT CLOSE — the real bound
# ---------------------------------------------------------
# An earlier version of this comment claimed a released run "can NEVER
# close a job by itself". That was FALSE, and the falsifying case is not
# exotic: ``consecutive_misses`` PERSISTS across guard trips (a tripped
# run is a total no-op on ``job_listings``), so any job already sitting at
# ``misses >= MISSED_RUN_THRESHOLD - 1`` from some earlier healthy run was
# closed outright by the first released run. On a 1000-job board where one
# sub-threshold hiccup (870/1000 — correctly not a trip) left 130 jobs at
# misses=1, the release then closed all 130 live jobs.
#
# Fix: a released run closes at RELEASED_RUN_MISS_THRESHOLD
# (= MISSED_RUN_THRESHOLD + 1) instead of MISSED_RUN_THRESHOLD. That makes
# the invariant TRUE and provable rather than hopeful:
#
#   A healthy run closes any job that reaches MISSED_RUN_THRESHOLD, so a
#   job that is still OPEN when a freeze begins can carry at most
#   MISSED_RUN_THRESHOLD - 1 misses. One released run adds exactly 1,
#   reaching at most MISSED_RUN_THRESHOLD — strictly below the released
#   run's own threshold. Therefore a single released run cannot close
#   anything; closure needs TWO released runs, i.e. two independent
#   N-truncation streaks.
#
# The one gap, stated honestly rather than hidden: a row that is somehow
# already at misses >= MISSED_RUN_THRESHOLD while still OPEN (legacy data,
# or a close that was interrupted between increment and mark_jobs_closed)
# is NOT protected by that argument and can be closed by the first
# released run. ``_UPSERT_ON_CONFLICT`` reactivates such a row on the next
# healthy scrape, so the failure mode is self-healing churn, not
# permanent loss — but it is real, and ``test_released_run_can_close_an_
# anomalous_row`` pins it so nobody rediscovers it as a surprise.
#
# Reconciling a genuine permanent shrink therefore takes three release
# cycles (~3 * (N + 1) runs). Slow on purpose.
SCRAPER_GUARD_DEFAULTS: Dict[str, float] = {
    "SCRAPER_GUARD_MIN_RATIO": 0.85,
    "SCRAPER_GUARD_MIN_ABS_DROP": 15,
    "SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS": 3,
}


def _guard_env(name: str, lo: float, hi: float, *, cast: type) -> Any:
    """Read one guard override from the environment, defensively.

    These env vars are the operator's escape hatch, and the single moment
    someone reaches for them is a live incident at 3am. Two failure modes
    are therefore handled instead of being allowed to propagate:

    * **Unparseable** (``SCRAPER_GUARD_MIN_RATIO=oops``). A bare
      ``float()`` raises ``ValueError`` at MODULE IMPORT, and every one of
      the six leaf tasks imports this module — so FastAPI would fail to
      start and Railway would crash-loop the whole API over a typo in a
      scraper tuning knob. We log an ERROR and fall back to the default.
    * **Out of range** (``SCRAPER_GUARD_MIN_RATIO=85`` — percent instead
      of ratio, an easy mistake). Unclamped, that would make
      ``jobs_seen < 85 * active`` true for every company on every run and
      freeze all 129 scrapers at once. We clamp into ``[lo, hi]`` and log.

    ERROR (not WARNING) on both paths: see the routing note on the guard
    log line below — Railway derives ``@level`` from the OS stream, and
    stdout WARNINGs do not reach the ``@level:error`` filter operators
    actually watch.
    """
    default = cast(SCRAPER_GUARD_DEFAULTS[name])
    raw = os.environ.get(name)
    if raw is None:
        return default

    try:
        value = cast(raw)
    except (TypeError, ValueError):
        logger.error(
            "%s=%r is not a valid %s — falling back to the calibrated "
            "default %r. Fix the env var; the guard is running UNTUNED.",
            name, raw, cast.__name__, default,
        )
        return default

    # NaN must be caught BEFORE the range check, not by it. ``float("nan")``
    # parses fine, and every comparison against NaN is False — so
    # ``lo <= nan <= hi`` is False (looks out of range) but
    # ``min(max(nan, lo), hi)`` returns NaN right back, and the clamp
    # branch would log "clamping to nan" while changing nothing. NaN in
    # SCRAPER_GUARD_MIN_RATIO then makes ``jobs_seen < nan * active`` False
    # for every company on every run — silently disabling rule (b)
    # fleet-wide, which is the exact failure this whole change exists to
    # prevent, dressed up as a successful clamp.
    if value != value:
        logger.error(
            "%s=%r parsed as NaN — falling back to the calibrated default "
            "%r. A NaN threshold makes every comparison False, which would "
            "silently disable the guard for every company.",
            name, raw, default,
        )
        return default

    if not lo <= value <= hi:
        clamped = cast(min(max(value, lo), hi))
        logger.error(
            "%s=%r is outside the sane range [%s, %s] — clamping to %r. "
            "(A ratio is a fraction, not a percentage: use 0.75, not 75.)",
            name, value, lo, hi, clamped,
        )
        return clamped

    return value


# NOTE: these are bound at import time, so changing the env var requires a
# process RESTART — it is not a live-reload lever. And note the direction:
# to make the guard LESS eager (unfreeze a company) you must LOWER
# SCRAPER_GUARD_MIN_RATIO toward 0.1, not raise it.
SCRAPER_GUARD_MIN_RATIO: float = _guard_env(
    "SCRAPER_GUARD_MIN_RATIO", 0.0, 1.0, cast=float
)
SCRAPER_GUARD_MIN_ABS_DROP: int = _guard_env(
    "SCRAPER_GUARD_MIN_ABS_DROP", 1, 1_000_000, cast=int
)
SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS: int = _guard_env(
    "SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS", 1, 1_000, cast=int
)


def evaluate_safety_guard(
    jobs_seen: int,
    active_count: int,
    consecutive_partial_skips: int = 0,
) -> Optional[GuardReason]:
    """Decide whether a scrape result is too small to trust.

    THE single source of truth for the scraper safety guard. Pure and sync
    so both the scraper subprocess (``run_incremental_scrape`` below) and
    the six backend ATS leaf tasks call the exact same logic — the guard
    used to be copy-pasted inline in seven places and drifted.

    Args:
        jobs_seen: Number of jobs the scrape actually returned.
        active_count: Number of rows currently OPEN in the DB for this
            company/source.
        consecutive_partial_skips: How many runs in a row have ALREADY
            been skipped for this company under ``"partial_scrape"``.
            Callers normally get this from
            ``database.count_consecutive_partial_skips``; ``resolve_
            safety_guard`` does that plumbing. Left at 0 the function is
            the plain stateless rule pair.

    Returns:
        ``None`` when the run looks healthy and the caller should proceed
        with the ingest/update/close phases; otherwise a short
        machine-readable reason string:

        * ``"empty_scrape"``  — rule (a): jobs_seen < SAFETY_GUARD_RATIO
          (10%) of active. A total or near-total scraper failure. Never
          auto-released.
        * ``"partial_scrape"`` — rule (b): jobs_seen < 85% of active AND
          the absolute drop is at least 15 jobs. An Apple-style truncation.
          Auto-released for one run once ``consecutive_partial_skips``
          reaches ``SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS``.

        A cold start (``active_count == 0``) always returns ``None`` — with
        nothing in the DB there is nothing to protect and nothing to close.
    """
    if active_count <= 0:
        return None

    if jobs_seen < SAFETY_GUARD_RATIO * active_count:
        return "empty_scrape"

    if (
        jobs_seen < SCRAPER_GUARD_MIN_RATIO * active_count
        and (active_count - jobs_seen) >= SCRAPER_GUARD_MIN_ABS_DROP
    ):
        if consecutive_partial_skips >= SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS:
            # Bounded auto-release: N identical truncations in a row is a
            # permanent board shrink, not a transient scraper fault. Let
            # this ONE run through so active_count can reconcile. See the
            # constant block for why a single released run can't close
            # anything on its own.
            logger.error(
                "SAFETY GUARD auto-release: %d consecutive partial_scrape "
                "skips (limit %d) — allowing this run to reconcile "
                "(seen=%d active=%d). A permanent board shrink is the only "
                "thing that repeats identically; if this is actually a "
                "persistently broken scraper, fix it — one released run "
                "cannot close jobs by itself, two in a row can.",
                consecutive_partial_skips,
                SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS,
                jobs_seen,
                active_count,
            )
            return None
        return "partial_scrape"

    return None


class GuardDecision(NamedTuple):
    """Outcome of the safety guard for one run.

    ``reason is None`` means "proceed". ``released`` distinguishes the two
    very different ways that can happen — a genuinely healthy run versus a
    run the bounded auto-release let through despite rule (b) firing. The
    caller MUST branch on it: a released run is low-confidence data and
    closes at ``RELEASED_RUN_MISS_THRESHOLD``, not
    ``MISSED_RUN_THRESHOLD``.

    Returning a bare ``str | None`` (as this did originally) made that
    distinction unrepresentable, which is how a released run silently
    inherited the normal threshold and mass-closed 130 live jobs in the
    reviewer's A/B.
    """

    reason: Optional[GuardReason]
    released: bool = False

    @property
    def miss_threshold(self) -> int:
        """Miss threshold this run may close at. Only meaningful when
        ``reason is None``."""
        return RELEASED_RUN_MISS_THRESHOLD if self.released else MISSED_RUN_THRESHOLD


def resolve_safety_guard(
    db_conn,
    company: str,
    jobs_seen: int,
    active_count: int,
) -> GuardDecision:
    """``evaluate_safety_guard`` plus the bounded auto-release lookup.

    This is what all seven call sites use. Sync (async callers wrap it in
    ``asyncio.to_thread``) so the pure rule logic above stays free of I/O
    and trivially unit-testable.

    The ``scrape_runs`` history read happens ONLY when rule (b) would
    otherwise trip, never on the healthy path. That matters: a truncation
    is rare (33 times in 7 months across the whole fleet), so this adds
    zero cost to the ~3,100 healthy scrape runs per day.

    Args:
        db_conn: Database connection (read-only use).
        company: Company id, as written to ``scrape_runs.company``.
        jobs_seen: Number of jobs this scrape returned.
        active_count: Number of currently-OPEN rows for the company.

    Returns:
        A ``GuardDecision``. ``reason`` follows ``evaluate_safety_guard``;
        ``released`` is True only on the run the auto-release let through.
    """
    reason = evaluate_safety_guard(jobs_seen, active_count)
    if reason != "partial_scrape":
        return GuardDecision(reason=reason, released=False)

    prior_skips = db.count_consecutive_partial_skips(
        db_conn, company, limit=SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS
    )
    resolved = evaluate_safety_guard(
        jobs_seen, active_count, consecutive_partial_skips=prior_skips
    )
    # reason flipped from "partial_scrape" to None => this is a release,
    # not a healthy run. Everything downstream keys off that.
    return GuardDecision(reason=resolved, released=resolved is None)


class ScrapeResult:
    """Result object returned by incremental scrape"""

    def __init__(
        self,
        jobs_seen: int = 0,
        new_jobs: int = 0,
        closed_jobs: int = 0,
        details_fetched: int = 0,
        error_count: int = 0,
        run_id: str = None,
        skipped_update: bool = False,
        guard_reason: Optional[GuardReason] = None,
    ):
        self.jobs_seen = jobs_seen
        self.new_jobs = new_jobs
        self.closed_jobs = closed_jobs
        self.details_fetched = details_fetched
        self.error_count = error_count
        self.run_id = run_id or str(uuid.uuid4())
        self.skipped_update = skipped_update
        # Which rule tripped, if any: None | "empty_scrape" | "partial_scrape".
        # Persisted so the release counter can distinguish them — counting the
        # skipped_update boolean (which BOTH rules set) let a total outage
        # release the very next truncated run.
        self.guard_reason = guard_reason


def calculate_job_diff(
    current_ids: Set[str],
    active_known_ids: Set[str]
) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Calculate difference between current scrape and database state

    Args:
        current_ids: Job IDs found in current scrape
        active_known_ids: Job IDs currently marked as OPEN in database

    Returns:
        Tuple of (new_jobs, still_active, missing_jobs)
        - new_jobs: Jobs in current scrape but not in DB
        - still_active: Jobs in both current scrape and DB
        - missing_jobs: Jobs in DB but not in current scrape
    """
    new_jobs = current_ids - active_known_ids
    still_active = current_ids & active_known_ids
    missing_jobs = active_known_ids - current_ids

    logger.info(f"Job diff - New: {len(new_jobs)}, Active: {len(still_active)}, Missing: {len(missing_jobs)}")

    return new_jobs, still_active, missing_jobs


async def process_new_jobs(
    scraper,
    db_conn,
    new_job_cards: List[Dict[str, Any]],
    detail_scrape: bool = True,
    batch_size: int = 50
) -> int:
    """
    Process new jobs: fetch details and insert into database IN BATCHES.

    Jobs are written to the database as they're scraped, not all at the end.
    This provides fault tolerance and reduces memory usage.

    Args:
        scraper: Scraper instance with scrape_job_details_streaming method
        db_conn: Database connection
        new_job_cards: List of job card dicts (basic info from list page)
        detail_scrape: Whether to fetch detail pages
        batch_size: Number of jobs per database batch

    Returns:
        Number of details fetched
    """
    if not new_job_cards:
        return 0

    logger.info(f"Processing {len(new_job_cards)} new jobs (batch_size={batch_size})...")

    timestamp = get_iso_timestamp()
    writer = BatchWriter(
        db_conn=db_conn,
        scraper=scraper,
        batch_size=batch_size,
        detail_scrape=detail_scrape,
        use_upsert=True  # Incremental mode uses upsert
    )

    details_fetched = 0

    if detail_scrape:
        # Use streaming approach - jobs are saved as they're scraped
        async for enriched_job in scraper.scrape_job_details_streaming(new_job_cards):
            writer.add_job(enriched_job, timestamp)
            details_fetched += 1
    else:
        # No detail scrape - just batch insert the cards
        for job_data in new_job_cards:
            writer.add_job(job_data, timestamp)

    # Flush any remaining jobs in buffer
    writer.flush()

    logger.info(
        f"Processed {writer.stats.total_processed} jobs: "
        f"{writer.stats.total_written} written, "
        f"{writer.stats.batches_written} batches, "
        f"{writer.stats.errors} errors"
    )

    return details_fetched


def update_existing_jobs(
    db_conn,
    source_id: str,
    still_active_ids: Set[str],
    missing_ids: Set[str],
    threshold: int = MISSED_RUN_THRESHOLD
) -> int:
    """
    Update existing jobs: reset misses for active, increment for missing, mark closed if threshold reached

    Args:
        db_conn: Database connection
        source_id: Source namespace shared by ``still_active_ids`` and
            ``missing_ids`` (e.g., ``"google_scraper"``). Must be non-empty —
            an empty value would silently no-op every UPDATE in this
            function, mirroring the guard in ``run_incremental_scrape``.
        still_active_ids: Job IDs that are still in search results
        missing_ids: Job IDs that are missing from search results
        threshold: Number of consecutive misses before marking as closed

    Returns:
        Number of jobs marked as closed
    """
    if not source_id:
        raise ValueError(
            "update_existing_jobs requires a non-empty source_id"
        )
    timestamp = get_iso_timestamp()

    # Update last_seen for still active jobs
    if still_active_ids:
        db.update_last_seen(db_conn, source_id, list(still_active_ids), timestamp)

    if not missing_ids:
        return 0

    # Increment consecutive_misses for missing jobs
    db.increment_consecutive_misses(db_conn, source_id, list(missing_ids))

    # Check which jobs have exceeded threshold and mark as closed (single query)
    # Note: consecutive_misses was already incremented above, so we check >= threshold
    jobs_to_close = db.get_jobs_exceeding_miss_threshold(
        db_conn, source_id, list(missing_ids), threshold
    )

    if jobs_to_close:
        db.mark_jobs_closed(db_conn, source_id, list(jobs_to_close), timestamp)
        return len(jobs_to_close)

    return 0


async def run_incremental_scrape(
    scraper,
    db_conn,
    company: str,
    detail_scrape: bool = True,
    source_id: str | None = None,
) -> ScrapeResult:
    """
    Run the 5-phase incremental scraping algorithm

    Args:
        scraper: Scraper instance (must have scrape_all_queries and scrape_job_details_streaming methods)
        db_conn: Database connection
        company: Company name (e.g., "google", "apple")
        detail_scrape: Whether to fetch detail pages for new jobs
        source_id: Source namespace for composite-PK lookups. If None,
            derived from ``scraper.SOURCE_ID``. Required either way;
            raises if neither path resolves.

    Returns:
        ScrapeResult with statistics
    """
    if source_id is None:
        source_id = getattr(scraper, "SOURCE_ID", None)
    if not isinstance(source_id, str) or not source_id:
        raise ValueError(
            "run_incremental_scrape requires source_id, either as an explicit "
            "arg or via scraper.SOURCE_ID class attribute"
        )

    logger.info(f"Starting incremental scrape for {company} (source_id={source_id})")

    result = ScrapeResult()
    timestamp = get_iso_timestamp()
    scrape_error = None

    try:
        # Phase 1: Quick list scrape (no details)
        logger.info("Phase 1: Quick list scrape...")
        job_cards = await scraper.scrape_all_queries()
        result.jobs_seen = len(job_cards)
        logger.info(f"Found {result.jobs_seen} jobs in search results")

        # Extract current job IDs
        current_ids = {job['id'] for job in job_cards}

        # Phase 2: Compare against database
        logger.info("Phase 2: Comparing against database...")
        active_known_ids = db.get_active_job_ids(db_conn, source_id, company)
        new_ids, still_active_ids, missing_ids = calculate_job_diff(current_ids, active_known_ids)

        # Safety guard: skip update/close phases if the scraper returned
        # suspiciously few jobs relative to the active DB count. Catches full
        # failures (0 jobs) and Apple-style truncations (crash after page N).
        # Logic lives in evaluate_safety_guard so this module and the six
        # backend ATS leaf tasks can never drift apart.
        decision = resolve_safety_guard(
            db_conn, company, result.jobs_seen, len(active_known_ids)
        )
        guard_reason = decision.reason
        result.guard_reason = guard_reason
        if guard_reason is not None:
            # ERROR (not WARNING) so Railway routes this to stderr — the
            # platform's @level field is derived from the OS stream (see
            # _configure_logging in main.py, which caps the stdout handler
            # below ERROR). This is the SAME routing requirement the six ATS
            # leaf tasks have always honored. It was a WARNING here, which
            # meant the 126 ATS companies surfaced under @level:error and
            # google/apple/microsoft — the script-scraped companies, i.e.
            # the exact ones this change exists for — silently did not.
            logger.error(
                "SAFETY GUARD (%s) for %s: scraper returned %d jobs but %d active "
                "jobs in database (empty<%.0f%%, partial<%.0f%% with drop>=%d). "
                "Skipping ingest/update/close phases to prevent mass closure. "
                "Investigate scraper health.",
                guard_reason, company, result.jobs_seen, len(active_known_ids),
                SAFETY_GUARD_RATIO * 100, SCRAPER_GUARD_MIN_RATIO * 100,
                SCRAPER_GUARD_MIN_ABS_DROP,
            )
            result.skipped_update = True
            # error_count=1 harmonizes with the six ATS leaf tasks, which
            # have always recorded a tripped guard as an error. Without it a
            # truncated run is written to scrape_runs as error_count=0 —
            # literally indistinguishable from a perfect run.
            result.error_count = 1
        else:
            # Phase 3: Fetch details ONLY for new jobs
            logger.info("Phase 3: Fetching details for new jobs...")
            new_job_cards = [job for job in job_cards if job['id'] in new_ids]
            result.details_fetched = await process_new_jobs(
                scraper, db_conn, new_job_cards, detail_scrape
            )
            result.new_jobs = len(new_ids)

            # Phase 4 & 5: Update existing jobs and mark closed.
            #
            # decision.miss_threshold — NOT the bare MISSED_RUN_THRESHOLD.
            # On a run the auto-release let through it is one higher, which
            # is what makes "a single released run cannot close anything" a
            # provable statement. Passing the normal threshold here is
            # exactly the bug that closed 130 live jobs in review.
            logger.info(
                "Phase 4 & 5: Updating job status (miss threshold %d%s)...",
                decision.miss_threshold,
                ", AUTO-RELEASED run" if decision.released else "",
            )
            result.closed_jobs = update_existing_jobs(
                db_conn, source_id, still_active_ids, missing_ids,
                threshold=decision.miss_threshold,
            )
            if decision.released:
                # Whatever a released run does close, a human should see.
                # ERROR for the same stderr/@level:error routing reason as
                # the guard log itself.
                logger.error(
                    "AUTO-RELEASED run for %s closed %d job(s) at threshold %d "
                    "(seen=%d active=%d). If this scraper is broken rather "
                    "than its board genuinely smaller, fix it — these rows "
                    "reactivate on the next healthy scrape.",
                    company, result.closed_jobs, decision.miss_threshold,
                    result.jobs_seen, len(active_known_ids),
                )

    except Exception as e:
        logger.error(f"Incremental scrape failed for {company}: {e}")
        result.error_count += 1
        scrape_error = e
    finally:
        # ALWAYS record scrape run - even on timeout/kill (defense in depth)
        run_record = ScrapeRun(
            run_id=result.run_id,
            company=company,
            started_at=timestamp,
            completed_at=get_iso_timestamp(),
            mode="incremental",
            jobs_seen=result.jobs_seen,
            new_jobs=result.new_jobs,
            closed_jobs=result.closed_jobs,
            details_fetched=result.details_fetched,
            error_count=result.error_count,
            skipped_update=result.skipped_update,
            guard_reason=result.guard_reason,
        )
        try:
            db.record_scrape_run(db_conn, run_record)
        except Exception as db_err:
            logger.error(f"Failed to record scrape run: {db_err}")

    if scrape_error:
        logger.info(
            f"Incremental scrape failed - "
            f"Seen: {result.jobs_seen}, New: {result.new_jobs}, "
            f"Errors: {result.error_count}"
        )
        raise scrape_error

    logger.info(
        f"Incremental scrape complete - "
        f"Seen: {result.jobs_seen}, New: {result.new_jobs}, "
        f"Closed: {result.closed_jobs}, Details: {result.details_fetched}"
        f"{', SKIPPED UPDATE (safety guard)' if result.skipped_update else ''}"
    )

    return result
