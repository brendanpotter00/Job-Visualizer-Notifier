"""AC-22 .. AC-24 — the three Stage-2 schema primitives
(``docs/implementations/custom-company-sources/PATH-TO-90-PERCENT.md`` §6 "Stage 2").

Each case pins a MECHANISM the vocabulary gained, plus — for AC-22 — the completeness
the mechanism must NOT buy. Live numbers were taken by hand on 2026-08-30 and are
recorded in the docstrings; what is checked in is the shape.

**Hermetic by default, and for the reason AC-16..AC-20 already give**: a live board
changes under you and a regression test that turns pink because a third party shipped a
redesign stops being read. Every fixture here is REAL captured bytes:

* ``bloomberg_searchjobs_anchors.html`` — the 12 distinct ``JobDetail`` anchors and six
  navigation anchors of ``bloomberg.avature.net/careers/SearchJobs``, verbatim tags;
* ``bloomberg_avature_sitemap_locs.json`` — all 420 ``<loc>`` entries of that board's
  sitemap, 380 of them jobs;
* ``src/backend/api/tests/fixtures/captures/klarna_rsc_flight.html`` — jobs.deel.com's
  Klarna board, with the description text rows truncated (see that file's own test).

There is no ``live`` case in this file, deliberately. The three live proofs are
one-shot measurements against boards with a PerimeterX tarpit (Bloomberg), an
interactive Turnstile (Citadel) and a session-bound GraphQL endpoint (Meta) — none of
them is a thing to fetch on every suite run.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest

from api.services.capture.discover import discover  # noqa: E402
from api.services.capture.network_capture import CaptureResult  # noqa: E402
from api.services.capture.request_selector import (  # noqa: E402
    CandidateAnswer,
    RequestSelection,
)
from api.services.capture.sources import WellKnownEvidence  # noqa: E402
from api.services.harvest_meta import HarvestEvidence  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
_BACKEND_FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "src" / "backend" / "api" / "tests" / "fixtures" / "captures"
)


# --------------------------------------------------------------------------
# shared seams (same style as test_board_defects.py)
# --------------------------------------------------------------------------

def capturing(result: CaptureResult):
    async def _capture(url: str, **_: Any) -> CaptureResult:
        return result
    return _capture


def allow_all(_url: str) -> None:
    return None


def one_page_per_job() -> Any:
    def _probe(url: str) -> tuple[int, str]:
        return 200, f"<html><body>{url}</body></html>" + "x" * (len(url) * 97)
    return _probe


async def no_well_known(_url: str) -> WellKnownEvidence:
    return WellKnownEvidence()


def failing_replay(exc: Exception):
    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        raise exc
    return _replay


def _replay_12(candidate: Any, declared_total: int):
    """A replay that reads exactly what the captured feed holds — the honest outcome
    for a board whose one request returns 12 rows. The refusal has to come from the
    COVERAGE floor comparing that against the board's own total, not from a failure."""
    from api.services.recipe_runner import _apply_shaping, map_records

    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        (extract,) = [s for s in script["steps"] if s["op"].startswith("extract_")]
        rows = map_records(candidate.records, extract["fields"],
                           script.get("base_url", ""))
        rows = _apply_shaping(
            rows, [s for s in script["steps"]
                   if s["op"] in ("transform", "parse_date")]
        )
        return rows, HarvestEvidence(
            declared_total=declared_total, cap_hit=False, terminated_cleanly=True,
            page_advance_ok=None, pages_fetched=1, transport_ok=True,
        )
    return _replay


def answering(selection: RequestSelection):
    async def _select(candidates: list[Any], **_: Any):
        return [CandidateAnswer(
            candidate_index=0, selection=selection, confidence="high",
        )]
    return _select


# ==========================================================================
# AC-22 — Bloomberg: the title-from-slug transform, and the sweep it must not bless
# ==========================================================================

_BLOOMBERG_SITEMAP = "https://bloomberg.avature.net/careers/sitemap.xml"


