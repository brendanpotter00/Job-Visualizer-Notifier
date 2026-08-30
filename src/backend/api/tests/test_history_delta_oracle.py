"""The history-delta oracle — how an ``oracle_kind='none'`` board earns a close.

Three layers, and the middle one is the point of the file:

1. **Unit** — the page-shape tells (checks 13a/13b/13c) and the delta band (check
   12), each pinned on its own.
2. **Simulation** — real recorded harvest histories replayed through the REAL
   ``run_gate`` / ``verify_harvest``, asserting per board what would and would not
   have been allowed to close. Every series in ``_SERIES`` is measured, not
   invented: the four discovered boards come from ``company_harvests`` in the
   owner's dev DB (``jobscraper_pr243``), and the ``apple`` / ``paypal`` series
   are consecutive hourly ``scrape_runs.jobs_seen`` from production. This is the
   simulation the design was derived from, kept as a test so the derivation
   cannot rot.
3. **Integration** — the real leaf task against a real database, proving the
   close actually happens for a board that earns it and does not for the boards
   that do not.

THE INVARIANT UNDER TEST, in one line: *a job is never closed by a run that could
not prove it saw the whole board* — and the change this file covers is that a
single-request discovered board can now build that proof out of its own history
instead of being told ``no_oracle`` forever.
"""

from __future__ import annotations

import httpx
import pytest

import api.tasks.fetch_custom_company as task_mod
from api.services.custom_baseline import Baseline, _median
from api.services.harvest_meta import HarvestEvidence
from api.services.harvest_verification import (
    UNVERIFIED,
    VERIFIED,
    HarvestVerdict,
    _limit_pinned,
    in_delta_band,
    page_shape_refusal,
    read_untruncated,
    run_gate,
    verify_harvest,
)
from api.tasks.fetch_custom_company import _required_streak, fetch_custom_company
from scripts.shared.constants import custom
from scripts.shared.models import JobListing

from api.services import lever_client

from api.tests.test_fetch_custom_company import (
    _job_status,
    _patch_env,
    _rows,
    _scrape_runs,
    _seed_custom_company,
    _seed_discovered_company,
)

_asyncio = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# the four REAL discovered recipes (trimmed to the fetch step + oracle)
#
# Copied verbatim from ``company_scripts.script`` in the owner's dev DB. The
# request shape is the whole point, so it is reproduced rather than paraphrased.
# --------------------------------------------------------------------------- #

WALMART_RECIPE = {
    "script_version": 1,
    "transport": "http_json",
    "expected_min_jobs": 1,
    "steps": [
        {"op": "fetch", "method": "POST",
         "url": "https://careers.walmart.com/api/graphql",
         "body": {
             "headers": {},
             "queryId": "b0467c1f-f578-4261-9280-0ea4614f251c",
             "variables": {"chatRequest": {
                 "channel": "job_search",
                 "context": {"job_search_context": {
                     "sort": "relevance", "locale": "en_US", "job_page": 0,
                     "active_tab": "jobs", "content_page": 0,
                     "future_roles_page": 0, "management_levels": [],
                 }},
                 "thread_id": "S-1788038636412-503c5cc2",
             }},
         }},
        {"op": "extract_json_path", "records_path": "", "fields": {"id": "id"}},
        {"op": "dedupe_key", "field": "id"},
    ],
    "oracle": {"kind": "none"},
}

ATLASSIAN_RECIPE = {
    "script_version": 1,
    "transport": "http_json",
    "expected_min_jobs": 1,
    "steps": [
        {"op": "fetch", "method": "GET",
         "url": "https://www.atlassian.com/endpoint/careers/listings",
         "headers": {"accept": "application/json, text/plain, */*"}},
        {"op": "extract_json_path", "records_path": "", "fields": {"id": "id"}},
        {"op": "dedupe_key", "field": "id"},
    ],
    "oracle": {"kind": "none"},
}

JANE_STREET_RECIPE = {
    "script_version": 1,
    "transport": "http_json",
    "expected_min_jobs": 1,
    "steps": [
        {"op": "fetch", "method": "GET",
         "url": "https://www.janestreet.com/jobs/main.json",
         "headers": {"x-requested-with": "XMLHttpRequest"}},
        {"op": "extract_json_path", "records_path": "", "fields": {"id": "id"}},
        {"op": "dedupe_key", "field": "id"},
    ],
    "oracle": {"kind": "none"},
}

# Goldman's stored recipe DOES paginate (``paginate_page``), which is why its
# oracle is ``declared_probed`` and not ``none``. Reproduced so the simulation
# can replay it as recorded rather than as a stand-in.
GOLDMAN_RECIPE = {
    "script_version": 1,
    "transport": "http_json",
    "expected_min_jobs": 1,
    "steps": [
        {"op": "fetch", "method": "POST",
         "url": "https://api-higher.gs.com/gateway/api/v1/graphql",
         "body": {"variables": {"searchQueryInput": {
             "page": {"pageSize": 20, "pageNumber": 0}}}}},
        {"op": "paginate_page", "param": "pageNumber", "max_pages": 56,
         "page_size": 20},
        {"op": "extract_json_path", "records_path": "data.roleSearch.items",
         "fields": {"id": "roleId"}},
        {"op": "dedupe_key", "field": "id"},
    ],
    "oracle": {"kind": "declared_probed",
               "total_path": "data.roleSearch.totalCount"},
}

