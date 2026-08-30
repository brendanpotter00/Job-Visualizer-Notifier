"""E7 Stage 2 — the three named schema gaps (PATH-TO-90-PERCENT.md §6).

Three primitives, each admitted by the schema on WRITE and on READ, executed by the
runner, and emittable by discovery:

* ``transform.kind = 'regex_capture'`` — derive a title from a URL slug. Live on
  2026-08-30: Bloomberg 380/380 rows against its sitemap's own 380, Citadel 56/56, and
  ZERO rows left carrying a URL in the title column.
* ``fetch.body_encoding = 'form'`` — metacareers.com's jobs GraphQL answers 200 with
  876 records to a form-encoded body and **400** to the same fields as JSON, measured
  through the real ``run_browser_fetch`` on the same day, same session, one key changed.
* ``extract_embedded_island.source = 'rsc_flight'`` — the Next.js App-Router row
  parser. Live: Klarna 81/81 from plain ``httpx``, no browser.

Everything here is pure — no DB, no network. The live numbers above are quoted, not
re-measured: a test that fetches a third party's board is a test that turns red when
that third party ships a redesign.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any

import httpx
import pytest

from api.services.recipe_runner import (
    CAPTURE_SUBJECT_MAX_CHARS,
    RecipeExecutionError,
    _form_fields,
    _regex_capture_value,
    _unslug,
    parse_rsc_flight,
    run_recipe,
)
from api.services.recipe_schema import (
    CAPTURE_PATTERN_MAX_CHARS,
    RecipeError,
    validate_capture_pattern,
    validate_recipe,
)

_CAPTURES = Path(__file__).parent / "fixtures" / "captures"
_BACKEND = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND.parents[1]


# --------------------------------------------------------------------------
# shared script builders
# --------------------------------------------------------------------------

def _html_script(**overrides: Any) -> dict[str, Any]:
    script: dict[str, Any] = {
        "script_version": 1,
        "transport": "http_html",
        "expected_min_jobs": 1,
        "base_url": "https://bloomberg.avature.net",
        "steps": [
            {"op": "fetch", "method": "GET",
             "url": "https://bloomberg.avature.net/careers/sitemap.xml", "headers": {}},
            {"op": "extract_css",
             "record_selector": 'url:-soup-contains("/careers/JobDetail/")',
             "field_selectors": {"id": "loc", "title": "loc", "url": "loc"}},
            {"op": "transform", "field": "title", "kind": "regex_capture",
             "from": "url", "pattern": r"/([^/?#]+)/\d+/?$", "unslug": True},
            {"op": "dedupe_key", "field": "id"},
        ],
        "oracle": {"kind": "none"},
    }
    script.update(overrides)
    return script


def _post_script(**fetch_overrides: Any) -> dict[str, Any]:
    fetch: dict[str, Any] = {
        "op": "fetch", "method": "POST", "url": "https://board.test/graphql",
        "headers": {}, "body": {"doc_id": "27129360303422352", "variables": "{}"},
    }
    fetch.update(fetch_overrides)
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": 1,
        "steps": [
            fetch,
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "title", "url": "u"}},
        ],
        "oracle": {"kind": "none"},
    }


# ==========================================================================
# GAP 1 — transform.kind = "regex_capture"
# ==========================================================================

class TestCapturePatternIsABoundedLanguage:
    """The pattern is a CLOSED subset, not a regex, and the reason is the threat model.

    It lands in ``company_scripts.script`` JSONB — data that drifts and is re-validated
    on every nightly read — and Python's ``re`` has no timeout and no step budget, so a
    catastrophically-backtracking pattern is a worker pinned with no way to interrupt it.
    Every rejection below names the shape it forbids.
    """

    def test_a_realistic_slug_pattern_is_admitted(self) -> None:
        for pattern in (r"/([^/?#]+)/\d+/?$", r"/([^/?#]+)/?$",
                        r"/jobs/detail/([a-z0-9-]{3,64})$",
                        r"/(?:careers|jobs)/([a-z0-9-]+)$"):
            validate_capture_pattern(pattern, "transform")

    def test_even_a_HARMLESS_group_quantifier_is_refused(self) -> None:
        """``(?:detail/)?`` cannot backtrack and is still rejected, because the rule is
        STRUCTURAL — "is there a quantifier after a ``)``" — and a rule that has to
        reason about whether *this* group is ambiguous is a rule that will one day get
        it wrong. Nothing needs the shape: the two derived patterns do not use it, and a
        board that does can spell the alternation inside the class instead."""
        with pytest.raises(RecipeError, match="applies a quantifier to a GROUP"):
            validate_capture_pattern(r"/jobs/(?:detail/)?([a-z-]+)$", "transform")

    @pytest.mark.parametrize(
        "pattern, because",
        [
            (r"/((?:a+)+)/", "a quantifier applied to a GROUP"),
            (r"/((?:a|a)*)x", "a quantifier applied to a GROUP"),
            (r"/(\w+)\1/", "a backreference"),
            (r"/(?=jobs)([a-z]+)/", "lookahead"),
            (r"/(?<=jobs/)([a-z]+)/", "lookbehind"),
            (r"/(?P<slug>[a-z]+)/", "a named group"),
            (r"/([a-z]{2,})/", "an unbounded repetition"),
            (r"/([a-z]{2,999})/", "a repetition past the ceiling"),
            (r"/([a-z]*)([0-9]*)/", "two capture groups"),
            (r"/[a-z]+/[a-z]+/[a-z]+/([a-z]+)/", "four quantifiers"),
            (r"/([a-z]+", "an invalid regex"),
            (r"/jobs/[a-z]+/", "no capture group at all"),
        ],
    )
    def test_the_shapes_outside_the_subset_are_rejected(
        self, pattern: str, because: str
    ) -> None:
        with pytest.raises(RecipeError):
            validate_capture_pattern(pattern, "transform")

    def test_an_over_long_pattern_is_rejected(self) -> None:
        """The literal 200 is deliberate. Building the subject out of
        ``CAPTURE_PATTERN_MAX_CHARS`` would make the case scale with the constant it is
        testing — raise the cap and the test raises its own input to match, so the bound
        could be deleted and nothing would go red."""
        assert CAPTURE_PATTERN_MAX_CHARS == 200
        with pytest.raises(RecipeError, match="chars"):
            validate_capture_pattern("/(" + "a" * 200 + ")/", "transform")

    def test_the_lazy_modifier_is_not_counted_as_a_second_quantifier(self) -> None:
        """``+?`` is ONE quantifier wearing two characters. Counting it twice would
        reject ``/([^/]+?)/\\d+/?$``, which is a pattern a board legitimately needs."""
        validate_capture_pattern(r"/([^/]+?)/\d+/?$", "transform")

    def test_validate_recipe_applies_the_bound_on_read(self) -> None:
        """The write path is not the only path — a stored row can be edited."""
        script = _html_script()
        script["steps"][2]["pattern"] = r"/((?:a+)+)b/"
        with pytest.raises(RecipeError, match="applies a quantifier to a GROUP"):
            validate_recipe(script)


class TestRegexCaptureSchema:
    def test_the_step_validates(self) -> None:
        assert validate_recipe(_html_script()) is not None

    def test_from_must_name_a_canonical_field(self) -> None:
        """Shaping runs on MAPPED rows, so a raw-record path renders empty forever."""
        script = _html_script()
        script["steps"][2]["from"] = "job.absolute_url"
        with pytest.raises(RecipeError, match="transform.from must be one of"):
            validate_recipe(script)

    def test_unslug_must_be_a_bool(self) -> None:
        script = _html_script()
        script["steps"][2]["unslug"] = "yes"
        with pytest.raises(RecipeError, match="transform.unslug must be true or false"):
            validate_recipe(script)

    def test_an_unknown_transform_key_still_fails_loudly(self) -> None:
        script = _html_script()
        script["steps"][2]["patern"] = "typo"
        with pytest.raises(RecipeError, match="unknown key"):
            validate_recipe(script)

    def test_the_two_older_kinds_are_untouched(self) -> None:
        for step in (
            {"op": "transform", "field": "url", "kind": "base_url_join",
             "base_url": "https://b.test"},
            {"op": "transform", "field": "title", "kind": "template",
             "template": "{title} ({location})"},
        ):
            script = _html_script()
            script["steps"][2] = step
            assert validate_recipe(script) is not None


class TestUnslug:
    """The casing rule is the part that could quietly be wrong on half a board."""

    def test_a_slug_that_carries_its_own_case_is_left_alone(self) -> None:
        assert _unslug("Senior-Data-Management-Professional-iOS") == (
            "Senior Data Management Professional iOS"
        )

    def test_a_slug_with_no_case_information_is_title_cased(self) -> None:
        assert _unslug("commodities-portfolio-manager") == (
            "Commodities Portfolio Manager"
        )

    def test_percent_escapes_and_plus_signs_decode(self) -> None:
        assert _unslug("Staff%20Engineer+Platform") == "Staff Engineer Platform"

    def test_separators_collapse_rather_than_doubling_up(self) -> None:
        assert _unslug("M-A--Deals___Reporter") == "M A Deals Reporter"


class TestRegexCaptureDegradesToAbsent:
    """**A miss must produce ABSENT, never a wrong value.** The whole point of the
    primitive is that the source field is a URL; leaving it in place on a miss would
    ship the exact defect it was added to fix, on precisely the rows nobody checks."""

    STEP = {"from": "url", "pattern": r"/([^/?#]+)/\d+/?$", "unslug": True}

    def test_a_bloomberg_url_yields_its_title(self) -> None:
        row = {"url": "https://bloomberg.avature.net/careers/JobDetail/"
                      "Senior-Recruiter-Corporate-Functions/21654"}
        assert _regex_capture_value(row, self.STEP) == (
            "Senior Recruiter Corporate Functions"
        )

    def test_a_citadel_url_yields_its_title(self) -> None:
        step = {"from": "url", "pattern": r"/([^/?#]+)/?$", "unslug": True}
        row = {"url": "https://www.citadel.com/careers/details/"
                      "commodities-portfolio-manager/"}
        assert _regex_capture_value(row, step) == "Commodities Portfolio Manager"

    @pytest.mark.parametrize("value", [
        "https://bloomberg.avature.net/careers/AgentCreate",   # no slug/id pair
        "",                                                     # empty
        None,                                                   # unmapped
        12345,                                                  # not a string
    ])
    def test_anything_the_pattern_cannot_read_becomes_none(self, value: Any) -> None:
        assert _regex_capture_value({"url": value}, self.STEP) is None

    def test_the_subject_is_capped(self) -> None:
        """A 512-char cap is the other half of the pattern bound; past it the pattern
        simply does not see the tail, which reads as a miss (→ absent).

        The literal 512 is deliberate — see ``test_an_over_long_pattern_is_rejected``."""
        assert CAPTURE_SUBJECT_MAX_CHARS == 512
        long_url = "https://b.test/" + "x" * 512 + "/Slug/12"
        assert _regex_capture_value({"url": long_url}, self.STEP) is None
        assert _regex_capture_value(
            {"url": "https://b.test/x/Slug/12"}, self.STEP
        ) == "Slug", "…and a short URL still reads normally"


class TestShapingMayNotEmptyARequiredField:
    """A ``regex_capture`` that stops matching is a FAILED run, not a quiet shrink.

    Three quiet alternatives, all rejected, all worse: leaving the URL in the title
    column reintroduces the defect; dropping the row makes a SHORTER sweep that still
    reports ``terminated_cleanly`` and therefore VERIFIES and closes the rest; writing
    ``None`` stores the literal string ``"None"`` (``recipe_rows`` does ``str(...)``).
    """

    def _run(self, body: str) -> Any:
        script = _html_script()
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text=body,
                                           headers={"content-type": "text/xml"})
        )
        with httpx.Client(transport=transport) as http:
            return run_recipe(script, http)

    SITEMAP = (
        '<?xml version="1.0" encoding="UTF-8"?><urlset>'
        "<url><loc>https://bloomberg.avature.net/careers/JobDetail/Line-Producer/21646"
        "</loc></url>"
        "<url><loc>https://bloomberg.avature.net/careers/JobDetail/M-A-Deals-Reporter/"
        "21669</loc></url>"
        "</urlset>"
    )

    def test_the_happy_path_stores_real_titles(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rows, _ = self._run(self.SITEMAP)
        assert [r["title"] for r in rows] == ["Line Producer", "M A Deals Reporter"]
        assert not any(str(r["title"]).startswith("http") for r in rows)

    def test_a_row_the_pattern_cannot_read_fails_the_whole_run(self) -> None:
        broken = self.SITEMAP.replace(
            "</urlset>",
            "<url><loc>https://bloomberg.avature.net/careers/JobDetail/</loc></url>"
            "</urlset>",
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with pytest.raises(RecipeExecutionError, match="emptied the required field"):
                self._run(broken)

    def test_a_board_with_no_shaping_on_a_required_field_is_unaffected(self) -> None:
        """The guard is scoped, so every recipe that shapes only optionals is untouched
        — including the ``parse_date`` steps every discovered board already carries."""
        script = _html_script()
        script["steps"][2] = {"op": "transform", "field": "location",
                              "kind": "regex_capture", "from": "url",
                              "pattern": r"/(nowhere)/", "unslug": False}
        script["steps"][1]["field_selectors"]["title"] = "loc"
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text=self.SITEMAP,
                                           headers={"content-type": "text/xml"})
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with httpx.Client(transport=transport) as http:
                rows, _ = run_recipe(script, http)
        assert len(rows) == 2
        assert all(r["location"] is None for r in rows), (
            "an OPTIONAL field that the pattern cannot read is absent, not fatal"
        )


# ==========================================================================
# GAP 2 — fetch.body_encoding
# ==========================================================================

class TestBodyEncodingSchema:
    def test_json_is_the_default_and_an_absent_key_still_means_json(self) -> None:
        script = _post_script()
        assert "body_encoding" not in script["steps"][0]
        assert validate_recipe(script) is not None

    def test_form_validates(self) -> None:
        assert validate_recipe(_post_script(body_encoding="form")) is not None

    def test_an_unknown_encoding_is_rejected(self) -> None:
        with pytest.raises(RecipeError, match="body_encoding"):
            validate_recipe(_post_script(body_encoding="multipart"))

    def test_it_is_rejected_on_a_get(self) -> None:
        """A GET carries no body, so the key can only be a mislabel — and silently
        ignoring it is how an author believes a request is form-encoded when it is not."""
        script = _post_script(method="GET", body_encoding="form")
        with pytest.raises(RecipeError, match="only meaningful on a POST"):
            validate_recipe(script)

    def test_a_nested_form_body_is_rejected(self) -> None:
        """The half that actually bites: ``merge_body_params`` sets the cursor at
        whatever depth it finds the name, so a nested form body would page correctly in
        the recipe and not at all on the wire — every page would be page one."""
        script = _post_script(
            body_encoding="form",
            body={"variables": {"page": 1}, "doc_id": "1"},
        )
        with pytest.raises(RecipeError, match="flat name=value pairs"):
            validate_recipe(script)

    def test_a_boolean_form_value_is_rejected(self) -> None:
        """``True`` urlencodes to the Python spelling ``True``, which no board reads."""
        with pytest.raises(RecipeError, match="flat name=value pairs"):
            validate_recipe(_post_script(body_encoding="form",
                                         body={"server_timestamps": True}))


class TestBodyEncodingOnTheWire:
    """What ``_request`` actually sends. Measured live on metacareers.com: form → 200
    with 876 records, JSON → 400, same session, one key changed."""

    PAYLOAD = {"jobs": [{"id": "1", "title": "Engineer", "u": "https://b.test/1"}]}

    def _capture(self, script: dict[str, Any]) -> httpx.Request:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=self.PAYLOAD)

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            run_recipe(script, http)
        return seen[0]

    def test_form_puts_the_fields_on_the_wire_urlencoded(self) -> None:
        request = self._capture(_post_script(body_encoding="form"))
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert request.content == b"doc_id=27129360303422352&variables=%7B%7D"

    def test_json_is_byte_for_byte_what_it_always_was(self) -> None:
        request = self._capture(_post_script())
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {
            "doc_id": "27129360303422352", "variables": "{}",
        }

    def test_form_overrides_a_captured_json_content_type(self) -> None:
        """The one header that may not disagree with the encoding. A board whose capture
        recorded ``application/json`` would otherwise get form bytes under a JSON
        content-type, which is a 400 everywhere."""
        request = self._capture(_post_script(
            body_encoding="form", headers={"content-type": "application/json"},
        ))
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"

    def test_the_pagination_cursor_is_stringified_into_the_form(self) -> None:
        """The cursor arrives as an ``int``; a form body is strings."""
        assert _form_fields({"doc_id": "1", "offset": 25}) == {
            "doc_id": "1", "offset": "25",
        }


class TestBodyEncodingReachesTheBrowserTier:
    """``browser_fetch`` has its own executor, and it is the tier that needs this most:
    metacareers.com answers this request at all ONLY from inside its own origin.
    Measured through the real ``run_browser_fetch`` on 2026-08-30 — ``form`` returned
    876 rows in 5.4s, the default ``json`` raised ``HTTP 400``."""

    def test_the_parent_forwards_the_encoding_to_the_child(self) -> None:
        from api.services.browser_fetch.runner import build_subprocess_plan
        from api.services.recipe_runner import parse_plan

        script = {
            "script_version": 1, "transport": "browser_fetch",
            "origin_url": "https://www.metacareers.com/jobsearch/",
            "expected_min_jobs": 1,
            "steps": [
                {"op": "fetch", "method": "POST",
                 "url": "https://www.metacareers.com/graphql",
                 "headers": {}, "body": {"doc_id": "1"}, "body_encoding": "form"},
                {"op": "extract_json_path", "records_path": "data.all_jobs",
                 "fields": {"id": "id", "title": "title", "url": "u"}},
            ],
            "oracle": {"kind": "none"},
        }
        validate_recipe(script, transport="browser_fetch", oracle_kind="none")
        plan = build_subprocess_plan(script, parse_plan(script))
        assert plan["body_encoding"] == "form"

    def test_a_recipe_without_the_key_still_says_json_to_the_child(self) -> None:
        from api.services.browser_fetch.runner import build_subprocess_plan
        from api.services.recipe_runner import parse_plan

        script = {
            "script_version": 1, "transport": "browser_fetch",
            "origin_url": "https://lifeattiktok.com/search",
            "expected_min_jobs": 1,
            "steps": [
                {"op": "fetch", "method": "POST",
                 "url": "https://api.lifeattiktok.com/api/v1/search/job/posts",
                 "headers": {}, "body": {"offset": 0}},
                {"op": "extract_json_path", "records_path": "data.job_post_list",
                 "fields": {"id": "id", "title": "title", "url": "u"}},
            ],
            "oracle": {"kind": "none"},
        }
        plan = build_subprocess_plan(script, parse_plan(script))
        assert plan["body_encoding"] == "json", (
            "every stored browser_fetch recipe predates this key and must keep its "
            "current meaning exactly"
        )

    def test_the_in_page_fetch_carries_both_branches(self) -> None:
        """The JS is a string in a subprocess-only module, so it is pinned the same way
        ``redirect: 'error'`` is — by reading it in the child."""
        code = (
            "from api.services.browser_fetch._browser_fetch_main import _FETCH_JS\n"
            "print('form' if \"new URLSearchParams(body)\" in _FETCH_JS else 'MISSING')\n"
            "print('json' if 'JSON.stringify(body)' in _FETCH_JS else 'MISSING')\n"
            "print('ct' if \"'application/x-www-form-urlencoded'\" in _FETCH_JS"
            " else 'MISSING')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(_BACKEND),
            env={"PYTHONPATH": f"{_REPO_ROOT}:{_BACKEND}", "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["form", "json", "ct"]


# ==========================================================================
# GAP 3 — extract_embedded_island source = "rsc_flight"
# ==========================================================================

def _rsc_script(**overrides: Any) -> dict[str, Any]:
    script: dict[str, Any] = {
        "script_version": 1,
        "transport": "http_html",
        "expected_min_jobs": 1,
        "base_url": "https://jobs.deel.com",
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://jobs.deel.com/klarna",
             "headers": {}},
            {"op": "extract_embedded_island", "selector": "script",
             "source": "rsc_flight", "records_path": "9.3.jobPostings",
             "fields": {"id": "id", "title": "title",
                        "url": "https://jobs.deel.com/klarna/job-details/{id}/overview",
                        "location": "job.jobLocations.0.location.name"}},
            {"op": "dedupe_key", "field": "id"},
            {"op": "assert_unique", "field": "id"},
        ],
        "oracle": {"kind": "none"},
    }
    script.update(overrides)
    return script


class TestRscFlightSchema:
    def test_the_source_is_admitted_on_http_html(self) -> None:
        assert validate_recipe(_rsc_script()) is not None

    def test_no_attribute_is_required_for_it(self) -> None:
        script = _rsc_script()
        assert "attribute" not in script["steps"][1]
        validate_recipe(script)

    @pytest.mark.parametrize("transport", ["http_json", "browser_fetch"])
    def test_it_is_rejected_on_a_transport_that_never_sees_the_document(
        self, transport: str
    ) -> None:
        """``http_json`` feeds its extraction a parsed JSON body and the browser child
        returns raw JSON bodies — on either one this source names a document that never
        arrives, and the failure at 3am would name a selector, not the real problem."""
        script = _rsc_script(transport=transport)
        if transport == "browser_fetch":
            script["origin_url"] = "https://jobs.deel.com/klarna"
        with pytest.raises(RecipeError, match="rsc_flight"):
            validate_recipe(script)

    def test_an_unknown_source_is_still_rejected(self) -> None:
        script = _rsc_script()
        script["steps"][1]["source"] = "flight"
        with pytest.raises(RecipeError, match="source must be one of"):
            validate_recipe(script)


class TestRscFlightRowFraming:
    """**The byte length is the whole parser.** ``T<hexlen>,`` counts UTF-8 BYTES, and
    the blobs it delimits are job descriptions full of typographic quotes. Framing on
    CHARACTERS lands mid-blob, the parse loses sync with the row grammar, and the row
    holding the jobs is never seen — measured: 0 job arrays vs all 81."""

    #: A description blob with typographic quotes: 4 bytes longer than it is characters,
    #: which is exactly the desync a character-framed parser walks into.
    TEXT = "we call it “work”, and it’s fun"
    STREAM = (
        '0:{"kind":"root"}\n'
        f'1:T{len(TEXT.encode()):x},{TEXT}\n'
        '9:[null,null,null,{"jobPostings":[{"id":"a","title":"Engineer"}]}]\n'
    )

    @staticmethod
    def _scripts(stream: str, *, at: int | None = None) -> list[str]:
        """``stream`` as the ``<script>`` bodies a Next.js page would actually carry."""
        parts = [stream] if at is None else [stream[:at], stream[at:]]
        return [
            f"self.__next_f.push([1,{json.dumps(part)}])" for part in parts
        ]

    def _doc(self, stream: str) -> str:
        return ("<html><body>"
                + "".join(f"<script>{s}</script>" for s in self._scripts(stream, at=30))
                + "</body></html>")

    def test_the_fixture_really_is_byte_longer_than_it_is_char_long(self) -> None:
        """The premise, asserted rather than assumed — without it the case proves
        nothing, because char-framing and byte-framing would agree."""
        assert len(self.TEXT.encode()) == len(self.TEXT) + 6

    def test_a_multibyte_text_row_does_not_desync_the_rows_after_it(self) -> None:
        rows = parse_rsc_flight(self._scripts(self.STREAM))
        assert set(rows) == {"0", "9"}, (
            f"the row after the multibyte T row was lost: {sorted(rows)}"
        )
        assert rows["9"][3]["jobPostings"][0]["title"] == "Engineer"

    def test_chunks_that_split_mid_token_still_concatenate(self) -> None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(self._doc(self.STREAM), "html.parser")
        rows = parse_rsc_flight([n.get_text() for n in soup.select("script")])
        assert rows["9"][3]["jobPostings"][0]["id"] == "a"

    def test_an_unparseable_stream_yields_nothing_rather_than_raising(self) -> None:
        """One place decides that a board is unreadable, and it is the caller's
        ``records_path`` dig — not a parser that raises from three frames down."""
        assert parse_rsc_flight(["<html>not a flight stream at all</html>"]) == {}

    def test_a_row_marker_INSIDE_a_text_row_is_not_a_row(self) -> None:
        """Why the declared length is CONSUMED rather than merely skipped.

        A job description can contain anything, newlines included — and ``9:[...]`` is
        four characters. A parser that resumes scanning inside a text blob reads that as
        row 9 and, because rows are first-write-wins, the board's REAL row 9 is then
        ignored: a wrong answer rather than a loud failure, which is the one outcome this
        module may never produce.
        """
        poison = 'first line\n9:["not the jobs at all"]\nlast line'
        stream = (
            f'1:T{len(poison.encode()):x},{poison}\n'
            '9:[null,null,null,{"jobPostings":[{"id":"a","title":"Engineer"}]}]\n'
        )
        rows = parse_rsc_flight(self._scripts(stream))
        assert isinstance(rows.get("9"), list), (
            f"row 9 was read out of the middle of a description: {rows.get('9')!r}"
        )
        assert rows["9"][3]["jobPostings"][0]["title"] == "Engineer"

    def test_text_rows_are_framed_but_not_returned(self) -> None:
        """The ``$<id>``-referenced description blobs are the element-tree half of RSC
        that Stage 2 deliberately skips (Roblox's CloudFront JSON is a better source)."""
        assert "1" not in parse_rsc_flight(self._scripts(self.STREAM))


class TestRscFlightOnRealKlarnaBytes:
    """The real board, hermetically.

    ``fixtures/captures/klarna_rsc_flight.html`` is jobs.deel.com/klarna as served on
    2026-08-30, with every ``T`` description row truncated to its first 300 BYTES (hex
    length recomputed) so the document is reviewable. Row ids, the row grammar, all 81
    postings and the multibyte byte-framing are verbatim. A live case is deliberately
    not the vehicle: Klarna ships a redesign whenever it likes, and this pins the
    PARSER, not their hiring.
    """

    def _run(self) -> Any:
        markup = (_CAPTURES / "klarna_rsc_flight.html").read_text()
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, text=markup, headers={"content-type": "text/html"}
            )
        )
        with httpx.Client(transport=transport) as http:
            return run_recipe(_rsc_script(), http)

    def test_the_whole_board_comes_out_of_the_flight_stream(self) -> None:
        rows, evidence = self._run()
        assert len(rows) == 81, (
            f"Klarna publishes 81 postings at 9.3.jobPostings; got {len(rows)}"
        )
        assert len({r["id"] for r in rows}) == 81
        assert all(r["title"] for r in rows)
        assert rows[0]["url"].startswith("https://jobs.deel.com/klarna/job-details/")
        assert evidence.terminated_cleanly is True

    def test_the_nested_location_resolves_too(self) -> None:
        """``job.jobLocations.0.location.name`` — the leaf, not the container. The
        stream is real JSON once framed, so every existing field primitive works on it."""
        rows, _ = self._run()
        assert rows[0]["location"] == "Sweden"

    def test_a_selector_that_matches_no_script_fails_loudly(self) -> None:
        markup = (_CAPTURES / "klarna_rsc_flight.html").read_text()
        script = _rsc_script()
        script["steps"][1]["selector"] = "script#__NEXT_DATA__"
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text=markup)
        )
        with httpx.Client(transport=transport) as http:
            with pytest.raises(RecipeExecutionError, match="matched nothing"):
                run_recipe(script, http)

    def test_a_records_path_into_an_element_tree_is_a_loud_failure(self) -> None:
        """The half Stage 2 skipped, and how it behaves when someone tries it anyway:
        a FAILED run that names the path, never a wrong answer."""
        markup = (_CAPTURES / "klarna_rsc_flight.html").read_text()
        script = _rsc_script()
        script["steps"][1]["records_path"] = "9.3.children.0.jobs"
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text=markup)
        )
        with httpx.Client(transport=transport) as http:
            with pytest.raises(RecipeExecutionError, match="did not resolve"):
                run_recipe(script, http)