def _bloomberg_locs() -> list[str]:
    return json.loads(
        (FIXTURES / "bloomberg_avature_sitemap_locs.json").read_text()
    )["locs"]


def _bloomberg_listing_capture() -> CaptureResult:
    markup = (FIXTURES / "bloomberg_searchjobs_anchors.html").read_text()
    return CaptureResult(
        final_url="https://bloomberg.avature.net/careers/SearchJobs",
        page_title="Search Jobs | Bloomberg",
        responses=[],
        server_html=markup,
        server_html_url="https://bloomberg.avature.net/careers/SearchJobs",
    )


class TestAC22TitleFromSlug:
    """AC-22 — **a source that publishes URLs and no titles is now readable.**

    Bloomberg's Avature sitemap publishes ``<loc>`` and ``<lastmod>`` and nothing else,
    so the only value a recipe could put in ``title`` was the job's own URL — and
    ``map_records`` drops a row with no title, so mapping it there is not a mistake, it
    is the only way the row exists. ``_select_html_field`` is whole-node only and
    ``transform`` had just ``template``/``base_url_join``; there was no way to say "the
    title is the slug inside this link".

    Measured live 2026-08-30 through the real ``recipe_runner.run_recipe``, plain
    ``httpx``, no browser:

    * Bloomberg — **380 rows in 0.5s** against the sitemap oracle's own **380**,
      ``terminated_cleanly=True``, **0** rows left carrying a URL in the title column;
    * Citadel — **56 rows in 0.4s** against a declared **56**, 56 distinct titles.

    That is the 22/27 → 24/27 the plan attributes to this primitive.
    """

    def test_ac22_the_sitemap_publishes_links_and_no_titles(self) -> None:
        """The premise, asserted rather than assumed."""
        locs = _bloomberg_locs()
        jobs = [u for u in locs if "/careers/JobDetail/" in u]
        assert len(locs) == 420 and len(jobs) == 380, (
            f"AC-22: fixture drift — {len(locs)} locs, {len(jobs)} of them jobs"
        )
        assert len({u.rsplit("/", 1)[-1] for u in jobs}) == 380, (
            "AC-22: every job loc must end in its own requisition id"
        )

    def test_ac22_the_recipe_reads_the_whole_sitemap_with_real_titles(self) -> None:
        """The real replay path, over the real sitemap bytes."""
        import warnings

        import httpx

        from api.services.recipe_runner import run_recipe

        locs = _bloomberg_locs()
        body = (
            '<?xml version="1.0" encoding="UTF-8"?><urlset>'
            + "".join(f"<url><loc>{u}</loc></url>" for u in locs)
            + "</urlset>"
        )
        script = {
            "script_version": 1,
            "transport": "http_html",
            "expected_min_jobs": 1,
            "base_url": "https://bloomberg.avature.net",
            "steps": [
                {"op": "fetch", "method": "GET", "url": _BLOOMBERG_SITEMAP,
                 "headers": {}},
                {"op": "extract_css",
                 "record_selector": 'url:-soup-contains("/careers/JobDetail/")',
                 "field_selectors": {"id": "loc", "title": "loc", "url": "loc"}},
                {"op": "transform", "field": "title", "kind": "regex_capture",
                 "from": "url", "pattern": r"/([^/?#]+)/\d+/?$", "unslug": True},
                {"op": "dedupe_key", "field": "id"},
                {"op": "assert_unique", "field": "id"},
            ],
            "oracle": {"kind": "sitemap", "sitemap_url": _BLOOMBERG_SITEMAP,
                       "url_pattern": "/careers/JobDetail/"},
        }
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, text=body, headers={"content-type": "text/xml"}
            )
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with httpx.Client(transport=transport) as http:
                rows, evidence = run_recipe(script, http)

        assert len(rows) == 380, f"AC-22: expected all 380 postings, got {len(rows)}"
        assert evidence.declared_total == 380, (
            "AC-22: the sitemap oracle counts the same 380 it read, so this board can "
            "actually be VERIFIED rather than living on UNVERIFIED forever"
        )
        assert not [r for r in rows if str(r["title"]).startswith("http")], (
            "AC-22: not one row may still carry a URL in the title column — that is "
            "the whole defect"
        )
        titles = {r["title"] for r in rows}
        assert "M A Deals Reporter" in titles
        assert len(titles) == 345, (
            "AC-22: 380 postings, 345 distinct titles — Bloomberg genuinely lists the "
            "same role several times (three 'Product Manager Company Screening' reqs). "
            f"Got {len(titles)}; the IDS are what must be unique, and they are"
        )