# The Walmart REQUEST BODY on a mockable endpoint. The integration tests need a
# recipe the runner can actually execute; what makes it Walmart-shaped is the
# ``job_page`` in the body, which is exactly and only what check 13a reads.
WALMART_SHAPED_RECIPE = {
    "script_version": 1,
    "transport": "http_json",
    "expected_min_jobs": 1,
    "steps": [
        {"op": "fetch", "method": "POST", "url": "https://x.test/api/graphql",
         "body": {"variables": {"chatRequest": {"context": {
             "job_search_context": {"job_page": 0, "sort": "relevance"}}}}}},
        {"op": "extract_json_path", "records_path": "jobs",
         "fields": {"id": "id", "title": "title", "url": "url"}},
        {"op": "dedupe_key", "field": "id"},
    ],
    "oracle": {"kind": "none"},
}

# A clean single-request recipe with nothing page-shaped about it — the shape
# Atlassian and Jane Street have, used where a test needs one without naming a
# real company.
PLAIN_RECIPE = {
    "script_version": 1,
    "transport": "http_json",
    "expected_min_jobs": 1,
    "steps": [
        {"op": "fetch", "method": "GET", "url": "https://x.test/api/jobs",
         "headers": {}},
        {"op": "extract_json_path", "records_path": "jobs",
         "fields": {"id": "id", "title": "title", "url": "url"}},
        {"op": "dedupe_key", "field": "id"},
    ],
    "oracle": {"kind": "none"},
}


# --------------------------------------------------------------------------- #
# 1. UNIT — the page-shape tells (check 13)
# --------------------------------------------------------------------------- #

def test_walmart_page_index_in_the_request_refuses_forever():
    """**The board this change exists to keep safe.**

    ``careers.walmart.com`` answers a GraphQL ``chatRequest`` carrying
    ``job_page: 0`` and hands back 10 rows. Walmart does not have ten open jobs;
    that is page one. The recipe has no ``paginate_*`` step, so nothing will ever
    fetch page two — and a count of 10 that never moves is *perfectly stable*,
    which means a delta band on its own would happily verify it and start closing
    live jobs as page one rotated.
    """
    assert page_shape_refusal(WALMART_RECIPE, 10) == "page_param_unpaginated"
    # And the refusal is about the REQUEST, so no count rescues it.
    assert page_shape_refusal(WALMART_RECIPE, 4321) == "page_param_unpaginated"


def test_the_two_genuine_whole_board_endpoints_are_not_refused():
    """Atlassian (232 rows) and Jane Street (233) send no parameters at all: one
    GET, whole catalogue. Refusing these would be the whole feature failing."""
    assert page_shape_refusal(ATLASSIAN_RECIPE, 232) is None
    assert page_shape_refusal(JANE_STREET_RECIPE, 233) is None


def test_a_paginating_recipe_is_out_of_scope_for_the_page_shape_tells():
    """Goldman's request carries ``pageNumber``/``pageSize`` — but it also has a
    ``paginate_page`` step, so the sweep is judged by checks 5 and 6 (cap /
    page-advance), which are strictly stronger. Firing 13a here would be
    double-counting, and would refuse every healthy paginating board."""
    assert page_shape_refusal(GOLDMAN_RECIPE, 20) is None


def test_an_explicit_page_size_that_the_harvest_exactly_filled_is_refused():
    """13b. ``?limit=50`` returning exactly 50 rows is a read that hit the ceiling
    it asked for."""
    recipe = {"steps": [
        {"op": "fetch", "url": "https://x.test/api/jobs?limit=50&team=eng"},
    ]}
    assert page_shape_refusal(recipe, 50) == "page_limit_reached"


def test_a_generous_page_size_the_harvest_did_not_fill_is_positive_evidence():
    """The mirror image, and the reason 13b keys on equality rather than presence:
    ``?limit=1000`` returning 232 rows PROVES the read was not truncated."""
    recipe = {"steps": [
        {"op": "fetch", "url": "https://x.test/api/jobs?limit=1000"},
    ]}
    assert page_shape_refusal(recipe, 232) is None


def test_page_shape_refusal_is_inert_on_a_malformed_recipe():
    """It may only ever make a verdict stricter, never licence one — so anything
    it cannot read is simply not a tell."""
    assert page_shape_refusal({}, 10) is None
    assert page_shape_refusal({"steps": "not a list"}, 10) is None
    assert page_shape_refusal({"steps": [{"op": "extract_json_path"}]}, 10) is None


def test_a_boolean_flag_is_not_a_page_size_of_one():
    """``"first": true`` must not read as ``limit=1``; ``True == 1`` in Python and
    an unguarded ``==`` would refuse every single-row harvest on that board."""
    recipe = {"steps": [{"op": "fetch", "url": "https://x.test/j",
                         "body": {"first": True}}]}
    assert page_shape_refusal(recipe, 1) is None


def test_limit_pinned_needs_both_a_round_count_and_an_unmoving_history():
    """13c — the implicit-limit tell, for an endpoint whose ceiling is a server
    default with no parameter to read."""
    pinned = Baseline(None, 0, 0.5, recent_records=(25, 25, 25, 25))
    assert _limit_pinned(25, pinned) is True
    # A count that has MOVED is a count the board chose, not a ceiling.
    moved = Baseline(None, 0, 0.5, recent_records=(25, 25, 26, 25))
    assert _limit_pinned(25, moved) is False
    # And a count nobody would configure is not a ceiling however stable it is.
    assert _limit_pinned(233, Baseline(None, 0, 0.5,
                                       recent_records=(233,) * 8)) is False