# ==========================================================================
# DISCOVERY CAN EMIT IT — the half that decides whether a primitive is alive
# ==========================================================================
#
# ``http_html`` and ``extract_css`` sat validated-but-never-emitted for weeks. A
# primitive the schema admits and discovery never writes down is dead code, so each
# section above has a counterpart here.

def _candidate_over(records: list[dict[str, Any]]) -> Any:
    from api.services.capture.network_capture import CapturedResponse
    from api.services.capture.request_selector import prefilter_candidates

    body = json.dumps({"jobs": records})
    (candidate,) = prefilter_candidates([CapturedResponse(
        url="https://board.test/api/openings", method="GET", status=200,
        content_type="application/json", request_headers={}, post_data=None,
        body=body, truncated=False, body_bytes=len(body),
    )])
    return candidate


#: A board that publishes a link and no title — the shape both Bloomberg and Citadel
#: are, and the shape the selector prompt now tells the model it may map title onto.
_LINKS_ONLY = [
    {"jobId": f"216{n}",
     "detailUrl": f"https://board.test/careers/JobDetail/Senior-Engineer-Team-{n}/216{n}"}
    for n in range(40, 52)
]


class TestDiscoveryEmitsTheFormEncoding:
    """GAP 2's emit half. ``_post_body`` used to refuse a form capture outright ("the
    jobs request POSTs a non-JSON body we cannot replay"), so no recipe could exist for
    such a board however the schema was widened."""

    @staticmethod
    def _post_candidate(post_data: str, content_type: str) -> Any:
        from api.services.capture.network_capture import CapturedResponse
        from api.services.capture.request_selector import prefilter_candidates

        body = json.dumps({"data": {"all_jobs": [
            {"id": str(n), "title": f"Engineer {n}"} for n in range(12)
        ]}})
        (candidate,) = prefilter_candidates([CapturedResponse(
            url="https://board.test/graphql", method="POST", status=200,
            content_type="application/json",
            request_headers={"content-type": content_type},
            post_data=post_data, body=body, truncated=False, body_bytes=len(body),
        )])
        return candidate

    def _synthesize(self, post_data: str, content_type: str) -> dict[str, Any]:
        from api.services.capture.discover import synthesize_recipe
        from api.services.capture.request_selector import RequestSelection

        return synthesize_recipe(
            self._post_candidate(post_data, content_type),
            RequestSelection(
                chosen_request_index=0, records_path="data.all_jobs",
                field_map={"id": "id", "title": "title",
                           "url": "https://board.test/jobs/{id}/"},
                pagination=None,
            ),
            transport="http_json",
            origin_url="https://board.test/jobsearch/",
        )

    def test_a_form_capture_becomes_a_form_recipe(self) -> None:
        script = self._synthesize(
            "doc_id=27129360303422352&variables=%7B%7D&server_timestamps=true",
            "application/x-www-form-urlencoded",
        )
        fetch = script["steps"][0]
        assert fetch["body_encoding"] == "form"
        assert fetch["body"] == {
            "doc_id": "27129360303422352", "variables": "{}",
            "server_timestamps": "true",
        }

    def test_a_json_capture_is_byte_identical_to_before(self) -> None:
        """No key at all on the JSON path — the diff between two nightly recipes has to
        stay readable, and an inert ``"body_encoding": "json"`` on every stored board
        would be noise forever."""
        script = self._synthesize('{"doc_id": "1"}', "application/json")
        assert "body_encoding" not in script["steps"][0]
        assert script["steps"][0]["body"] == {"doc_id": "1"}

    def test_the_encoding_is_read_off_the_header_not_sniffed_from_the_body(self) -> None:
        """Almost any string parses as a degenerate form, so sniffing would turn a body
        we cannot read into one we MISREAD."""
        from api.services.capture.discover import _Refusal

        with pytest.raises(_Refusal):
            self._synthesize("this is not json at all", "application/json")

    def test_repeated_form_field_names_are_refused_rather_than_dropped(self) -> None:
        from api.services.capture.discover import _Refusal

        with pytest.raises(_Refusal, match="repeated field names"):
            self._synthesize("tag=a&tag=b&doc_id=1",
                             "application/x-www-form-urlencoded")