class TestAC22DoesNotWeakenCompleteness:
    """**The cautionary half, and the reason this class exists at all.**

    An earlier agent proved that fixing Bloomberg's anchor grouping alone would store
    **12 of 380** jobs as a clean, complete-looking sweep and then close the other 368.
    Re-measured live 2026-08-30: ``bloomberg.avature.net/careers/SearchJobs`` publishes
    exactly **12** distinct ``JobDetail`` anchors on page one, its ``jobRecordsPerPage``
    parameter is ignored, and ``http_html`` may not paginate — while its own sitemap
    publishes **380**.

    A new FIELD primitive must not move that verdict one inch, and "it obviously does
    not" is not a check. Three checks, in order of how much they prove:

    1. the board's listing still produces no candidate at all (real bytes);
    2. the transform is structurally incapable of shortening a sweep;
    3. a board where the derivation DOES fire and the read IS a sliver is still refused
       by the coverage floor, through the real ``discover()``.
    """

    def test_ac22_the_listing_publishes_12_of_380(self) -> None:
        """The premise, from the real page and the real sitemap."""
        markup = (FIXTURES / "bloomberg_searchjobs_anchors.html").read_text()
        hrefs = set(re.findall(r'href="([^"]*JobDetail[^"]*)"', markup))
        assert len(hrefs) == 12, f"AC-22: page one lists 12 jobs; got {len(hrefs)}"
        assert len([u for u in _bloomberg_locs() if "/JobDetail/" in u]) == 380

    def test_ac22_that_listing_still_produces_no_candidate_at_all(self) -> None:
        """Where the 12-of-380 sweep is stopped TODAY, recorded so a later change to
        the anchor grouping cannot quietly unstop it.

        Avature puts the requisition id in the LAST path segment
        (``/careers/JobDetail/<slug>/21646``), so ``_anchor_rows`` groups on
        ``/careers/JobDetail/<slug>/`` — a different directory per job, twelve groups of
        one, all under ``_MIN_HTML_RECORDS``. Stage 2 changed nothing here and must not.
        """
        from api.services.capture.sources import _anchor_rows, anchor_candidate

        capture = _bloomberg_listing_capture()
        groups = _anchor_rows(capture.server_html, "bloomberg.avature.net")
        job_groups = {d: len(r) for d, r in groups.items() if "JobDetail" in d}
        assert max(job_groups.values()) < 8, (
            f"AC-22: every job is its own group; got {job_groups}"
        )
        assert anchor_candidate(capture, "bloomberg.avature.net") is None, (
            "AC-22: if this board ever starts producing an anchor candidate, the very "
            "next thing to check is whether a 12-row sweep can VERIFY — see the class "
            "docstring. Rewrite this case, do not delete it"
        )

    def test_ac22_the_transform_can_never_shorten_a_sweep(self) -> None:
        """The structural half, and the strongest of the three.

        Completeness is judged on row COUNTS. A shaping step that silently dropped the
        rows it could not read would make a short sweep look clean — so ``regex_capture``
        does not drop: it either derives a value for every row or RAISES
        (``recipe_runner._assert_shaping_kept_required_fields``). ``len(rows)`` is
        therefore invariant across shaping, which is what lets every existing gate keep
        meaning what it meant.
        """
        from api.services.recipe_runner import (
            RecipeExecutionError,
            _apply_shaping,
            _assert_shaping_kept_required_fields,
        )

        step = {"op": "transform", "field": "title", "kind": "regex_capture",
                "from": "url", "pattern": r"/([^/?#]+)/\d+/?$", "unslug": True}
        rows = [{"id": str(n), "title": f"https://b.test/JobDetail/Role-{n}/{n}",
                 "url": f"https://b.test/JobDetail/Role-{n}/{n}"} for n in range(12)]
        shaped = _apply_shaping([dict(r) for r in rows], [step])
        _assert_shaping_kept_required_fields(shaped, [step])
        assert len(shaped) == 12 and all(r["title"].startswith("Role ") for r in shaped)

        rows[4]["url"] = "https://b.test/AgentCreate"
        shaped = _apply_shaping([dict(r) for r in rows], [step])
        assert len(shaped) == 12, (
            "AC-22: the miss must not remove the row — dropping it is how a partial "
            "read starts looking complete"
        )
        with pytest.raises(RecipeExecutionError):
            _assert_shaping_kept_required_fields(shaped, [step])

    def _sliver_capture(self, declared_total: int) -> CaptureResult:
        """A links-only feed that returns 12 jobs and declares the board's real 380.

        Bloomberg's own listing offers no such feed — this is the shape, carrying its
        numbers, which is what the coverage floor actually reads.
        """
        from api.services.capture.network_capture import CapturedResponse

        payload = {
            "total": declared_total,
            "jobs": [
                {"reqId": u.rsplit("/", 1)[-1], "detailUrl": u}
                for u in [x for x in _bloomberg_locs() if "/JobDetail/" in x][:12]
            ],
        }
        body = json.dumps(payload)
        return CaptureResult(
            final_url="https://bloomberg.avature.net/careers/SearchJobs",
            page_title="Search Jobs | Bloomberg",
            responses=[CapturedResponse(
                url="https://bloomberg.avature.net/careers/api/jobs",
                method="GET", status=200, content_type="application/json",
                request_headers={}, post_data=None, body=body, truncated=False,
                body_bytes=len(body),
            )],
        )

    def test_ac22_a_readable_title_does_not_make_a_sliver_complete(self) -> None:
        """The whole point. The derivation FIRES here — the feed publishes links and no
        titles, exactly the Bloomberg/Citadel shape — and the board is still refused,
        because the question the coverage floor asks ("is this the board, or 3% of it?")
        is not the question a field primitive answers."""
        from api.services.capture.request_selector import (
            derive_title_from_url,
            prefilter_candidates,
        )

        captured = self._sliver_capture(380)
        (candidate,) = prefilter_candidates(captured.responses)
        field_map = {"id": "reqId", "title": "detailUrl", "url": "detailUrl"}
        assert derive_title_from_url(candidate.records, field_map) is not None, (
            "AC-22: the premise — this is precisely the board the transform exists for"
        )

        outcome = asyncio.run(discover(
            "https://bloomberg.avature.net/careers/SearchJobs",
            capture=capturing(captured),
            select=answering(RequestSelection(
                chosen_request_index=0, records_path="jobs", field_map=field_map,
                pagination=None,
                title_from_url=derive_title_from_url(candidate.records, field_map),
            )),
            replay_http=_replay_12(candidate, 380),
            replay_browser=failing_replay(AssertionError("http_json is enough")),
            validate_url=allow_all,
            probe_link=one_page_per_job(),
            collect_sources=no_well_known,
        ))

        assert outcome.ok is False, (
            "AC-22: 12 rows against the board's own 380 must stay refused. If this ever "
            "passes, the board is tracked at 12 jobs and closes the other 368 on its "
            "second VERIFIED run"
        )
        reason = outcome.refuse_reason or ""
        assert "silently miss almost all of it" in reason and "380" in reason, (
            f"AC-22: the coverage floor is what must catch it, in the board's own "
            f"numbers; got {reason!r}"
        )

    def test_ac22_the_same_feed_at_full_size_is_accepted(self) -> None:
        """The control. Without it the case above only proves that something refused —
        it could have been the derivation declining, or the link probe, or anything.
        Same bytes, same mapping, the board's total set to what the feed actually
        returns: it stores, and it stores WITH the derived titles."""
        from api.services.capture.request_selector import (
            derive_title_from_url,
            prefilter_candidates,
        )
        from api.services.recipe_runner import map_records

        captured = self._sliver_capture(12)
        (candidate,) = prefilter_candidates(captured.responses)
        field_map = {"id": "reqId", "title": "detailUrl", "url": "detailUrl"}
        selection = RequestSelection(
            chosen_request_index=0, records_path="jobs", field_map=field_map,
            pagination=None,
            title_from_url=derive_title_from_url(candidate.records, field_map),
        )

        async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
            from api.services.recipe_runner import _apply_shaping

            (extract,) = [s for s in script["steps"] if s["op"].startswith("extract_")]
            rows = map_records(candidate.records, extract["fields"],
                               script.get("base_url", ""))
            shaping = [s for s in script["steps"]
                       if s["op"] in ("transform", "parse_date")]
            rows = _apply_shaping(rows, shaping)
            return rows, HarvestEvidence(
                declared_total=12, cap_hit=False, terminated_cleanly=True,
                page_advance_ok=None, pages_fetched=1, transport_ok=True,
            )

        outcome = asyncio.run(discover(
            "https://bloomberg.avature.net/careers/SearchJobs",
            capture=capturing(captured),
            select=answering(selection),
            replay_http=_replay,
            replay_browser=failing_replay(AssertionError("http_json must be enough")),
            validate_url=allow_all,
            probe_link=one_page_per_job(),
            collect_sources=no_well_known,
        ))

        assert outcome.ok is True, (
            f"AC-22 control: got {outcome.refuse_reason!r}"
        )
        assert outcome.script is not None
        (transform,) = [s for s in outcome.script["steps"] if s["op"] == "transform"]
        assert transform["kind"] == "regex_capture" and transform["from"] == "url"