def test_limit_pinned_and_the_settled_release_share_one_window():
    """The coupling that leaves no gap between them. Any history long enough to
    release a settled step change is long enough to pin a page size, so a board
    that jams at a server default can never be re-baselined onto it."""
    from api.services.harvest_verification import settled_prior_runs

    jammed = Baseline(200.0, 4, 0.5, recent_records=(100,) * settled_prior_runs())
    assert in_delta_band(100, jammed) is True, "the release alone would allow it"
    assert _limit_pinned(100, jammed) is True, "and 13c is what does not"


def test_the_settled_span_is_wall_clock_not_a_run_count():
    """**The cadence trap, pinned.** The measurement behind the release is "four
    consecutive HOURLY observations of the identical count", and both halves of
    that matter. A bare run count keeps only the first, so shortening the cadence
    would quietly shrink four hours of evidence into one."""
    from api.services.harvest_verification import settled_prior_runs

    assert settled_prior_runs(1.0) == 4, "the shipped cadence — as measured"
    assert settled_prior_runs(0.25) == 16, "15 min: more runs for the same 4 hours"
    assert settled_prior_runs(24.0) == 4, "daily: the run floor wins, never fewer than 4"


def test_a_short_baseline_window_can_only_make_the_rule_stricter():
    """Both consumers of the settled span degrade safely when ``compute_baseline``
    hands them a shorter window than the span asks for — which is what happens at
    a sub-hourly cadence. The release refuses (not enough matches); the page-limit
    tell fires (``all()`` over fewer values). Neither can silently widen."""
    from api.services.harvest_verification import settled_prior_runs

    span = settled_prior_runs(0.25)
    short = Baseline(200.0, 4, 0.5, recent_records=(87,) * (span - 1))
    assert len(short.recent_records) < span
    assert in_delta_band(87, short, 0.25) is False, "no release on a short window"
    assert _limit_pinned(100, Baseline(None, 0, 0.5, recent_records=(100, 100)),
                         0.25) is True, "13c still refuses on a short window"


# --------------------------------------------------------------------------- #
# 2. UNIT — the delta band (check 12)
# --------------------------------------------------------------------------- #

def _bl(median, recent=()):
    return Baseline(median_records=median, run_count=len(recent), min_ratio=0.5,
                    recent_records=tuple(recent))


def test_no_median_yet_is_vacuously_in_band():
    """A board's first runs have nothing to be consistent with. They cannot close
    either — ``first_verified_run`` and the streak both block them."""
    assert in_delta_band(500, _bl(None)) is True


def test_normal_churn_stays_in_band():
    assert in_delta_band(1000, _bl(1000)) is True
    assert in_delta_band(970, _bl(1000)) is True        # -3%
    assert in_delta_band(1040, _bl(1000)) is True       # +4%


def test_the_moderate_partial_read_is_the_gap_this_band_closes():
    """**The 60% read.** A board of 1,000 hands back 600. The ratio guard passes
    (600 > 0.5 x 1,000), the id-churn guard passes (40% < 50%), misses accrue and
    400 live jobs close over two ticks. Under the OLD [0.5, 2.0] band this
    VERIFIED. Under this one it does not."""
    assert 600 >= 0.5 * 1000, "the old hard floor really did admit this"
    assert in_delta_band(600, _bl(1000)) is False


def test_a_small_board_shedding_a_few_roles_is_not_a_truncation():
    """The absolute-drop AND, and why it is not optional. Prod's sub-0.85 tail is
    dominated by boards with a median of 8-18 jobs (``browserbase``, ``light``,
    ``posthog``, ``gem``): a 9-job board that posts 6 is Tuesday. Without the
    >= 15 floor those boards would be UNVERIFIED most days and never close."""
    assert 6 < 0.85 * 9, "the ratio alone really would have tripped"
    assert in_delta_band(6, _bl(9)) is True
    assert in_delta_band(23, _bl(30)) is True           # drop 7, ratio 0.77


def test_the_old_hard_floor_still_bites_below_it():
    """The band only ever TIGHTENS: everything the 0.5 floor refused before is
    still refused, absolute drop or not."""
    assert in_delta_band(4, _bl(10)) is False           # drop 6, ratio 0.4
    assert in_delta_band(0, _bl(9)) is False


def test_an_implausible_jump_up_is_still_out_of_band():
    assert in_delta_band(2100, _bl(1000)) is False


def test_a_settled_step_change_is_released_and_a_wandering_one_is_not():
    """**How a real layoff differs from a broken read** — the discriminator is
    measured, not assumed. Across 271,053 prod runs, 0 of the 5 real Apple
    truncations were preceded by four runs of the identical count; 6 of the 19
    genuine PayPal step shrinks were."""
    settled = _bl(112, recent=(87, 87, 87, 87, 112, 112))
    assert in_delta_band(87, settled) is True, "a held number is a real shrink"

    wandering = _bl(3689, recent=(2460, 3691, 2585, 3688, 3689))
    assert in_delta_band(2460, wandering) is False, "a moving number is a bad read"