class TestDiscoveryEmitsTheRscFlightSource:
    """GAP 3's emit half. The capture child looks for ``<script type="application/json">``
    islands and an App-Router page has none — it has a STREAM — so the whole class was
    invisible to ``island_candidates`` and Klarna produced zero candidates."""

    @staticmethod
    def _captured(markup: str) -> Any:
        from dataclasses import dataclass, field as dc_field

        @dataclass
        class _Capture:
            server_html: str
            server_html_url: str = "https://jobs.deel.com/klarna"
            final_url: str = "https://jobs.deel.com/klarna"
            islands: tuple = dc_field(default_factory=tuple)

        return _Capture(markup)

    def test_the_flight_stream_becomes_a_candidate(self) -> None:
        from api.services.capture.sources import document_candidates

        markup = (_CAPTURES / "klarna_rsc_flight.html").read_text()
        (candidate,) = document_candidates(
            self._captured(markup), "jobs.deel.com", "https://jobs.deel.com/klarna"
        )
        assert candidate.records_path == "9.3.jobPostings"
        assert candidate.record_count == 81
        assert candidate.html.source == "rsc_flight"

    def test_a_page_with_no_flight_stream_is_untouched(self) -> None:
        """The regression bar: this must add nothing and reorder nothing anywhere else."""
        from api.services.capture.sources import rsc_candidate

        plain = self._captured(
            "<html><body><a href='/careers/jobs/1'>Engineer</a>"
            "<script>console.log(1)</script></body></html>"
        )
        assert rsc_candidate(plain, "https://b.test/careers") is None

    def test_synthesis_turns_it_into_an_http_html_rsc_recipe(self) -> None:
        from api.services.capture.discover import synthesize_recipe
        from api.services.capture.sources import rsc_candidate
        from api.services.capture.request_selector import RequestSelection

        markup = (_CAPTURES / "klarna_rsc_flight.html").read_text()
        candidate = rsc_candidate(self._captured(markup),
                                  "https://jobs.deel.com/klarna")
        script = synthesize_recipe(
            candidate,
            RequestSelection(
                chosen_request_index=0, records_path="9.3.jobPostings",
                field_map={
                    "id": "id", "title": "title",
                    "url": "https://jobs.deel.com/klarna/job-details/{id}/overview",
                },
                pagination=None,
            ),
            transport="http_html",
            origin_url="https://jobs.deel.com/klarna",
        )
        (extract,) = [s for s in script["steps"] if s["op"].startswith("extract_")]
        assert extract["op"] == "extract_embedded_island"
        assert extract["source"] == "rsc_flight"
        assert "attribute" not in extract
        assert script["steps"][0]["url"] == "https://jobs.deel.com/klarna"
        validate_recipe(script, transport="http_html")

    def test_the_synthesised_recipe_actually_replays(self) -> None:
        """The whole point of the emit half: what discovery writes down must be what the
        agent-free runner can read back. Same fixture, both directions."""
        from api.services.capture.discover import synthesize_recipe
        from api.services.capture.request_selector import RequestSelection
        from api.services.capture.sources import rsc_candidate

        markup = (_CAPTURES / "klarna_rsc_flight.html").read_text()
        script = synthesize_recipe(
            rsc_candidate(self._captured(markup), "https://jobs.deel.com/klarna"),
            RequestSelection(
                chosen_request_index=0, records_path="9.3.jobPostings",
                field_map={
                    "id": "id", "title": "title",
                    "url": "https://jobs.deel.com/klarna/job-details/{id}/overview",
                },
                pagination=None,
            ),
            transport="http_html",
            origin_url="https://jobs.deel.com/klarna",
        )
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text=markup)
        )
        with httpx.Client(transport=transport) as http:
            rows, _ = run_recipe(script, http)
        assert len(rows) == 81