# ==========================================================================
# AC-23 — Meta: fetch.body_encoding
# ==========================================================================

class TestAC23FormEncodedBody:
    """AC-23 — **a board whose request only works form-urlencoded is now expressible.**

    ``metacareers.com``'s ``CareersJobSearchResultsV2DataQuery`` is the measured case.
    Both executors hard-coded JSON (``recipe_runner._request`` did ``http.post(json=…)``,
    ``_browser_fetch_main`` did ``JSON.stringify``), and the 27-board agent escaped only
    by moving the whole body into the query string.

    Measured live 2026-08-30, one key changed, everything else identical:

    * through the REAL ``run_browser_fetch`` on ``metacareers.com/jobsearch/``:
      ``body_encoding: "form"`` → **876 rows in 5.4s**; the default ``json`` → **HTTP 400**;
    * from plain ``httpx``, with the captured headers and cookies and without them:
      **400 in every combination, both encodings.** So Meta is a ``browser_fetch``
      board — form encoding removes OUR blocker, it does not make the endpoint
      answer httpx.

    **A correction to AC-16.** ``test_ac16_the_honest_end_state_is_named`` says Meta
    refuses because "``recipe_schema`` requires ``fetch.body`` to be an OBJECT … so no
    recipe can be synthesised". That is no longer the reason: a form capture now
    synthesises. AC-16 still passes, and honestly — its fixture carries
    ``request_headers={}``, so the recorded request never declares its content-type and
    the JSON parse is still what refuses. The board's real blocker is the 400 above.
    """

    def _capture_with_content_type(self) -> CaptureResult:
        """The AC-16 Meta fixture, plus the ``content-type`` its live request carries."""
        from api.services.capture.network_capture import CapturedResponse

        raw = json.loads((FIXTURES / "meta_graphql_text_html.json").read_text())
        body = json.dumps(raw["body"])
        return CaptureResult(
            final_url="https://www.metacareers.com/jobsearch/",
            page_title=raw.get("page_title", ""),
            responses=[CapturedResponse(
                url=raw["url"], method=raw["method"], status=raw["status"],
                content_type=raw["content_type"],
                request_headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "x-fb-friendly-name": "CareersJobSearchResultsV2DataQuery",
                },
                post_data=raw["post_data"], body=body, truncated=False,
                body_bytes=len(body),
            )],
        )

    def test_ac23_the_captured_meta_body_really_is_form_encoded(self) -> None:
        """The premise, from the real capture."""
        from urllib.parse import parse_qsl

        raw = json.loads((FIXTURES / "meta_graphql_text_html.json").read_text())
        fields = dict(parse_qsl(raw["post_data"], keep_blank_values=True))
        assert fields["fb_api_req_friendly_name"] == (
            "CareersJobSearchResultsV2DataQuery"
        )
        assert fields["doc_id"] and fields["variables"].startswith('{"search_input"')
        with pytest.raises(json.JSONDecodeError):
            json.loads(raw["post_data"])

    def test_ac23_synthesis_writes_a_form_recipe_for_it(self) -> None:
        """The emit half: with the content-type the live request actually sends, the
        board that could not be synthesised at all now produces a valid recipe."""
        from api.services.capture.discover import synthesize_recipe
        from api.services.capture.request_selector import prefilter_candidates
        from api.services.recipe_schema import validate_recipe

        (candidate,) = prefilter_candidates(
            self._capture_with_content_type().responses
        )
        assert candidate.record_count == 877
        script = synthesize_recipe(
            candidate,
            RequestSelection(
                chosen_request_index=0,
                records_path="data.job_search_with_featured_jobs_v2.all_jobs",
                field_map={"id": "id", "title": "title",
                           "url": "https://www.metacareers.com/jobs/{id}/"},
                pagination=None,
            ),
            transport="http_json",
            origin_url="https://www.metacareers.com/jobsearch/",
        )
        fetch = script["steps"][0]
        assert fetch["body_encoding"] == "form"
        assert fetch["body"]["doc_id"], (
            "AC-23: the form fields become the body, flat, exactly as they go on the wire"
        )
        validate_recipe(script, transport="http_json")

    def test_ac23_the_encoding_survives_into_the_browser_tier(self) -> None:
        """The tier that actually reads Meta. ``browser_fetch`` runs the captured
        request out of process, so the encoding has to cross that boundary or the fix
        stops at the httpx tier — which is the one Meta 400s."""
        from api.services.browser_fetch.runner import build_subprocess_plan
        from api.services.recipe_runner import parse_plan
        from api.services.recipe_schema import validate_recipe

        script = {
            "script_version": 1, "transport": "browser_fetch",
            "origin_url": "https://www.metacareers.com/jobsearch/",
            "expected_min_jobs": 1,
            "steps": [
                {"op": "fetch", "method": "POST",
                 "url": "https://www.metacareers.com/graphql", "headers": {},
                 "body": {"doc_id": "27129360303422352", "variables": "{}"},
                 "body_encoding": "form"},
                {"op": "extract_json_path",
                 "records_path": "data.job_search_with_featured_jobs_v2.all_jobs",
                 "fields": {"id": "id", "title": "title",
                            "url": "https://www.metacareers.com/jobs/{id}/"}},
            ],
            "oracle": {"kind": "none"},
        }
        validate_recipe(script, transport="browser_fetch", oracle_kind="none")
        plan = build_subprocess_plan(script, parse_plan(script))
        assert plan["body_encoding"] == "form"