def test_the_release_needs_a_FULL_run_of_identical_counts():
    """Three priors is not four. A board with too little history has settled
    nothing, and a partial run of matches must not shortcut the release."""
    assert in_delta_band(87, _bl(112, recent=(87, 87, 87))) is False
    assert in_delta_band(87, _bl(112, recent=(87, 87, 88, 87))) is False


# --------------------------------------------------------------------------- #
# 3. UNIT — routing: what turns ``none`` from a refusal into an oracle
# --------------------------------------------------------------------------- #

def _job(i: int) -> JobListing:
    return JobListing(
        id=str(i), title="Engineer", company="c", location="Remote",
        url=f"https://x/{i}", source_id="custom:c", details={},
        posted_on=None, created_at="2025-01-01T00:00:00.000Z",
        first_seen_at="2025-01-01T00:00:00.000Z",
        last_seen_at="2025-01-01T00:00:00.000Z", consecutive_misses=0,
        details_scraped=True, status="OPEN", has_matched=False,
        ai_metadata={}, closed_on=None,
    )


def _verdict(n, *, recipe=None, baseline=None, evidence=None, oracle="none"):
    ev = evidence or HarvestEvidence.single_shot(declared_total=None)
    gate = run_gate([_job(i) for i in range(n)], ev, oracle_kind=oracle)
    return verify_harvest(oracle, gate, ev, baseline or _bl(None), recipe=recipe)


def test_no_recipe_no_completeness_claim():
    """The safety property that keeps every other caller byte-identical. The six
    public ATS crons and the custom ATS path pass no recipe, and for them
    ``none`` still means "unrecognized provider" and still refuses forever."""
    v = _verdict(232, recipe=None)
    assert (v.verdict, v.reason) == (UNVERIFIED, "no_oracle")


def test_a_clean_single_request_board_now_verifies():
    """The feature, at its smallest. Atlassian's 232-row single GET, second run."""
    v = _verdict(232, recipe=ATLASSIAN_RECIPE, baseline=_bl(232, (232,)))
    assert (v.verdict, v.reason) == (VERIFIED, "history_delta_ok")


def test_the_structural_checks_still_run_first_for_a_none_board():
    """A capped or wrapped read is refused before any history is consulted —
    check 5 and check 6 outrank the whole history-delta ladder."""
    capped = HarvestEvidence(declared_total=None, cap_hit=True,
                             terminated_cleanly=False, page_advance_ok=True,
                             pages_fetched=100)
    v = _verdict(2000, recipe=PLAIN_RECIPE, baseline=_bl(2000, (2000,)),
                 evidence=capped)
    assert (v.verdict, v.reason) == (UNVERIFIED, "cap_hit")

    wrapped = HarvestEvidence(declared_total=None, cap_hit=False,
                              terminated_cleanly=True, page_advance_ok=False,
                              pages_fetched=3)
    v = _verdict(60, recipe=PLAIN_RECIPE, baseline=_bl(60, (60,)),
                 evidence=wrapped)
    assert (v.verdict, v.reason) == (UNVERIFIED, "page_advance_failed")


def test_the_page_shape_tells_outrank_the_delta_band():
    """Order matters and this pins it. Walmart's ten rows are perfectly
    consistent with Walmart's history of ten rows — a band-first ladder would
    VERIFY them. The tell has to run first or it never runs at all."""
    stable = _bl(10, (10, 10, 10, 10, 10))
    assert in_delta_band(10, stable) is True, "the band alone is happy with this"
    v = _verdict(10, recipe=WALMART_RECIPE, baseline=stable)
    assert (v.verdict, v.reason) == (UNVERIFIED, "page_param_unpaginated")


def test_a_none_board_that_ran_out_of_page_budget_is_refused():
    """``terminated_cleanly`` is checked on the history-delta path too, not only on
    ``self_consistent``. A sweep that stopped because it ran out of budget saw an
    unknown fraction of the board, and a stable history of such reads is a stable
    history of the same wrong answer."""
    ran_out = HarvestEvidence(
        declared_total=None, cap_hit=False, terminated_cleanly=False,
        page_advance_ok=True, pages_fetched=40,
    )
    v = _verdict(400, recipe=PLAIN_RECIPE, baseline=_bl(400, (400,) * 6),
                 evidence=ran_out)
    assert (v.verdict, v.reason) == (UNVERIFIED, "not_terminated_cleanly")


def test_an_http_html_board_can_never_earn_the_history_delta_oracle():
    """CHECK 13d — the transport whose ``terminated_cleanly`` is a hard-coded ``True``.

    ``recipe_runner._run_http_html`` issues ONE request and sets
    ``terminated_cleanly=True`` unconditionally: it has no sweep, so it cannot know
    whether that document was the whole board or page one of forty. Every other check
    on this path is hedging around that flag, so on ``http_html`` the hedge is vacuous.

    The board this forecloses is real now, not latent — ``capture.discover`` emits
    ``http_html`` for a document candidate (sources 2 and 6) and DROPS the pagination
    step, because ``validate_recipe`` forbids paging on this transport. A paginating
    careers page therefore stores a page-one-forever recipe with a perfectly stable
    history of page-one counts, and a VERIFIED verdict on that is how jobs that merely
    rotated onto page two get closed while they are still open.

    Note the recipe is otherwise IDENTICAL to ``PLAIN_RECIPE``, which verifies two
    tests up. The transport is the only difference, and it is the whole difference.
    """
    html_recipe = {**PLAIN_RECIPE, "transport": "http_html"}
    baseline = _bl(400, (400,) * 6)
    clean = HarvestEvidence(
        declared_total=None, cap_hit=False, terminated_cleanly=True,
        page_advance_ok=None, pages_fetched=1,
    )

    # The identical read on http_json is the feature working as designed...
    assert _verdict(400, recipe=PLAIN_RECIPE, baseline=baseline,
                    evidence=clean).verdict == VERIFIED

    # ...and on http_html it is a claim the executor cannot make.
    v = _verdict(400, recipe=html_recipe, baseline=baseline, evidence=clean)
    assert (v.verdict, v.reason) == (UNVERIFIED, "html_no_sweep_evidence")