class TestDiscoveryEmitsTheTitleTransform:
    def test_the_derivation_fires_on_a_links_only_board(self) -> None:
        from api.services.capture.request_selector import derive_title_from_url

        derived = derive_title_from_url(_LINKS_ONLY, {
            "id": "jobId", "title": "detailUrl", "url": "detailUrl",
        })
        assert derived is not None
        assert derived.pattern == r"/([^/?#]+)/\d+/?$"
        assert derived.unslug is True

    def test_it_does_not_fire_on_a_board_whose_title_is_a_title(self) -> None:
        """The regression that matters most here: every board we read today must be
        byte-identical after this change."""
        from api.services.capture.request_selector import derive_title_from_url

        records = [
            {"id": str(n), "title": f"Staff Engineer, Platform {n}",
             "url": f"https://board.test/jobs/staff-engineer-platform-{n}"}
            for n in range(12)
        ]
        assert derive_title_from_url(records, {
            "id": "id", "title": "title", "url": "url",
        }) is None, (
            "the URL slug here WOULD read as a plausible title — the trigger has to be "
            "'the mapped title is a link', not 'the url has a slug', or every board on "
            "the corpus gets a derived title over the one it published"
        )

    def test_it_refuses_a_pattern_that_only_works_on_most_of_the_sample(self) -> None:
        """100% of the sample, not a majority: as of Stage 2 an unmatched required
        field is a FAILED run, so a nine-in-ten pattern takes the board down nightly
        instead of mis-titling one row."""
        from api.services.capture.request_selector import derive_title_from_url

        records = _LINKS_ONLY + [{"jobId": "999",
                                  "detailUrl": "https://board.test/careers/AgentCreate"}]
        assert derive_title_from_url(records, {
            "id": "jobId", "title": "detailUrl", "url": "detailUrl",
        }) is None

    def test_it_refuses_a_capture_that_is_the_same_word_on_every_job(self) -> None:
        """One value for the whole board is a path constant, not a title."""
        from api.services.capture.request_selector import derive_title_from_url

        records = [{"jobId": str(n), "u": f"https://board.test/careers/details/{n}/"}
                   for n in range(8)]
        derived = derive_title_from_url(records, {
            "id": "jobId", "title": "u", "url": "u",
        })
        assert derived is None, (
            "the last segment here is the numeric id; unslugging it yields no letters "
            f"and must not become a title (got {derived})"
        )

    def test_the_selection_builder_carries_it(self) -> None:
        """Through the REAL ``_to_selection``, so the derivation cannot be skipped by
        the path a real model answer actually takes."""
        from api.services.capture.request_selector import (
            _FieldMap,
            _SelectionEnvelope,
            _to_selection,
        )

        selection = _to_selection(
            _SelectionEnvelope(
                is_jobs_feed=True, confidence="high", records_path="jobs",
                field_map=_FieldMap(id="jobId", title="detailUrl", url="detailUrl"),
            ),
            _candidate_over(_LINKS_ONLY),
        )
        assert selection.title_from_url is not None

    def test_synthesis_writes_the_step_into_the_recipe(self) -> None:
        from api.services.capture.discover import synthesize_recipe
        from api.services.capture.request_selector import (
            RequestSelection,
            TitleFromUrl,
        )

        script = synthesize_recipe(
            _candidate_over(_LINKS_ONLY),
            RequestSelection(
                chosen_request_index=0,
                records_path="jobs",
                field_map={"id": "jobId", "title": "detailUrl", "url": "detailUrl"},
                pagination=None,
                title_from_url=TitleFromUrl(pattern=r"/([^/?#]+)/\d+/?$"),
            ),
            transport="http_json",
            origin_url="https://board.test/careers",
        )
        (transform,) = [s for s in script["steps"] if s["op"] == "transform"]
        assert transform == {
            "op": "transform", "field": "title", "kind": "regex_capture",
            "from": "url", "pattern": r"/([^/?#]+)/\d+/?$", "unslug": True,
        }
        assert script["steps"].index(transform) > next(
            i for i, s in enumerate(script["steps"]) if s["op"].startswith("extract_")
        ), "shaping must see the MAPPED row, so the step goes after the extraction"

    def test_a_normal_board_still_gets_no_transform_step(self) -> None:
        from api.services.capture.discover import synthesize_recipe
        from api.services.capture.request_selector import RequestSelection

        records = [{"id": str(n), "title": f"Engineer {n}",
                    "url": f"https://board.test/jobs/{n}"} for n in range(12)]
        script = synthesize_recipe(
            _candidate_over(records),
            RequestSelection(
                chosen_request_index=0, records_path="jobs",
                field_map={"id": "id", "title": "title", "url": "url"},
                pagination=None,
            ),
            transport="http_json",
            origin_url="https://board.test/careers",
        )
        assert [s for s in script["steps"] if s["op"] == "transform"] == []

    def test_the_prompt_tells_the_model_the_shape_is_allowed(self) -> None:
        """The other half of "discovery can emit it": the model has to know that
        pointing ``title`` at a link field is a legitimate answer for such a board, and
        that it is NOT one anywhere else."""
        from api.services.capture.request_selector import SYSTEM_PROMPT

        assert "readable slug" in SYSTEM_PROMPT
        assert "Never do this when a real title field exists" in SYSTEM_PROMPT


# ==========================================================================
# The vocabulary is still CLOSED
# ==========================================================================

def test_stage_two_did_not_open_the_phase_four_door() -> None:
    """Three additions, zero new escape hatches: the browser transports and ops are
    still rejected, and ``transform`` is still a named kind, not an expression."""
    script = _html_script()
    for bad in ("page_fetch", "dom", "browser_dom"):
        drifted = copy.deepcopy(script)
        drifted["transport"] = bad
        with pytest.raises(RecipeError, match="Phase 4"):
            validate_recipe(drifted)
    drifted = copy.deepcopy(script)
    drifted["steps"][2]["kind"] = "eval"
    with pytest.raises(RecipeError, match="transform.kind must be one of"):
        validate_recipe(drifted)