# ==========================================================================
# AC-24 — Klarna: extract_embedded_island with source rsc_flight
# ==========================================================================

def _klarna_capture() -> CaptureResult:
    markup = (_BACKEND_FIXTURES / "klarna_rsc_flight.html").read_text()
    return CaptureResult(
        final_url="https://jobs.deel.com/klarna",
        page_title="Careers at Klarna",
        responses=[],
        server_html=markup,
        server_html_url="https://jobs.deel.com/klarna",
    )


class TestAC24RscFlightBoard:
    """AC-24 — **a Next.js App-Router board is no longer invisible.**

    Klarna and Roblox were both refused by the 27-board agent for one reason: their jobs
    live in a React Flight STREAM, split across dozens of ``self.__next_f.push`` calls,
    and ``extract_embedded_island`` could only ``json.loads`` a single node. Nothing in
    the pipeline could see the array at all — ``island_candidates`` looks for islands the
    capture child found, and an App-Router page has none.

    Measured live 2026-08-30 through the real ``run_recipe``, plain ``httpx``:
    ``jobs.deel.com/klarna`` → **81 rows in 1.2s**, 81 distinct ids, every row with a
    title, plus location and posting date, against a sitemap oracle of **81**. Exactly
    the number PATH-TO-90-PERCENT.md §3 predicted.

    The harder element-tree variant is deliberately skipped (the plan says so): a
    ``records_path`` into a serialized React element tree simply fails to resolve, which
    is a loud FAILED run and never a wrong answer.
    """

    def test_ac24_discovery_offers_the_flight_stream_as_a_candidate(self) -> None:
        from api.services.capture.sources import document_candidates

        (candidate,) = document_candidates(
            _klarna_capture(), "jobs.deel.com", "https://jobs.deel.com/klarna"
        )
        assert candidate.records_path == "9.3.jobPostings"
        assert candidate.record_count == 81
        assert candidate.html.op == "extract_embedded_island"
        assert candidate.html.source == "rsc_flight"

    def test_ac24_the_whole_ladder_stores_a_replaying_recipe(self) -> None:
        """Through the REAL ``discover()``: capture → candidate → selection → synthesis
        → acceptance, with only the model and the network stubbed."""
        from api.services.recipe_runner import map_records, run_recipe

        markup = (_BACKEND_FIXTURES / "klarna_rsc_flight.html").read_text()
        selection = RequestSelection(
            chosen_request_index=0,
            records_path="9.3.jobPostings",
            field_map={
                "id": "id", "title": "title",
                "url": "https://jobs.deel.com/klarna/job-details/{id}/overview",
                "location": "job.jobLocations.0.location.name",
            },
            pagination=None,
        )

        async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
            import httpx

            transport = httpx.MockTransport(
                lambda request: httpx.Response(200, text=markup)
            )
            with httpx.Client(transport=transport) as http:
                return run_recipe(script, http)

        outcome = asyncio.run(discover(
            "https://jobs.deel.com/klarna",
            capture=capturing(_klarna_capture()),
            select=answering(selection),
            replay_http=_replay,
            replay_browser=failing_replay(AssertionError("plain httpx must be enough")),
            validate_url=allow_all,
            probe_link=one_page_per_job(),
            collect_sources=no_well_known,
        ))

        assert outcome.ok is True, (
            f"AC-24: this board must now store. Got: {outcome.refuse_reason!r}"
        )
        assert outcome.script is not None
        assert outcome.script["transport"] == "http_html"
        (extract,) = [
            s for s in outcome.script["steps"] if s["op"].startswith("extract_")
        ]
        assert extract["source"] == "rsc_flight"
        assert extract["records_path"] == "9.3.jobPostings"

        # ...and the stored recipe is one the agent-free runner really reads back.
        rows, _ = asyncio.run(_replay(outcome.script))
        assert len(rows) == 81
        assert len({r["id"] for r in rows}) == 81
        assert map_records(
            [{"id": "x", "title": "T"}], {"id": "id", "title": "title", "url": "id"}
        ), "sanity: the mapper used above is the production one"

    def test_ac24_a_page_with_no_flight_stream_gains_nothing(self) -> None:
        """The regression bar for every board already tracked: a document with no
        ``__next_f`` must produce exactly the candidates it produced before."""
        from api.services.capture.sources import document_candidates, rsc_candidate

        plain = CaptureResult(
            final_url="https://b.example/careers", page_title="", responses=[],
            server_html="<html><body>"
            + "".join(f'<a href="/careers/jobs/{i}">Engineer {i}</a>' for i in range(9))
            + "</body></html>",
            server_html_url="https://b.example/careers",
        )
        assert rsc_candidate(plain, "https://b.example/careers") is None
        (only,) = document_candidates(plain, "b.example", "https://b.example/careers")
        assert only.html.op == "extract_css", (
            "AC-24: the anchor source must still be what this page produces"
        )