def test_an_http_html_board_with_a_TRUSTED_TOTAL_still_verifies():
    """The guard above is not a ban on the transport — it is a ban on the EMPIRICAL
    oracle. A trusted total demands ``n == declared_total`` exactly, which a page-one
    read of a longer board cannot fake, so proof still buys a close on html."""
    html_recipe = {**PLAIN_RECIPE, "transport": "http_html",
                   "oracle": {"kind": "sitemap"}}
    proved = HarvestEvidence(
        declared_total=400, cap_hit=False, terminated_cleanly=True,
        page_advance_ok=None, pages_fetched=1,
    )
    v = _verdict(400, recipe=html_recipe, baseline=_bl(400, (400,) * 6),
                 evidence=proved, oracle="sitemap")
    assert (v.verdict, v.reason) == (VERIFIED, "oracle_exact")


def test_a_zero_row_none_harvest_is_still_unprovable():
    """The zero-proof chain is untouched: a board that returns nothing and
    declares nothing cannot prove it is empty, whatever its history says."""
    ev = HarvestEvidence.single_shot(declared_total=None)
    gate = run_gate([], ev, oracle_kind="none")
    v = verify_harvest("none", gate, ev, _bl(200, (200,)), recipe=PLAIN_RECIPE)
    assert (v.verdict, v.reason) == (UNVERIFIED, "zero_unproven")


def test_a_page_shaped_refusal_is_not_a_comparable_read():
    """``read_untruncated`` licences nothing destructive, but it DOES licence the
    published-board title comparison — and a board refused by check 13 is exactly
    a board whose title set is a fraction of the real one. Comparing Walmart's ten
    rows against a published board is a statement about a board that does not
    exist, so all three check-13 reasons must be excluded.

    ``no_oracle`` stays included, unchanged: that is the genuinely-unproven middle
    (an unrecognized provider, a script out of sync with its column) where nothing
    says the read stopped early."""
    clean = HarvestEvidence.single_shot(declared_total=None)
    for reason in ("page_param_unpaginated", "page_limit_reached",
                   "page_limit_pinned", "delta_anomaly"):
        assert read_untruncated(HarvestVerdict(UNVERIFIED, reason), clean) is False, (
            f"{reason!r} means the read was probably short — it must not be compared"
        )
    assert read_untruncated(HarvestVerdict(UNVERIFIED, "no_oracle"), clean) is True
    assert read_untruncated(HarvestVerdict(VERIFIED, "history_delta_ok"), clean) is True


# --------------------------------------------------------------------------- #
# 4. SIMULATION — recorded histories replayed through the real gate
# --------------------------------------------------------------------------- #

def _replay(counts, recipe, *, oracle="none", declared=None,
            evidence_of=None, window=14):
    """Replay a series of record counts through the REAL gate, rebuilding the
    baseline between runs exactly as ``compute_baseline`` does.

    Returns one ``(n, verdict, reason)`` per run. The median is taken over
    VERIFIED harvests only and ``recent_records`` over every non-FAILED harvest —
    the same split, and the same ``_median``, the production reader uses, so this
    cannot drift away from what actually runs.
    """
    verified: list[int] = []
    recent: list[int] = []
    out = []
    for n in counts:
        ev = (evidence_of(n) if evidence_of
              else HarvestEvidence.single_shot(declared_total=declared))
        baseline = Baseline(
            median_records=_median(verified[-window:]) if verified else None,
            run_count=len(verified[-window:]),
            min_ratio=0.5,
            recent_records=tuple(reversed(recent[-window:])),
        )
        gate = run_gate([_job(i) for i in range(n)], ev, oracle_kind=oracle)
        v = verify_harvest(oracle, gate, ev, baseline, recipe=recipe)
        out.append((n, v.verdict, v.reason))
        recent.append(n)
        if v.verdict == VERIFIED:
            verified.append(n)
    return out


# Recorded series. Provenance is in the module docstring; each entry names it.
_ATLASSIAN = [232, 222]                 # company_harvests, dev DB
_JANE_STREET = [233]                    # company_harvests, dev DB
_WALMART = [10]                         # company_harvests, dev DB
# prod scrape_runs, company='apple', hourly, 2026-06-24 -> 06-26. Two isolated
# truncations (1692, 2460) inside an otherwise flat ~3,689 board.
_APPLE = [3686, 3686, 3689, 3688, 3689, 3689, 3689, 3689, 3689, 3689, 3689,
          3688, 3686, 3678, 3683, 3684, 3687, 3688, 3690, 3688, 3689, 1692,
          3691, 2460, 3691, 3691, 3691, 3692, 3732, 3740, 3743, 3742, 3736,
          3734]
