"""AC-15 — the half of verification that REFUSES (PLAN.md §5, AC-04/AC-05's mirror).

AC-04 and AC-05 prove a whole-catalogue board can now verify, and therefore can
now close a filled role. On their own they prove half a design: a rule that
verified everything would pass them both. This case pins the other half — the
boards that must still be refused, and the reason each is refused — so that
"``none`` boards can close now" cannot quietly become "``none`` boards always
close".

Hermetic, like AC-06a: no network, no browser, no LLM. Rows are seeded directly
into the real e2e database and the REAL production functions
(``api.services.custom_baseline`` + ``api.services.harvest_verification``) are
called against them. That is deliberately different from the unit coverage in
``src/backend/api/tests/test_history_delta_oracle.py``, which builds its
``Baseline`` by hand: here the baseline comes out of ``company_harvests`` through
the same SQL the leaf task runs, so the DB-side plumbing — the VERIFIED-only
median, the unfiltered recent-records window — is under test too.

The two shapes, both measured off the owner's dev DB rather than imagined:

* **Goldman** (``higher.gs.com``) — 20 records harvested against a declared
  1,074, ``page_advance_ok=False``. If anything here ever lets that run through,
  1,054 live jobs close.
* **Walmart** (``careers.walmart.com``) — 10 records from a request whose body
  carries ``job_page: 0`` and a recipe with no pagination step. Its count is
  perfectly stable, so a delta band alone would verify it; the request shape is
  the only thing that says otherwise.
"""

from __future__ import annotations

import uuid

# Imported directly — same import root e2e_app.py uses (src/backend on sys.path
# via conftest.py) — so this exercises the REAL gate, not a reimplementation.
from api.services.custom_baseline import compute_baseline  # noqa: E402
from api.services.harvest_meta import HarvestEvidence  # noqa: E402
from api.services.harvest_verification import (  # noqa: E402
    UNVERIFIED,
    VERIFIED,
    GateResult,
    verify_harvest,
)

# The Walmart request body, verbatim from ``company_scripts.script`` for
# ``u-7d9oae7zbl``. ``job_page`` is the whole tell.
WALMART_RECIPE = {
    "script_version": 1,
    "transport": "http_json",
    "expected_min_jobs": 1,
    "steps": [
        {"op": "fetch", "method": "POST",
         "url": "https://careers.walmart.com/api/graphql",
         "body": {"variables": {"chatRequest": {"context": {
             "job_search_context": {"job_page": 0, "sort": "relevance"}}}}}},
        {"op": "extract_json_path", "records_path": "", "fields": {"id": "id"}},
        {"op": "dedupe_key", "field": "id"},
    ],
    "oracle": {"kind": "none"},
}

# Goldman's, verbatim: it DOES paginate, which is why its stored oracle is
# ``declared_probed`` and why the page-shape tells correctly leave it alone.
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


