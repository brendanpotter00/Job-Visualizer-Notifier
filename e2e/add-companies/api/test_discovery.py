"""AC-04 / AC-05 — one-time discovery, and boards with no posted date
(PLAN.md §5 "AC-04 / AC-05").

Live, not hermetic (PLAN.md §6): real Chromium, real Haiku, real board. Each
case is a genuine ~30-90s round trip through discovery + the first harvest.

Both boards now reach VERIFIED on that first harvest, where they used to sit at
``UNVERIFIED no_oracle`` forever. That is the history-delta oracle working — see
``api/services/harvest_verification.py`` and
``docs/implementations/custom-company-sources/CLOSING-NO-ORACLE-BOARDS.md`` — and
its consequence is that these boards can, from their fifth consecutive VERIFIED
harvest onward, close a job that has left the board. The refusing half of the
same rule is covered by ``test_verification_refusal.py``; a suite that only
proved boards CAN verify would be proving half a design.
"""

from __future__ import annotations

import sys

import boards
import httpx
import pytest
from conftest import db, find_company, poll_until, require_reachable

# The capture package's ``__init__`` re-exports the FUNCTION ``discover``, which shadows
# the submodule of the same name, so the module is reached through ``sys.modules`` — the
# same trick ``src/backend/api/tests/test_recipe_corpus_regression.py`` uses.
import api.services.capture  # noqa: E402,F401  (import order is the point)

_discover = sys.modules["api.services.capture.discover"]

EXPECTED_STEP_KEYS = {"open_page", "find_feed", "verify_read", "ready", "first_scan"}
TERMINAL = {"done", "failed"}

# The same UA the capture browser sends. A job page fetched with httpx's default UA is a
# different request from the one a user makes, and some boards answer it differently.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _first_scan_settled(row: dict) -> bool:
    discovery = row.get("discovery") or {}
    steps = discovery.get("steps") or []
    for step in steps:
        if step["key"] == "first_scan" and step["status"] in TERMINAL:
            return True
    return False