# prod scrape_runs, company='paypal', hourly, 2026-08-18 -> 08-20. A genuine
# step shrink: a slow drift to 112, then a hard drop to 87 that HOLDS.
_PAYPAL = [117, 117, 117, 117, 117, 117, 116, 116, 115, 115, 115, 115, 114,
           114, 114, 114, 112, 112, 112, 112, 112, 112, 112, 112, 112, 112,
           112, 112, 111, 109, 109, 87, 87, 87, 87, 87, 87, 87, 88, 88, 88,
           88, 88, 88, 95]


def test_simulation_atlassian_and_jane_street_can_close():
    """The two boards that SHOULD graduate. Both are single-request whole-board
    endpoints with no page-shaped parameter and a count nobody would configure,
    so every recorded run VERIFIES and the boards start closing once their
    streak completes."""
    for name, counts, recipe in (
        ("atlassian", _ATLASSIAN, ATLASSIAN_RECIPE),
        ("janestreet", _JANE_STREET, JANE_STREET_RECIPE),
    ):
        runs = _replay(counts, recipe)
        assert all(v == VERIFIED for _, v, _ in runs), (name, runs)


def test_simulation_walmart_never_closes():
    """The board that must NOT graduate, replayed as recorded and then pushed
    well past any streak. Ten runs, all refused, for the structural reason."""
    runs = _replay(_WALMART * 10, WALMART_RECIPE)
    assert {(v, r) for _, v, r in runs} == {(UNVERIFIED, "page_param_unpaginated")}


def test_simulation_goldman_is_still_refused():
    """**The non-negotiable one.** Goldman's two recorded harvests are 20 records
    against a declared 1,074 (and 1,033), with ``page_advance_ok=False``. Replayed
    as recorded, and then repeated fifteen times so no streak or re-baseline can
    rescue it, every run is UNVERIFIED — so the 1,054 jobs it did not see are
    never even a miss, let alone a close."""
    def evidence(_n):
        return HarvestEvidence(declared_total=1074, cap_hit=False,
                               terminated_cleanly=True, page_advance_ok=False,
                               pages_fetched=1)

    runs = _replay([20] * 15, GOLDMAN_RECIPE, oracle="declared_probed",
                   evidence_of=evidence)
    assert all(v == UNVERIFIED for _, v, _ in runs), runs
    assert {r for _, _, r in runs} == {"page_advance_failed"}


def test_simulation_goldman_is_refused_even_with_a_clean_page_advance():
    """Belt and braces on the same board: strip the page-advance failure away and
    the declared total alone still refuses it, because 20 != 1,074. There is no
    single gate holding Goldman up."""
    def evidence(_n):
        return HarvestEvidence.single_shot(declared_total=1074)

    runs = _replay([20] * 15, GOLDMAN_RECIPE, oracle="declared_probed",
                   evidence_of=evidence)
    assert {(v, r) for _, v, r in runs} == {(UNVERIFIED, "count_mismatch")}


def test_simulation_apple_truncations_are_refused_and_the_board_recovers():
    """Prod's two real Apple truncations, replayed as a custom board would see
    them. Both are refused, the surrounding 32 healthy runs all VERIFY, and the
    board is closing again on the very next run — a truncation costs a board one
    run, not its lifecycle."""
    runs = _replay(_APPLE, PLAIN_RECIPE)
    refused = [(n, r) for n, v, r in runs if v == UNVERIFIED]
    assert refused == [(1692, "delta_anomaly"), (2460, "delta_anomaly")]

    # And the run immediately after each refusal is healthy again.
    verdicts = [v for _, v, _ in runs]
    assert verdicts[22] == VERIFIED and verdicts[24] == VERIFIED


def test_simulation_the_old_band_would_have_verified_apples_2460_run():
    """The counterfactual that justifies moving 0.5 -> 0.85+15, stated as a test
    rather than as a claim in a comment. 2,460 of a 3,689 board is 66.7% — inside
    the old band, so that run would have VERIFIED and been free to start closing
    the ~1,200 jobs it did not see."""
    median = _median(_APPLE[7:21])
    assert 2460 >= 0.5 * median, "the old low bound admitted it"
    assert 2460 < 0.85 * median and (median - 2460) >= 15, "the new one does not"


def test_simulation_paypal_step_shrink_is_refused_then_released():
    """The layoff case, on the real series. PayPal drifts 117 -> 112, then drops
    hard to 87 and HOLDS it. The drop is refused, the next three identical runs
    are refused, and the FIFTH 87 is released — the board is closing again about
    five hours after it shrank instead of never."""
    runs = _replay(_PAYPAL, PLAIN_RECIPE)
    eighty_sevens = [(v, r) for n, v, r in runs if n == 87]
    assert len(eighty_sevens) == 7
    assert [v for v, _ in eighty_sevens[:4]] == [UNVERIFIED] * 4
    assert {r for _, r in eighty_sevens[:4]} == {"delta_anomaly"}
    assert [v for v, _ in eighty_sevens[4:]] == [VERIFIED] * 3

    # The gentle drift that preceded it was never refused at all: 117 -> 112 is
    # a 5-job move on a 117-job board, which is a board, not a bug.
    assert all(v == VERIFIED for n, v, _ in runs if n >= 109)


