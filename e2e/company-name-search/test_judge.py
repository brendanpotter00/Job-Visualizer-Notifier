"""What the judge does when the endpoint answers NOTHING. Costs $0, runs offline.

THE HOLE THIS FILE EXISTS FOR. ``must_not`` is checked against the strings the user
is being OFFERED. An endpoint that offers nothing produces none of them, so the loop
body never runs and the case reports PASS. Four cases in ``cases.toml`` were shaped
exactly like that — `metabase`, `poke`, `gm`, `hp` — which means a ``search-by-name``
that returned ``{"candidates": [], "careersUrl": null}`` for every input would have
printed **4 of 21 passing**. This suite was written because "4 for 4, live" was
reported and was false; a hole that reproduces that report inside the harness is the
one bug it may not have.

The fix is structural (``Case.has_positive_expectation`` + the vacuous rule in
``judge``), so what is pinned here is the INVARIANT rather than those four keys:

    against a dead endpoint, the only cases that may pass are the ones that
    explicitly expect silence.

Run it — free, no backend, no Browserbase:

    .venv/bin/python -m pytest e2e/company-name-search/test_judge.py -q

Not wired into CI, for the same reason the suite it guards is not: ``e2e/`` is
deliberately human-run. It needs nothing but the file next to it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from intent_test import (  # noqa: E402  (path shim above must run first)
    Answer,
    Case,
    judge,
    load_cases,
    read_answer,
)

#: EXACTLY what a completely dead endpoint returns — the body from the review, not a
#: hand-built ``Answer``, so the read path is proved along with the judging.
DEAD_ENDPOINT_BODY: dict[str, Any] = {"candidates": [], "careersUrl": None}

#: The four cases the review measured as passing against that body.
WAS_VACUOUS = ("metabase", "poke", "gm", "hp")


@pytest.fixture(scope="module")
def cases() -> dict[str, Case]:
    return {c.key: c for c in load_cases(_HERE / "cases.toml")}


@pytest.fixture()
def nothing() -> Answer:
    answer = read_answer(DEAD_ENDPOINT_BODY)
    assert not answer.answered, "the fixture is meant to be a dead endpoint"
    return answer


# ── the invariant ────────────────────────────────────────────────────────────


def test_a_dead_endpoint_can_only_pass_cases_that_ask_for_silence(
    cases: dict[str, Case], nothing: Answer
) -> None:
    """THE ONE THAT MATTERS, and it is written over the whole file rather than a
    list of keys — a case added tomorrow is covered without anyone remembering."""
    survivors = {k for k, c in cases.items() if not judge(c, nothing)}
    expected = {k for k, c in cases.items() if c.spec.get("nothing")}
    assert survivors == expected, (
        f"cases that pass against {DEAD_ENDPOINT_BODY} without asking for silence: "
        f"{sorted(survivors - expected)}"
    )


@pytest.mark.parametrize("key", WAS_VACUOUS)
def test_the_four_negative_only_cases_no_longer_pass_on_silence(
    cases: dict[str, Case], nothing: Answer, key: str
) -> None:
    """The four from the review. Two routes to the same place, both honest:

    * `metabase`, `gm`, `hp` now FAIL — they assert only what must not come back,
      and there is nothing to check that against.
    * `poke` now says ``nothing = true``. Silence is the right answer for a name
      whose best result is a poke-bowl chain, so it passes ON PURPOSE and says why
      in the case file, instead of passing because the check had nothing to look at.
    """
    case = cases[key]
    reasons = judge(case, nothing)
    if case.spec.get("nothing"):
        assert not reasons, f"{key} asserts silence, so silence must satisfy it"
    else:
        assert reasons, f"{key} still passes against a dead endpoint"
        assert any("vacuous" in r for r in reasons), reasons


def test_metabase_is_caught_by_the_structural_rule_alone(
    cases: dict[str, Case], nothing: Answer
) -> None:
    """No ``must_answer`` was added to `metabase`, deliberately: it is the case that
    proves the SHAPE rule fires on its own, not the four extra lines."""
    case = cases["metabase"]
    assert not case.has_positive_expectation
    assert "must_answer" not in case.spec
    reasons = judge(case, nothing)
    assert len(reasons) == 1 and "vacuous" in reasons[0], reasons


# ── the shape rule, on cases that are not in the file ────────────────────────


def _case(key: str, **spec: Any) -> Case:
    return Case(key=key, input="X", spec={"input": "X", "truth": "owner:x", **spec})


def test_a_brand_new_one_line_must_not_case_is_covered(nothing: Answer) -> None:
    """The whole reason the fix is not four ``must_answer`` lines."""
    assert judge(_case("newcomer", must_not=["poki"]), nothing)


def test_must_answer_still_works_and_is_not_what_is_being_relied_on(
    nothing: Answer,
) -> None:
    reasons = judge(_case("explicit", must_not=["x"], must_answer=True), nothing)
    assert any("vacuous" in r for r in reasons)
    assert any("dead end" in r for r in reasons)


def test_a_positive_expectation_is_judged_on_its_own_terms(nothing: Answer) -> None:
    """A case that says what a right answer looks like was never vacuous, and must
    not now collect a second, confusing reason for the same failure."""
    reasons = judge(_case("boardish", board="workday:x"), nothing)
    assert reasons == ["no auto-addable board workday:x"]


def test_expecting_silence_is_still_falsifiable() -> None:
    """``nothing = true`` is an assertion, not an exemption: offer something and it
    fails. Without this, the opt-out for `poke`/`facebook` would be a new hole."""
    answered = read_answer(
        {"candidates": [], "careersUrl": "https://pokemoto.com/careers"}
    )
    reasons = judge(_case("silent", nothing=True), answered)
    assert any("honest dead end" in r for r in reasons), reasons


# ── the known-limitation marker ──────────────────────────────────────────────


def test_the_known_limitation_case_still_runs_and_still_asserts(
    cases: dict[str, Case], nothing: Answer
) -> None:
    """`citadel` is excused from the PASS LINE, never from being judged. Against a
    dead endpoint it fails like anything else — the gap it records is "we answer
    with the wrong company", and an empty answer must not hide behind it."""
    citadel = cases["citadel"]
    assert citadel.known_limitation
    assert judge(citadel, nothing)


def test_the_wrong_entity_is_what_citadel_fails_on(cases: dict[str, Case]) -> None:
    """The measured behaviour, as a fixture: the offer is a different legal entity."""
    offered = read_answer(
        {
            "candidates": [],
            "careersUrl": "https://www.citadelsecurities.com/careers/open-positions/",
        }
    )
    reasons = judge(cases["citadel"], offered)
    assert any("citadelsecurities" in r for r in reasons), reasons