def _seed_company(conn, company_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO companies (id, display_name, ats, board_token, visibility,
                                   enabled, health_state, provider_config)
            VALUES (%s, %s, 'discovered', %s, 'user', false, 'unverified', '{}'::jsonb)
            """,
            (company_id, f"E2E refusal fixture {company_id}", company_id),
        )
    conn.commit()


def _seed_harvests(conn, company_id: str, rows: list[tuple[int, str, str]]) -> None:
    """``rows`` is ``(records_harvested, verdict, oracle_kind)``, oldest first."""
    with conn.cursor() as cur:
        for i, (records, verdict, oracle_kind) in enumerate(rows):
            cur.execute(
                """
                INSERT INTO company_harvests
                  (company_id, run_id, started_at, completed_at, verdict,
                   verdict_reason, records_harvested, oracle_kind)
                VALUES (%s, %s, now() - (%s * interval '1 hour'),
                        now() - (%s * interval '1 hour'), %s, 'fixture', %s, %s)
                """,
                (company_id, f"{company_id}-{i}", len(rows) - i, len(rows) - i,
                 verdict, records, oracle_kind),
            )
    conn.commit()


def _delete_fixture(conn, company_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM company_harvests WHERE company_id = %s", (company_id,))
        cur.execute("DELETE FROM companies WHERE id = %s", (company_id,))
    conn.commit()


def _gate(n: int) -> GateResult:
    """The gate result for an ``n``-row harvest. ``jobs`` is unread by
    ``verify_harvest`` (it works off ``records_harvested``), so it stays empty —
    the alternative is fabricating n JobListings to prove nothing extra."""
    return GateResult(jobs=[], records_harvested=n, id_dedup_dropped=0)


class TestGoldmanIsRefused:
    """**The non-negotiable one.** Goldman's recorded harvest is 20 rows against a
    declared 1,074. Every gate below is asserted independently, because "Goldman
    is refused" must not depend on any single one of them holding."""

    def test_ac15a_goldman_short_read_is_refused_however_long_its_history(self, db_conn):
        company_id = f"u-e2eref{uuid.uuid4().hex[:9]}"
        _seed_company(db_conn, company_id)
        # Fifteen identical 20-row harvests: long enough to satisfy any streak,
        # and settled enough to satisfy the settled-step re-baseline release.
        _seed_harvests(
            db_conn, company_id,
            [(20, "UNVERIFIED", "declared_probed")] * 15,
        )
        try:
            baseline = compute_baseline(db_conn, company_id)
            evidence = HarvestEvidence(
                declared_total=1074, cap_hit=False, terminated_cleanly=True,
                page_advance_ok=False, pages_fetched=1,
            )
            v = verify_harvest(
                "declared_probed", _gate(20), evidence, baseline,
                recipe=GOLDMAN_RECIPE,
            )
            assert (v.verdict, v.reason) == (UNVERIFIED, "page_advance_failed"), (
                f"AC-15a: a Goldman-shaped run (20 of a declared 1,074, pages "
                f"re-serving ids) must never verify — got {v.verdict}/{v.reason}. "
                f"If this goes green the next 1,054 Goldman jobs close."
            )

        finally:
            _delete_fixture(db_conn, company_id)

    def test_ac15b_goldman_is_still_refused_with_a_clean_page_advance(self, db_conn):
        """Belt and braces: take the page-advance failure away and the declared
        total alone still refuses it. No single gate is holding Goldman up."""
        company_id = f"u-e2eref{uuid.uuid4().hex[:9]}"
        _seed_company(db_conn, company_id)
        _seed_harvests(
            db_conn, company_id, [(20, "UNVERIFIED", "declared_probed")] * 15
        )
        try:
            baseline = compute_baseline(db_conn, company_id)
            v = verify_harvest(
                "declared_probed", _gate(20),
                HarvestEvidence.single_shot(declared_total=1074), baseline,
                recipe=GOLDMAN_RECIPE,
            )
            assert (v.verdict, v.reason) == (UNVERIFIED, "count_mismatch")
        finally:
            _delete_fixture(db_conn, company_id)


class TestWalmartIsRefused:
    def test_ac15c_a_page_one_of_n_board_is_refused_on_its_request_shape(self, db_conn):
        """Walmart: ten rows, ten rows, ten rows — a history so consistent that the
        delta band has no objection at all. What refuses it is the ``job_page`` in
        the captured request, which says the board is paginated and this recipe
        reads exactly one page of it."""
        company_id = f"u-e2eref{uuid.uuid4().hex[:9]}"
        _seed_company(db_conn, company_id)
        _seed_harvests(db_conn, company_id, [(10, "VERIFIED", "none")] * 15)
        try:
            baseline = compute_baseline(db_conn, company_id)
            assert baseline.median_records == 10.0, (
                "AC-15c fixture: the seeded VERIFIED history must produce a median, "
                "otherwise the delta band is skipped and the test proves nothing"
            )
            v = verify_harvest(
                "none", _gate(10),
                HarvestEvidence.single_shot(declared_total=None), baseline,
                recipe=WALMART_RECIPE,
            )
            assert (v.verdict, v.reason) == (UNVERIFIED, "page_param_unpaginated"), (
                f"AC-15c: a page-one-of-N board must never verify however stable it "
                f"looks — got {v.verdict}/{v.reason}"
            )
        finally:
            _delete_fixture(db_conn, company_id)


class TestTheRuleIsNotVacuous:
    """The control cases. Without these, AC-15 could pass by refusing everything."""

    def test_ac15d_a_whole_catalogue_board_with_the_same_history_verifies(self, db_conn):
        """The same seeded history, the same call, one difference: a request with
        no page index in it and a count nobody would configure as a limit. This is
        what makes AC-15a/b/c evidence of a RULE rather than of a blanket refusal."""
        company_id = f"u-e2eref{uuid.uuid4().hex[:9]}"
        _seed_company(db_conn, company_id)
        _seed_harvests(db_conn, company_id, [(233, "VERIFIED", "none")] * 15)
        plain = {
            "script_version": 1, "transport": "http_json", "expected_min_jobs": 1,
            "steps": [
                {"op": "fetch", "method": "GET",
                 "url": "https://www.janestreet.com/jobs/main.json"},
                {"op": "extract_json_path", "records_path": "",
                 "fields": {"id": "id"}},
            ],
            "oracle": {"kind": "none"},
        }
        try:
            baseline = compute_baseline(db_conn, company_id)
            v = verify_harvest(
                "none", _gate(233),
                HarvestEvidence.single_shot(declared_total=None), baseline,
                recipe=plain,
            )
            assert (v.verdict, v.reason) == (VERIFIED, "history_delta_ok")
        finally:
            _delete_fixture(db_conn, company_id)

    def test_ac15e_a_moderate_partial_read_of_that_same_board_is_refused(self, db_conn):
        """And the board that verifies at 233 is refused at 140 — the moderate
        partial read, the gap the old [0.5, 2.0] band left open. 140/233 is 0.60:
        past the 0.5 hard floor, so nothing but the tightened band catches it."""
        company_id = f"u-e2eref{uuid.uuid4().hex[:9]}"
        _seed_company(db_conn, company_id)
        _seed_harvests(db_conn, company_id, [(233, "VERIFIED", "none")] * 15)
        plain = {
            "script_version": 1, "transport": "http_json", "expected_min_jobs": 1,
            "steps": [
                {"op": "fetch", "method": "GET",
                 "url": "https://www.janestreet.com/jobs/main.json"},
                {"op": "extract_json_path", "records_path": "",
                 "fields": {"id": "id"}},
            ],
            "oracle": {"kind": "none"},
        }
        try:
            baseline = compute_baseline(db_conn, company_id)
            assert 140 >= 0.5 * baseline.median_records, "the old floor admitted it"
            v = verify_harvest(
                "none", _gate(140),
                HarvestEvidence.single_shot(declared_total=None), baseline,
                recipe=plain,
            )
            assert (v.verdict, v.reason) == (UNVERIFIED, "delta_anomaly")
        finally:
            _delete_fixture(db_conn, company_id)