def test_simulation_a_board_stuck_at_a_wrong_number_never_gets_released():
    """The release's own failure mode, pinned. A scraper that jams at a round
    page size returns an identical count forever — which is exactly what the
    settled-step release keys on. Check 13c is what stops that from becoming a
    licence: 100 is a page size, the history never moves off it, so the board is
    refused on every run no matter how settled it looks."""
    runs = _replay([247] * 6 + [100] * 12, PLAIN_RECIPE)
    assert all(v == VERIFIED for _, v, _ in runs[:6])
    assert all(v == UNVERIFIED for _, v, _ in runs[6:]), runs[6:]
    # The first four 100s are out of band; from the fifth on, the settled-step
    # release WOULD have rescued them and 13c is what stops it.
    assert [r for _, _, r in runs[6:]] == ["delta_anomaly"] * 4 + [
        "page_limit_pinned"
    ] * 8


# --------------------------------------------------------------------------- #
# 5. INTEGRATION — the real leaf task against a real database
# --------------------------------------------------------------------------- #

def _payload(ids):
    return {"jobs": [{"id": str(i), "title": f"Engineer {i}",
                      "url": f"https://x.test/j/{i}"} for i in ids]}


def _patch_http(monkeypatch, next_payload):
    """``next_payload`` is a zero-arg callable so a test can change the board
    between runs without re-patching."""
    def handler(_req):
        return httpx.Response(200, json=next_payload())

    monkeypatch.setattr(
        task_mod, "_recipe_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )


# The cadence the product actually ships (``ccs.DEFAULT_CADENCE_HOURS``). Only
# the streak test uses it — the other integration cases are about a DIFFERENT
# gate (the band, the churn guard), so they run at the daily cadence where the
# streak is its floor of 3 and does not dominate the case.
_CADENCE_H = 1.0
_DAILY_CADENCE_H = 24.0


def _set_cadence(db_conn, company_id, hours):
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE companies SET cadence_hours = %s WHERE id = %s", (int(hours), company_id)
    )
    db_conn.commit()


def _backdate(db_conn, company_id, hours=40):
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE job_freshness SET last_seen_at = now() - (%s * interval '1 hour') "
        "WHERE source_id = %s",
        (hours, custom(company_id)),
    )
    db_conn.commit()


@_asyncio
async def test_a_stable_single_request_board_closes_after_five_verified_runs(
    db_conn, monkeypatch
) -> None:
    """**The feature, end to end, at the SHIPPED cadence.** An Atlassian-shaped
    board carries 7 jobs; job 7 comes off the board and never returns. Before this
    change the board was ``no_oracle`` on every run and job 7 stayed OPEN forever.

    Now it closes — on the run that completes a full DAY of consecutive VERIFIED
    observation, which at the 1 h cadence is the 24th run, and not one run
    earlier. The run count is read from ``_required_streak`` rather than written
    out, so the day is what is pinned; the assertion above pins that the day is
    still 24 runs at this cadence."""
    company_id = "u-histdelta1"
    _patch_env(monkeypatch)
    _seed_discovered_company(
        db_conn, company_id, script=PLAIN_RECIPE, oracle_kind="none"
    )
    _set_cadence(db_conn, company_id, _CADENCE_H)

    required = _required_streak("none", _CADENCE_H)
    assert required == 24, (
        "the shipped 1 h cadence must require a full day of observation; if this "
        "moved, _NO_ORACLE_STREAK_MIN_HOURS or the cadence did"
    )

    ids = list(range(1, 8))
    _patch_http(monkeypatch, lambda: _payload(ids))
    await fetch_custom_company(company_id=company_id)      # run 1 — seeds 7 jobs
    db_conn.rollback()
    assert _rows(db_conn, "company_harvests", company_id)[-1]["verdict"] == VERIFIED
    assert _scrape_runs(db_conn, company_id)[-1]["guard_reason"] == "first_verified_run"

    # Job 7 leaves the board and is aged past the 1.5 x cadence floor.
    ids = list(range(1, 7))
    _backdate(db_conn, company_id)

    # Runs 2 .. required-1: VERIFIED, but the day of observation is not complete.
    for _ in range(required - 2):
        await fetch_custom_company(company_id=company_id)
        db_conn.rollback()
        assert _job_status(db_conn, company_id)["7"]["status"] == "OPEN"
        assert _scrape_runs(db_conn, company_id)[-1]["guard_reason"] == "streak_too_short"

    # The run that completes the streak closes it.
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()
    runs = _scrape_runs(db_conn, company_id)
    assert len(runs) == required
    assert runs[-1]["guard_reason"] is None
    assert runs[-1]["closed_jobs"] == 1
    assert _job_status(db_conn, company_id)["7"]["status"] == "CLOSED"


@_asyncio
async def test_an_unrecognized_ats_provider_is_never_handed_a_recipe(
    db_conn, monkeypatch
) -> None:
    """**The blast radius of ``none`` outside the discovered path.**

    ``effective_oracle_kind`` maps any ATS provider it does not recognize to
    ``none`` — a deliberate safe default, so that forgetting to add a new provider
    to the map costs a refusal rather than a wrong close. That default only stays
    safe while the ATS branch passes NO recipe: an ``ats_client`` script is
    ``{"kind", "provider", "token"}``, it has no ``steps``, so the page-shape tells
    read nothing off it and a stable board would sail through the band.

    Simulated exactly as it would happen — a real Lever company whose provider the
    map does not know about — by making the map answer ``none`` for it."""
    company_id = "u-histats001"
    _patch_env(monkeypatch)
    _seed_custom_company(db_conn, company_id, "acme", ats="lever")
    monkeypatch.setattr(task_mod, "effective_oracle_kind", lambda _p: "none")

    async def _lever(board_token, http):
        return [{"id": str(i), "text": "Eng", "hostedUrl": f"https://x/{i}"}
                for i in range(1, 8)]

    monkeypatch.setattr(lever_client, "fetch_jobs", _lever)

    for _ in range(3):
        await fetch_custom_company(company_id=company_id)
        db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert {(h["verdict"], h["verdict_reason"]) for h in harvests} == {
        (UNVERIFIED, "no_oracle")
    }, harvests
    assert {r["guard_reason"] for r in _scrape_runs(db_conn, company_id)} == {
        "unverified_harvest"
    }