def _run_discovery_case(http, db_conn, board: "boards.Board"):
    require_reachable(board)
    resp = http.post("/api/users/companies", json={"url": board.url})
    assert resp.status_code == 202, (
        f"{board.case_id}: expected 202 discovery_pending for {board.url!r}, "
        f"got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["status"] == "discovery_pending"
    company_id = body["id"]
    assert body["finalUrl"]

    # Assertion 2: a provisional row exists immediately.
    provisional = find_company(http, company_id)
    assert provisional is not None, f"{board.case_id}: no provisional row immediately after 202"
    assert provisional["healthState"] == "discovering"
    row = db.company_row(db_conn, company_id)
    assert row is not None
    assert row["enabled"] is False, f"{board.case_id}: provisional row must be enabled=false"

    # Assertion 3: exactly one custom_discovery job, correctly locked.
    user_id = db.user_id_for_email(db_conn, "e2e+add-companies@jvn.test")
    expected_lock = f"discover:{user_id}:{body['finalUrl']}"
    n_jobs = db.procrastinate_job_count(
        db_conn, queue_name="custom_discovery", queueing_lock=expected_lock
    )
    assert n_jobs == 1, (
        f"{board.case_id}: expected exactly one custom_discovery job under "
        f"queueing_lock={expected_lock!r}, found {n_jobs}"
    )

    settled = poll_until(
        http, company_id, _first_scan_settled, timeout_s=240.0, what="first_scan settled"
    )

    discovery = settled["discovery"]
    assert discovery["outcome"] == "tracking", (
        f"{board.case_id}: expected discovery.outcome='tracking' for a board on the "
        f"validated six-board list; got {discovery['outcome']!r} "
        f"(steps={discovery.get('steps')})"
    )
    # ---- verification: assert the MECHANISM, not the projection ---------------
    #
    # This used to read ``healthState == 'unverified'``, on the grounds that a
    # discovered board is stored ``oracle_kind='none'`` and a ``none`` board could
    # never verify. The second half of that stopped being true: the history-delta
    # oracle lets a board with no declared total and no pagination verify on its
    # own request shape and its own harvest history, which is what lets these two
    # boards ever close a filled role.
    #
    # So the assertion is deliberately NOT the new string. ``healthState`` is a
    # projection of the harvest verdict, and asserting the projection alone would
    # pass whatever the gate decided. What is pinned instead is the reasoning:
    # which oracle ran, what it concluded, and — the load-bearing half — that this
    # first run still reached NOTHING destructive.
    harvest = db.latest_harvest(db_conn, company_id)
    assert harvest is not None, f"{board.case_id}: no company_harvests row after first_scan"
    assert harvest["oracle_kind"] == "none", (
        f"{board.case_id}: a discovered single-request board must still be STORED "
        f"oracle_kind='none' — discovery must not have started claiming a total; "
        f"got {harvest['oracle_kind']!r}"
    )
    assert (harvest["verdict"], harvest["verdict_reason"]) == (
        "VERIFIED", "history_delta_ok",
    ), (
        f"{board.case_id}: expected the history-delta oracle to accept a whole-catalogue "
        f"board — one request, no page-index parameter in it, a record count that is not "
        f"a page-size ceiling — got {harvest['verdict']!r}/{harvest['verdict_reason']!r}. "
        f"A ``no_oracle`` here means the recipe never reached verify_harvest; a "
        f"``page_param_unpaginated`` means the captured request carries a page index and "
        f"this board is NOT whole-catalogue after all."
    )
    assert harvest["cap_hit"] is False and harvest["declared_total"] is None, (
        f"{board.case_id}: a single-request board declares no total and hits no cap; "
        f"got cap_hit={harvest['cap_hit']!r} declared_total={harvest['declared_total']!r}"
    )
    assert settled["healthState"] == "healthy", (
        f"{board.case_id}: healthState is a projection of the harvest verdict — a "
        f"VERIFIED harvest must read 'healthy'; got {settled['healthState']!r}"
    )

    # ...and the first VERIFIED run is still forbidden from closing anything. This
    # is the invariant the string assertion used to protect by accident and now
    # protects on purpose: a board verifying is not a board closing.
    run = db.latest_scrape_run(db_conn, company_id)
    assert run is not None, f"{board.case_id}: no scrape_runs row after first_scan"
    assert run["guard_reason"] == "first_verified_run", (
        f"{board.case_id}: the FIRST verified harvest must be refused the close path by "
        f"the first-run guard; got guard_reason={run['guard_reason']!r}"
    )
    assert run["closed_jobs"] == 0, (
        f"{board.case_id}: a first harvest must close nothing; closed {run['closed_jobs']}"
    )

    step_keys = {s["key"] for s in discovery["steps"]}
    assert step_keys == EXPECTED_STEP_KEYS, (
        f"{board.case_id}: expected exactly the five checklist keys "
        f"{EXPECTED_STEP_KEYS}, got {step_keys}"
    )
    for step in discovery["steps"]:
        assert step["status"] in TERMINAL, (
            f"{board.case_id}: step {step['key']!r} did not reach a terminal state "
            f"(status={step['status']!r})"
        )

    script = db.company_script_row(db_conn, company_id)
    assert script is not None
    assert script["transport"] == "http_json", (
        f"{board.case_id}: expected company_scripts.transport='http_json' for a "
        f"discovered board, got {script['transport']!r}"
    )

    assert settled["openJobCount"] > 0, (
        f"{board.case_id}: expected open_job_count > 0 after the first harvest, got 0"
    )
    if board.approx_job_count:
        lo, hi = board.approx_job_count * 0.4, board.approx_job_count * 2.5
        if not (lo <= settled["openJobCount"] <= hi):
            print(
                f"{board.case_id}: DRIFT NOTICE — open_job_count={settled['openJobCount']} "
                f"is outside the loose sanity band [{lo:.0f}, {hi:.0f}] around the last "
                f"measured {board.approx_job_count}. Not a failure — live boards drift "
                "(PLAN.md §6) — reported for visibility."
            )
    print(f"{board.case_id}: harvested {settled['openJobCount']} open jobs (live count, informational)")

    source_id = f"custom:{company_id}"
    total = db.job_listing_count(db_conn, source_id=source_id)
    with_posted_on = _count_with_posted_on(db_conn, source_id)
    with_first_seen = _count_with_first_seen(db_conn, source_id)
    assert with_posted_on == 0, (
        f"{board.case_id}: posted_on must be NULL for every harvested job "
        f"(the board publishes no date field) — found {with_posted_on} of {total} set"
    )
    assert with_first_seen == total, (
        f"{board.case_id}: first_seen_at must be set for every job — "
        f"{with_first_seen} of {total} set"
    )

    # ...and WHAT IS ON THE ROWS, which this suite could not see until now. See the
    # block at the bottom of this file for why each of these is here.
    rows = _harvested_rows(db_conn, source_id)
    (extract,) = [
        st for st in script["script"]["steps"] if st["op"] == "extract_json_path"
    ]
    _assert_job_links_point_at_jobs(board, rows)
    _assert_fields_are_per_job(board, rows)
    _assert_two_job_links_resolve(board, rows, url_spec=extract["fields"]["url"])
    return company_id


def _count_with_posted_on(conn, source_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM job_listings WHERE source_id = %s AND posted_on IS NOT NULL",
            (source_id,),
        )
        return int(cur.fetchone()["n"])


def _count_with_first_seen(conn, source_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM job_listings WHERE source_id = %s AND first_seen_at IS NOT NULL",
            (source_id,),
        )
        return int(cur.fetchone()["n"])


class TestDiscoveryAtlassian:
    @pytest.mark.live
    def test_ac04_atlassian_discovers_and_harvests(self, http, db_conn):
        _run_discovery_case(http, db_conn, boards.ATLASSIAN)


class TestDiscoveryJaneStreet:
    @pytest.mark.live
    def test_ac05_jane_street_discovers_and_harvests_with_no_date_field(self, http, db_conn):
        _run_discovery_case(http, db_conn, boards.JANE_STREET)


# --------------------------------------------------------------------------
# WHAT THE HARVEST ACTUALLY WROTE — the half this suite could not see
# --------------------------------------------------------------------------
#
# AC-04 and AC-05 have run these two boards LIVE on every suite run since they were
# written, and asserted the verdict, the oracle, the transport, ``openJobCount``,
# ``posted_on`` and ``first_seen_at`` — never a URL, a location or a description. So
# Jane Street shipped 233 jobs whose "view job" link went to the board's own listing
# page, green, through 48 passing cases. These are the assertions that would have seen
# it, and they are deliberately about the CONTENT of a row rather than about the shape
# of the pipeline that wrote it.
#
# A job link is not checkable from its status code — a client-rendered board answers
# 200 for any path — so the live half asks the same question ``discover._prove_job_link``
# asks: do two different jobs get two different pages?

_MIN_LOCATION_COVERAGE = 0.8       # Atlassian leaves ~9% of its postings without one
_MIN_URL_DISTINCTNESS = 0.8        # two postings CAN share an application page
_LINK_CHECK_SAMPLES = 2
_LINK_CHECK_TIMEOUT_S = 30.0

# THE REAL RULES, IMPORTED — not retyped. This helper used to carry its own copy of the
# page comparison (raw ``len(resp.text)``, a flat 200-char floor and a 2% fraction), and
# on 2026-08-30 the copy went out of sync with production and failed a board that
# production had correctly PROVED: Jane Street's ``…/position/8213653002/`` and
# ``…/position/8233259002/`` are *ASIC Engineer, New York* and *ASIC Engineer, London* —
# two real jobs, near-identical sibling pages, 53,710 vs 53,535 raw bytes. The shipped
# prover reads the DECLARED title and says yes; the copy read only bytes and said no.
#
# A duplicated rule that can disagree with the rule it is checking is worse than no
# check, so the duplication is gone. The path check (Nintendo) is the same rule
# ``request_selector._names_a_page`` gates rung 1 with, imported for the same reason.
# What stays local is the SPLIT — WHEN each rule applies: a published link is never
# page-compared (Atlassian's iCIMS iframe serves 478,872 / 478,860 / 478,906 chars for
# three different jobs), and the path check runs on every row regardless.
_declared_title = _discover._declared_title
_page_text = _discover._page_text
_pages_differ = _discover._pages_differ
_names_a_page = sys.modules["api.services.capture.request_selector"]._names_a_page


def _harvested_rows(conn, source_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, url, location, details->>'description' AS description "
            "FROM job_listings WHERE source_id = %s",
            (source_id,),
        )
        return list(cur.fetchall())


def _assert_job_links_point_at_jobs(board: "boards.Board", rows: list[dict]) -> None:
    """Every link absolute, per-job, and NOT the honest listing-page fallback.

    ``discover._board_page_link`` produces ``<listing page>#<job id>`` when no per-job
    link can be proved. It is safe and it is honest and it is not a job link, so a board
    that lands there has not been fixed — which is exactly the state Jane Street was in
    while this suite was green.
    """
    urls = [r["url"] for r in rows]
    assert all(isinstance(u, str) and u.startswith("https://") for u in urls), (
        f"{board.case_id}: every job URL must be an absolute https link; got "
        f"{[u for u in urls if not (isinstance(u, str) and u.startswith('https://'))][:3]}"
    )
    fragments = [u for u in urls if "#" in u]
    assert not fragments, (
        f"{board.case_id}: {len(fragments)} of {len(urls)} job URLs are "
        f"listing-page fragments (e.g. {fragments[0]!r}) — that is "
        f"``_board_page_link``, the fallback discovery uses when it cannot PROVE a "
        f"per-job link. The job-url derivation did not find one for this board."
    )
    distinct = len(set(urls))
    assert distinct >= _MIN_URL_DISTINCTNESS * len(urls), (
        f"{board.case_id}: only {distinct} distinct URLs across {len(urls)} jobs — a "
        f"link that is the same on every row is a careers page, a logo or an SPA shell, "
        f"not a link to this job"
    )


def _assert_two_job_links_resolve(
    board: "boards.Board", rows: list[dict], *, url_spec: str
) -> None:
    """Fetch two real job pages and prove the stored link is a link.

    Two questions, and the SECOND is asked only of a link WE composed:

    * every sampled link answers < 400. Always asked.
    * two different jobs get two materially different pages. Asked only when
      ``url_spec`` is a TEMPLATE (it carries a placeholder), because that is the only
      case where the path is our invention rather than the board's own statement.

    THE SPLIT IS THE ONE ``discover._resolve_job_link`` ALREADY MAKES, and it is not
    pedantry — measured 2026-08-30, Atlassian's published iCIMS links serve
    **478,872 / 478,860 / 478,906 chars** for three different jobs, because the posting
    renders inside an IFRAME. That is byte-for-byte the shape of a dead SPA shell, and
    it is a perfectly good working link. Applying the page-diff test to a published link
    would fail one of the two boards this suite exists to protect.

    A TRANSPORT failure is BLOCKED, not FAILED (PLAN.md §6): a third-party outage must
    not read as our regression. A 4xx/5xx always FAILS; an identical pair FAILS only for
    a template, per the split above.

    ...AND A THIRD QUESTION, ASKED OF BOTH: does the stored URL name a PAGE? This is the
    half that used to be missing entirely. Nintendo's Greenhouse embed publishes
    ``absolute_url = "https://careers.nintendo.com/?gh_jid=4295098009"``: distinct per
    job, link-shaped, HTTP 200 — and 64,408 bytes of the LISTING page with the job's own
    title absent. Everything above passes it. A link whose path is ``/`` puts all its
    identity in a query string, which is exactly what a board serving one SPA shell
    ignores, so it is checked on EVERY row and before anything is fetched. See AC-20.
    """
    for row in rows:
        url = row.get("url")
        assert _names_a_page(url), (
            f"{board.case_id}: the stored job link {url!r} has no path segments — all "
            f"its identity is in the query string. Measured on Nintendo: such a URL "
            f"answers 200 and serves the board's listing page to every job."
        )
    sample = [r for r in rows if isinstance(r.get("url"), str)][:_LINK_CHECK_SAMPLES]
    assert len(sample) == _LINK_CHECK_SAMPLES, f"{board.case_id}: too few rows to check"
    pages: list[tuple[str, int]] = []
    for row in sample:
        try:
            resp = httpx.get(
                row["url"], timeout=_LINK_CHECK_TIMEOUT_S, follow_redirects=True,
                headers={"User-Agent": _BROWSER_UA},
            )
        except httpx.HTTPError as exc:
            pytest.skip(
                f"BLOCKED: {board.label} job page {row['url']} unreachable ({exc!r})"
            )
        assert resp.status_code < 400, (
            f"{board.case_id}: the stored job link {row['url']!r} answers HTTP "
            f"{resp.status_code} — every user clicking this job gets that"
        )
        pages.append((row["url"], resp.text))
    (url_a, body_a), (url_b, body_b) = pages
    said_a, said_b = _declared_title(body_a), _declared_title(body_b)
    text_a, text_b = _page_text(body_a), _page_text(body_b)
    print(
        f"{board.case_id}: job links resolve — {url_a} ({len(text_a)} chars, "
        f"{said_a!r}), {url_b} ({len(text_b)} chars, {said_b!r})"
    )
    if "{" not in url_spec:
        return                      # a link the BOARD published; see the docstring
    if said_a and said_b and said_a != said_b:
        return                      # the pages declare two different jobs
    assert _pages_differ(text_a, text_b), (
        f"{board.case_id}: the TEMPLATE {url_spec!r} served two different jobs the same "
        f"page ({len(text_a)} vs {len(text_b)} chars, declared {said_a!r} / {said_b!r}: "
        f"{url_a} / {url_b}) — it does not route on the job id, so every link on this "
        f"board points at the same place"
    )


def _assert_fields_are_per_job(board: "boards.Board", rows: list[dict]) -> None:
    """Locations populated, descriptions per-job.

    Both boards publish a location on nearly every posting and prose on every one. A
    column of NULLs means a mapping that renders nothing was stored anyway (the gap in
    ``_prune_unusable_optionals``); one description repeated on every row means company
    boilerplate was stored as this job's description.
    """
    located = [r for r in rows if r["location"]]
    assert len(located) >= _MIN_LOCATION_COVERAGE * len(rows), (
        f"{board.case_id}: only {len(located)} of {len(rows)} jobs carry a location — a "
        f"field mapped to a path that renders nothing must be DROPPED at discovery, not "
        f"stored as a column of NULLs"
    )
    described = [r["description"] for r in rows if r["description"]]
    assert described, (
        f"{board.case_id}: no job carries a description, but this board publishes prose "
        f"on every posting — either the mapping was lost or it was dropped as boilerplate"
    )
    assert len(set(described)) > 1, (
        f"{board.case_id}: all {len(described)} descriptions are identical — that is the "
        f"employer's boilerplate, not this job's prose, and it must be dropped at "
        f"discovery rather than written onto every row"
    )
    print(
        f"{board.case_id}: {len(located)}/{len(rows)} located, "
        f"{len(set(described))} distinct descriptions"
    )