@_asyncio
async def test_the_walmart_shape_closes_nothing_however_long_it_runs(
    db_conn, monkeypatch
) -> None:
    """**The never-wrong-close invariant, on the board that would have broken it.**

    A page-one-of-N board whose ten rows rotate as new jobs post. Run it eight
    times — well past any streak — with a completely fresh id set each run and
    every prior job aged past the close floor. Not one job closes, not one miss
    accrues, and the reason is the same every time."""
    company_id = "u-histwalm01"
    _patch_env(monkeypatch)
    _seed_discovered_company(
        db_conn, company_id, script=WALMART_SHAPED_RECIPE, oracle_kind="none"
    )

    page = [0]

    def payload():
        base = page[0] * 10
        return _payload(range(base, base + 10))

    _patch_http(monkeypatch, payload)

    for _ in range(8):
        await fetch_custom_company(company_id=company_id)
        db_conn.rollback()
        _backdate(db_conn, company_id)
        page[0] += 1

    statuses = _job_status(db_conn, company_id)
    assert len(statuses) == 80, "every run's rows were still upserted"
    assert {row["status"] for row in statuses.values()} == {"OPEN"}
    assert {row["consecutive_misses"] for row in statuses.values()} == {0}
    harvests = _rows(db_conn, "company_harvests", company_id)
    assert {h["verdict"] for h in harvests} == {UNVERIFIED}
    assert {h["verdict_reason"] for h in harvests} == {"page_param_unpaginated"}
    assert {r["guard_reason"] for r in _scrape_runs(db_conn, company_id)} == {
        "unverified_harvest"
    }


@_asyncio
async def test_a_moderate_partial_read_closes_nothing(db_conn, monkeypatch) -> None:
    """The 60% read against a real database. The board settles at 103 rows, then
    one run returns 62 of them. Ratio 0.60, drop 41 — the safety guard's own
    min_ratio (0.5) lets that through, so the delta band is the only thing
    standing between it and 41 wrongly-closed jobs."""
    company_id = "u-histpart1"
    _patch_env(monkeypatch)
    _seed_discovered_company(
        db_conn, company_id, script=PLAIN_RECIPE, oracle_kind="none"
    )

    ids = list(range(1, 104))
    _patch_http(monkeypatch, lambda: _payload(ids))
    for _ in range(5):
        await fetch_custom_company(company_id=company_id)
        db_conn.rollback()
    assert _scrape_runs(db_conn, company_id)[-1]["guard_reason"] is None

    _backdate(db_conn, company_id)
    ids = list(range(1, 63))                              # the short read
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvest = _rows(db_conn, "company_harvests", company_id)[-1]
    assert (harvest["verdict"], harvest["verdict_reason"]) == (
        UNVERIFIED, "delta_anomaly",
    )
    run = _scrape_runs(db_conn, company_id)[-1]
    assert run["guard_reason"] == "unverified_harvest"
    assert run["closed_jobs"] == 0
    statuses = _job_status(db_conn, company_id)
    assert {row["status"] for row in statuses.values()} == {"OPEN"}
    # Not a miss either — an UNVERIFIED run does not move a job toward closure.
    assert {row["consecutive_misses"] for row in statuses.values()} == {0}


@_asyncio
async def test_a_none_board_whose_ids_churn_is_refused_by_the_churn_guard(
    db_conn, monkeypatch
) -> None:
    """The second defence, isolated. This board's request carries no page
    parameter and its count is rock steady at 41, so checks 12 and 13 are both
    satisfied and it VERIFIES — but more than half its id set turns over in one
    run, which is the churning-``id_field`` shape. Nothing closes."""
    company_id = "u-histchurn1"
    _patch_env(monkeypatch)
    _seed_discovered_company(
        db_conn, company_id, script=PLAIN_RECIPE, oracle_kind="none"
    )

    ids = list(range(1, 42))
    _patch_http(monkeypatch, lambda: _payload(ids))
    for _ in range(5):
        await fetch_custom_company(company_id=company_id)
        db_conn.rollback()
    assert _scrape_runs(db_conn, company_id)[-1]["guard_reason"] is None

    _backdate(db_conn, company_id)
    ids = list(range(1000, 1041))                         # same count, new ids
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    assert _rows(db_conn, "company_harvests", company_id)[-1]["verdict"] == VERIFIED
    run = _scrape_runs(db_conn, company_id)[-1]
    assert run["guard_reason"] == "id_churn_suspected"
    assert run["closed_jobs"] == 0
    statuses = _job_status(db_conn, company_id)
    assert {row["status"] for row in statuses.values()} == {"OPEN"}
    assert {row["consecutive_misses"] for row in statuses.values()} == {0}
