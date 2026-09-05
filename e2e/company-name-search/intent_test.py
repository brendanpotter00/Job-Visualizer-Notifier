#!/usr/bin/env python3
"""The intent test for "type a company name, get its job board".

WHY THIS FILE EXISTS, stated once so it cannot be lost.

This feature was reported as "4 for 4, live" on Atlassian / GitHub / AMD / Oracle.
Both halves of that report were wrong, in two different ways, and this harness is
shaped by both:

1. **The wrong thing was tested.** The script called ``pick_careers_url`` directly.
   The UI calls ``POST /api/companies/search-by-name``, which runs a probe phase, a
   20-second budget, a published-company check and ``_careers_fallback`` before the
   picker is ever reached. A green result from the inner function says nothing at
   all about the endpoint.
   → So this harness only ever speaks HTTP to the real endpoint. There is no import
     of a service module anywhere in it, and there never may be.

2. **The ground truth was invented.** Oracle was scored correct for returning
   ``oracle.com/careers/``. The owner says the real board is
   ``careers.oracle.com/en/sites/jobsearch/jobs``. Oracle had been failing the whole
   time and was counted as a pass, which makes the "16/28" headline unreliable by an
   unknown amount.
   → So every expectation carries a ``truth`` provenance field, an unverified one can
     never count towards the pass line, and every careers URL — recorded OR returned
     — must be job-list-shaped.

WHAT "CORRECT" MEANS, and why a marketing page cannot satisfy it.

There are only three channels this endpoint can answer on, and each has its own
proof:

* an **ATS board** (``candidates[].autoAddable``) — proved by the ATS token matching
  AND the real ATS client having returned ``jobCount >= min_jobs``. Nothing that is
  not an actual job board can produce either half.
* an **already-published match** (``alreadyPublic``) — proved by the company id.
* a **careers URL** (``careersUrl``) — proved by exact URL match against reviewed
  ground truth AND by :func:`is_job_list_shaped`, which requires a job-list path
  segment. ``oracle.com/careers/``, ``amd.com/en/corporate/careers.html`` and
  ``careers.airbnb.com/`` all fail that rule; every known-good answer passes it.

That last rule is the load-bearing one. It is enforced in BOTH directions — on the
value recorded in ``cases.toml`` (so a brochure cannot be written down as truth) and
on the value the endpoint actually returns (so a brochure cannot be returned as an
answer, even for a company nobody has established the right answer for yet).

SILENCE IS NOT A PASS. A case that says only what must NOT come back is satisfied by
an endpoint that answers nothing at all — the ``must_not`` check has no answer to
look at, so it never fires. Four cases were that shape, which means a completely dead
``search-by-name`` would have printed "4 of 21 passing" — the same false green,
reproduced inside the harness written to prevent it. :func:`judge` now fails any case
that asserts no POSITIVE expectation against an answer of nothing, and a case whose
right answer really is silence says ``nothing = true`` out loud.

A NOTE ON WHY A LIVE "does this page have jobs on it" PROBE IS NOT USED. It was
measured and it does not work. Fetched plain, ``careers.oracle.com/en/sites/jobsearch/jobs``
— the CORRECT answer — yields 6 characters of text (an empty SPA shell), while
``www.oracle.com/careers/`` 403s and ``atlassian.com/company/careers`` (the wrong
answer) yields 27,737 characters, five times its own job list. A content probe would
have inverted several cases. The structural URL rule separates the same corpus
cleanly and costs nothing.

NON-DETERMINISM IS FIRST CLASS. Browserbase Search results vary between calls:
Atlassian passed 3/3 in one sitting while the owner watched it fail. ``--runs N``
repeats every case, and a case that does not hold across all N runs is reported
FLAKY, never PASS.

COST. Every case spends real money — $0.007 per Browserbase Search call, one call
per search plus a second one whenever the careers fallback fires. The run prints the
count and the dollar figure, and refuses to start work it cannot pay for under
``--max-searches``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

#: Browserbase Search list price, verified against the vendor's own page and
#: recorded in COMPANY-NAME-SEARCH-EVALUATION.md §6. Flat per CALL, regardless of
#: how many results come back.
USD_PER_SEARCH = 0.007

DEFAULT_BASE_URL = "http://127.0.0.1:8202"


# ─────────────────────────────────────────────────────────────────────────────
# The job-list shape rule — the anti-marketing-page gate
# ─────────────────────────────────────────────────────────────────────────────

#: A path segment that means "a collection of open roles" rather than "a page about
#: working here". Deliberately a closed vocabulary of LIST words: `careers`,
#: `company`, `about`, `working-here` and friends are absent on purpose, because
#: those are exactly what a brochure's URL is made of.
_JOB_LIST_SEGMENT = re.compile(
    r"^(?:"
    r"jobs?|job[-_]?search|jobsearch|job[-_]?listings?|joblist"
    r"|all[-_]?jobs|open[-_]?jobs|job[-_]?openings|openings"
    r"|open[-_]?roles|roles|open[-_]?positions|positions|vacancies"
    r"|opportunities|open[-_]?opportunities|search|search[-_]?results"
    r")$"
)

#: Extensions a careers page wears while still being a page rather than a list —
#: stripped before the segment test so `careers.html` is judged as `careers`.
_PAGE_EXTENSION = re.compile(r"\.(?:html?|aspx|php|jsp)$", re.IGNORECASE)

#: A HOST whose first label already says "this whole site is the job list", so the
#: list page can legitimately sit at `/` — `jobs.sap.com/?locale=en_US`,
#: `jobs.cisco.com`, `job-boards.greenhouse.io/x`. Deliberately NOT `careers`:
#: `careers.airbnb.com/` and `www.oracle.com/careers/` are precisely the brochures
#: this rule exists to reject, and `careers.oracle.com` only earns its pass from the
#: `/jobsearch/jobs` in its path.
_JOB_LIST_HOST_LABEL = re.compile(r"^(?:jobs?|job[-_]boards?|jobsearch|joblist|apply)$")


def is_job_list_shaped(url: str) -> bool:
    """Does this URL's PATH claim to be a list of open roles?

    The whole anti-Oracle mechanism, and it is deliberately structural rather than
    content-based — see the module docstring for the measurement that ruled a
    content probe out.

    Measured against the corpus this suite covers:

    ======================================================  ======
    ``careers.oracle.com/en/sites/jobsearch/jobs``            True
    ``atlassian.com/company/careers/all-jobs``                True
    ``www.github.careers/careers-home/jobs``                  True
    ``careers.amd.com/careers-home/jobs``                     True
    ``www.metacareers.com/jobs``                              True
    ``www.oracle.com/careers/``                              False
    ``www.amd.com/en/corporate/careers.html``                False
    ``careers.airbnb.com/``                                  False
    ``www.atlassian.com/company/careers``                    False
    ``jobs.sap.com/?locale=en_US``                            True   (host rule)
    ======================================================  ======
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.netloc or "").lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    first_label = host.split(".")[0] if host else ""
    if _JOB_LIST_HOST_LABEL.match(first_label):
        return True
    for raw in (parts.path or "").split("/"):
        if not raw:
            continue
        seg = _PAGE_EXTENSION.sub("", raw).lower()
        if _JOB_LIST_SEGMENT.match(seg):
            return True
    return False


def normalize_url(url: str) -> str:
    """Compare URLs the way a human would: scheme/case/``www.``/trailing-slash blind.

    Query is KEPT. ``careers.oracle.com/…/jobs?lastSelectedFacet=…`` and the bare
    path are the same page, but a query that selects a different board is not, and
    guessing which is which here would be the harness inventing truth again. A case
    that needs a query records it; one that does not, does not.

    Path CASE is folded, which paths technically do not license. Every careers URL
    in this corpus is lowercase, and `jobs.ashbyhq.com/Crusoe` vs `/crusoe` failing
    the suite would be a false alarm about capitalisation dressed up as a product
    regression.
    """
    parts = urlsplit(url.strip())
    host = (parts.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parts.path or "").rstrip("/").lower()
    q = f"?{parts.query}" if parts.query else ""
    return f"{host}{path}{q}"


def host_of(url: str) -> str:
    host = (urlsplit(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


# ─────────────────────────────────────────────────────────────────────────────
# The case file
# ─────────────────────────────────────────────────────────────────────────────

_POSITIVE_KEYS = ("board", "careers_url", "careers_host", "already_public", "nothing")
_KNOWN_KEYS = set(_POSITIVE_KEYS) | {
    "input", "min_jobs", "match_kind", "must_not", "must_offer_careers",
    "must_answer", "must_not_aggregator", "max_searches", "allow_brochure",
    "known_limitation", "truth", "tags", "note",
}

#: Only these prefixes count as an expectation somebody actually established.
#: Anything else runs but can never count as a pass — see ``Case.truth_verified``.
_VERIFIED_TRUTH = ("owner:", "measured:")


class CaseFileError(Exception):
    """The case file is wrong. Raised at load time, before a cent is spent."""


@dataclass(frozen=True)
class Case:
    key: str
    input: str
    spec: dict[str, Any]

    @property
    def tags(self) -> list[str]:
        return list(self.spec.get("tags", []))

    @property
    def truth(self) -> str:
        return str(self.spec.get("truth", ""))

    @property
    def truth_verified(self) -> bool:
        return self.truth.startswith(_VERIFIED_TRUTH)

    @property
    def known_limitation(self) -> str:
        """WHY this case is expected to fail today, or ``""`` if it is not.

        A case wearing this still RUNS, is still judged, and its reasons are still
        printed in full under ``WHY:`` — the only thing it changes is that the gap
        it records cannot be mistaken for a regression, so it is reported on its own
        line instead of inside the N/M pass count. ``citadel`` is the case it exists
        for: the wrong-legal-entity match is real, measured, and fixing it means
        changing the name-matching rule, which is a change of its own with its own
        risk (``metabase``/``meta`` live on the same rule).

        It is a STRING and never a bare ``true`` so that the reason has to be
        written down by whoever decided it, right next to the case.
        """
        return str(self.spec.get("known_limitation", ""))

    @property
    def has_positive_expectation(self) -> bool:
        """Does this case say what a RIGHT answer looks like, at all?

        ``nothing = true`` counts: "the honest answer here is silence" is a claim
        about the right answer, and one the endpoint can fail. A case with none of
        these says only what must NOT come back, which is the shape that silence
        satisfies for free — see the vacuous rule in :func:`judge`.
        """
        return any(k in self.spec for k in _POSITIVE_KEYS)

    @property
    def weak(self) -> bool:
        """True when the strongest thing asserted is weaker than an exact answer.

        ``careers_host`` pins only the host, and a purely negative case pins only
        what must NOT come back. Both are honest — they are all the ground truth
        that exists — but the summary says how many of them there are, because a
        suite made mostly of weak checks is not the same evidence as one made of
        strong ones.
        """
        return "careers_host" in self.spec or not self.has_positive_expectation

    @property
    def expected_text(self) -> str:
        s = self.spec
        if "board" in s:
            return f"board {s['board']} (>= {s.get('min_jobs', 1)} jobs)"
        if "careers_url" in s:
            v = s["careers_url"]
            return f"careers {v if isinstance(v, str) else ' | '.join(v)}"
        if "careers_host" in s:
            return f"careers on host {s['careers_host']}"
        if "already_public" in s:
            return f"already tracked: {s['already_public']}"
        if s.get("nothing"):
            return "nothing (known dead end)"
        bits = []
        if s.get("must_offer_careers"):
            bits.append("a careers page")
        if s.get("must_answer"):
            bits.append("some answer")
        for n in s.get("must_not", []):
            bits.append(f"not {n}")
        for h in s.get("must_not_aggregator", []):
            bits.append(f"{h} not dropped as aggregator")
        return "; ".join(bits) or "(nothing asserted)"


def load_cases(path: Path) -> list[Case]:
    """Read and VALIDATE the case file. Every failure here is fatal.

    Validation is not politeness. ``oracle.com/careers/`` was once somebody's idea
    of Oracle's job board, and the cheapest place to refuse that is before the run
    starts, not after $0.20 of searching.
    """
    with path.open("rb") as fh:
        doc = tomllib.load(fh)
    raw = doc.get("cases")
    if not isinstance(raw, dict) or not raw:
        raise CaseFileError(f"{path}: no [cases] table, or it is empty")

    cases: list[Case] = []
    for key, spec in raw.items():
        where = f"{path}: case {key!r}"
        if not isinstance(spec, dict):
            raise CaseFileError(f"{where}: must be an inline table")
        unknown = set(spec) - _KNOWN_KEYS
        if unknown:
            raise CaseFileError(f"{where}: unknown key(s) {sorted(unknown)}")
        if not spec.get("input"):
            raise CaseFileError(f"{where}: missing `input` (the name a user types)")
        positives = [k for k in _POSITIVE_KEYS if k in spec]
        if len(positives) > 1:
            raise CaseFileError(
                f"{where}: {positives} are mutually exclusive — a search has one answer"
            )
        if not positives and not any(
            k in spec
            for k in ("must_not", "must_offer_careers", "must_answer", "must_not_aggregator")
        ):
            raise CaseFileError(f"{where}: asserts nothing at all")
        if not spec.get("truth"):
            raise CaseFileError(
                f"{where}: missing `truth`. Say where the expectation came from — "
                f"'owner:<date>', 'measured:<doc>', or 'agent-guess' if you are being "
                f"honest that nobody has established it."
            )
        for url in _as_list(spec.get("careers_url")):
            if not is_job_list_shaped(url):
                raise CaseFileError(
                    f"{where}: careers_url {url!r} is not job-list-shaped — its path has "
                    f"no segment like /jobs, /jobsearch, /all-jobs, /openings. This is "
                    f"the exact shape of a marketing page, and recording one as ground "
                    f"truth is how Oracle was scored as a pass while it was failing. If "
                    f"this really is the answer, the rule in is_job_list_shaped() is "
                    f"what needs changing, deliberately and in a commit of its own."
                )
        if "board" in spec and ":" not in str(spec["board"]):
            raise CaseFileError(f"{where}: board must be 'ats:token', got {spec['board']!r}")
        if "known_limitation" in spec and not str(spec["known_limitation"]).strip():
            raise CaseFileError(
                f"{where}: known_limitation must be a non-empty string saying WHY this "
                f"case fails today and what closing it would take. A bare flag would "
                f"let a case be excused from the pass line without anyone writing down "
                f"what is broken."
            )
        cases.append(Case(key=key, input=str(spec["input"]), spec=spec))
    return cases


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)


# ─────────────────────────────────────────────────────────────────────────────
# Reading the response
# ─────────────────────────────────────────────────────────────────────────────

def _get(d: dict[str, Any], camel: str, snake: str, default: Any = None) -> Any:
    """The wire is camelCase (pydantic ``alias_generator=to_camel``); accept either."""
    if camel in d:
        return d[camel]
    return d.get(snake, default)


@dataclass
class Answer:
    """The three channels this endpoint can answer on, flattened."""

    auto_boards: list[dict[str, Any]] = field(default_factory=list)
    all_boards: list[dict[str, Any]] = field(default_factory=list)
    careers_url: str | None = None
    already: dict[str, Any] | None = None
    searches: int = 1
    non_boards: list[dict[str, Any]] = field(default_factory=list)

    @property
    def answered(self) -> bool:
        return bool(self.auto_boards) or self.careers_url is not None or self.already is not None

    @property
    def careers_is_the_offer(self) -> bool:
        """Is the careers URL what the user is actually being handed?

        It rides along on an ``already_public`` ``'name'`` match too, where it is the
        escape hatch rather than the offer, and on that path the page shows the
        published match instead. The brochure rule only applies when the careers page
        IS the answer — otherwise a perfectly correct "we already track GM" would fail
        for the shape of a URL nobody is being asked to accept.
        """
        return (
            self.careers_url is not None
            and self.already is None
            and not self.auto_boards
        )

    def summary(self) -> str:
        """EVERY channel that answered, not just the first.

        This started as a first-match ladder and it lied: Cisco came back with an
        auto-addable ``workday:cisco`` AND an already-published match, and the ladder
        printed only the second, so the ACTUAL column hid the very board the case was
        asserting on. An actual-value column that shows some of the actual value is
        the same class of mistake this whole suite exists to catch.
        """
        bits: list[str] = []
        if self.already is not None:
            kind = _get(self.already, "matchKind", "match_kind", "board")
            bits.append(
                f"already tracked: {_get(self.already, 'companyId', 'company_id')} ({kind})"
            )
        if self.auto_boards:
            boards = []
            for b in self.auto_boards:
                c = b["candidate"]
                jobs = _get(b["probe"], "jobCount", "job_count", 0)
                boards.append(f"{c['ats']}:{_get(c, 'boardToken', 'board_token')} ({jobs} jobs)")
            bits.append("auto-add " + ", ".join(boards))
        if self.careers_url:
            shape = "" if is_job_list_shaped(self.careers_url) else " [BROCHURE]"
            label = "careers" if self.careers_is_the_offer else "careers(escape-hatch)"
            bits.append(f"{label} {self.careers_url}{shape}")
        if bits:
            return " + ".join(bits)
        if self.all_boards:
            c = self.all_boards[0]["candidate"]
            token = _get(c, "boardToken", "board_token")
            return (
                f"nothing offered ({len(self.all_boards)} board(s) shown, none auto-addable; "
                f"top: {c['ats']}:{token})"
            )
        return "nothing at all"


def read_answer(body: dict[str, Any]) -> Answer:
    boards = body.get("candidates") or []
    trace = body.get("trace") or {}
    return Answer(
        auto_boards=[b for b in boards if _get(b, "autoAddable", "auto_addable")],
        all_boards=list(boards),
        careers_url=_get(body, "careersUrl", "careers_url"),
        already=_get(body, "alreadyPublic", "already_public"),
        # The router fires the second, plain "{name} careers" query ONLY on a miss,
        # and reports it as this block. Its presence is therefore an exact count of
        # what the request cost.
        searches=2 if _get(body, "careersSearch", "careers_search") is not None else 1,
        non_boards=_get(trace, "nonBoards", "non_boards", []) or [],
    )


def _answer_strings(a: Answer) -> list[str]:
    """Everything the user is being OFFERED, as lowercase text.

    Scoped to answers on purpose. ``must_not`` asks "did we hand the user somebody
    else's board", not "did the search engine mention them" — a stranger's board
    listed as information the user can reject is the design working, and asserting
    against it would make the suite fight the feature.
    """
    out: list[str] = []
    if a.careers_url:
        out.append(a.careers_url)
    for b in a.auto_boards:
        c = b["candidate"]
        out.append(f"{c['ats']}:{_get(c, 'boardToken', 'board_token')}")
        out.append(str(_get(c, "sourceUrl", "source_url", "")))
        out.append(str(b.get("sourceUrl") or b.get("source_url") or ""))
    if a.already is not None:
        out.append(str(_get(a.already, "companyId", "company_id", "")))
        out.append(str(_get(a.already, "displayName", "display_name", "")))
        out.append(str(_get(a.already, "finalUrl", "final_url", "")))
    return [s.lower() for s in out if s]


# ─────────────────────────────────────────────────────────────────────────────
# Judging one attempt
# ─────────────────────────────────────────────────────────────────────────────

def judge(case: Case, a: Answer) -> list[str]:
    """Every reason this attempt is wrong. Empty list means it is right."""
    s = case.spec
    fails: list[str] = []

    if "board" in s:
        want = str(s["board"]).lower()
        floor = int(s.get("min_jobs", 1))
        hit = None
        for b in a.auto_boards:
            c = b["candidate"]
            got = f"{c['ats']}:{_get(c, 'boardToken', 'board_token')}".lower()
            if got == want:
                hit = b
                break
        if hit is None:
            fails.append(f"no auto-addable board {s['board']}")
        else:
            probe = hit["probe"]
            jobs = _get(probe, "jobCount", "job_count", 0)
            if not probe.get("ok"):
                fails.append(f"{s['board']} did not answer: {probe.get('error')}")
            elif jobs < floor:
                fails.append(f"{s['board']} returned {jobs} jobs, floor is {floor}")
        # An ATS hit must cost exactly one search. The careers escalation firing
        # anyway would be a silent doubling of the bill on the commonest path.
        if a.searches > int(s.get("max_searches", 1)):
            fails.append(f"spent {a.searches} searches, expected {s.get('max_searches', 1)}")

    elif "careers_url" in s:
        want = {normalize_url(u) for u in _as_list(s["careers_url"])}
        if a.careers_url is None:
            fails.append("no careers page offered")
        else:
            if normalize_url(a.careers_url) not in want:
                fails.append(
                    f"offered {a.careers_url} — expected {' | '.join(sorted(want))}"
                )

    elif "careers_host" in s:
        want_host = str(s["careers_host"]).lower()
        if a.careers_url is None:
            fails.append("no careers page offered")
        else:
            got = host_of(a.careers_url)
            if got != want_host and not got.endswith("." + want_host):
                fails.append(f"offered host {got}, expected {want_host}")

    elif "already_public" in s:
        if a.already is None:
            fails.append(f"did not say we already track {s['already_public']}")
        else:
            got = _get(a.already, "companyId", "company_id")
            if got != s["already_public"]:
                fails.append(f"matched {got}, expected {s['already_public']}")
            want_kind = s.get("match_kind")
            if want_kind:
                got_kind = _get(a.already, "matchKind", "match_kind", "board")
                if got_kind != want_kind:
                    fails.append(f"match_kind {got_kind}, expected {want_kind}")
        # NO implied search pin here, deliberately. An already-published company can
        # be recognised on either of two rungs — the BOARD rung, before the careers
        # escalation (one search), or the careers-URL NAME rung, after it (two).
        # Measured 2026-09-04: `Databricks` takes the second route, because its
        # Greenhouse board does not appear in the host-shaped query's 25 results at
        # all (COMPANY-NAME-SEARCH-EVALUATION.md, ground-truth row "Databricks:
        # absent; fan-out #50"). Pinning one search here would have been the harness
        # inventing an expectation the owner never stated — the exact sin this suite
        # exists to prevent. A case that really wants the cheap rung says
        # `max_searches = 1` out loud.
        if "max_searches" in s and a.searches > int(s["max_searches"]):
            fails.append(f"spent {a.searches} searches, expected {s['max_searches']}")

    elif s.get("nothing"):
        if a.answered:
            fails.append(f"expected an honest dead end, got: {a.summary()}")

    # ── THE GLOBAL BROCHURE RULE, applied to every case ────────────────────
    # If the thing the user is handed is a careers page, it must be a list of open
    # roles. This is the owner's requirement stated as code: "prefer a definition
    # that cannot be satisfied by a plausible-looking marketing page, because that
    # is precisely how Oracle passed."
    #
    # It applies even to cases that record no positive expectation, and that is the
    # point — `Poke` asserts only "not poki", and without this rule it PASSES while
    # handing the user pokemoto.com/careers, a poke-bowl restaurant chain's About-Us
    # page. Passing on a technicality while the answer is junk is the failure mode
    # this suite was built to remove.
    #
    # `allow_brochure = true` opts a case out. It has to be written down, in the case
    # file, by someone who decided it — never assumed here.
    if a.careers_is_the_offer and not is_job_list_shaped(a.careers_url or ""):
        if not s.get("allow_brochure"):
            fails.append(
                f"offered {a.careers_url} — a marketing page, not a list of open roles "
                f"(no /jobs, /jobsearch, /openings… segment)"
            )

    # ── THE VACUOUS-PASS RULE, applied to every case ───────────────────────
    # A case that only says what must NOT come back is satisfied by SILENCE. The
    # ``must_not`` loop below iterates the ANSWER strings; an endpoint that answered
    # nothing produces none, so the loop body never runs and every check "passes" by
    # having nothing to look at.
    #
    # Four cases were shaped exactly like that — `metabase`, `poke`, `gm`, `hp` — so
    # a `search-by-name` that returned `{candidates: [], careersUrl: null}` for every
    # input would have reported 4 of 21 GREEN. That is a reproduction, inside the
    # harness built to prevent it, of the "4 for 4, live" report this file exists
    # because of.
    #
    # STRUCTURAL rather than four more ``must_answer`` lines, deliberately: the hole
    # belongs to the SHAPE of a case, not to those four, so the next one-line
    # ``must_not`` case someone adds is covered without them ever learning this
    # happened.
    #
    # A case whose right answer really IS silence opts in by saying so —
    # ``nothing = true`` (`facebook`, `poke`). That is a positive expectation, judged
    # above, and it can fail; the difference is between ASSERTING a dead end and
    # INHERITING one.
    if not case.has_positive_expectation and not a.answered:
        fails.append(
            "vacuous: the endpoint answered nothing at all, and this case asserts "
            "only what must NOT come back — so every check above passed by having "
            "nothing to look at. Say what a right answer is (`nothing = true` if it "
            "really is silence, `must_answer = true` if any answer will do)."
        )

    # ── modifiers, applied to every case ───────────────────────────────────
    haystack = _answer_strings(a)
    for forbidden in s.get("must_not", []):
        needle = str(forbidden).lower()
        for got in haystack:
            if needle in got:
                fails.append(f"answer contains {forbidden!r}: {got}")
                break
    if s.get("must_offer_careers") and a.careers_url is None:
        fails.append("no careers page offered")
    if s.get("must_answer") and not a.answered:
        fails.append("dead end — no board, no careers page, no published match")
    for host in s.get("must_not_aggregator", []):
        h = str(host).lower()
        for row in a.non_boards:
            url = str(row.get("url", ""))
            row_host = host_of(url)
            if (row_host == h or row_host.endswith("." + h)) and row.get("aggregator"):
                fails.append(f"{url} was dropped as an aggregator, but it is {host}")
    return fails


# ─────────────────────────────────────────────────────────────────────────────
# Running
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Attempt:
    ok: bool
    reasons: list[str]
    actual: str
    seconds: float
    searches: int
    error: str | None = None
    body: dict[str, Any] | None = None


class Budget:
    """A hard ceiling on real money, checked before every call."""

    def __init__(self, max_searches: int) -> None:
        self.max = max_searches
        self.spent = 0

    def can_afford(self) -> bool:
        # Worst case is 2 (the careers escalation), so refuse at max-1 rather than
        # discovering the overrun after paying for it.
        return self.spent + 2 <= self.max

    @property
    def usd(self) -> float:
        return self.spent * USD_PER_SEARCH


def run_case(client: httpx.Client, case: Case, budget: Budget) -> Attempt:
    started = time.monotonic()
    try:
        resp = client.post(
            "/api/companies/search-by-name", json={"name": case.input}
        )
    except Exception as exc:  # noqa: BLE001
        return Attempt(
            ok=False, reasons=[f"request failed: {type(exc).__name__}: {exc}"],
            actual="(no response)", seconds=time.monotonic() - started, searches=0,
            error=str(exc),
        )
    elapsed = time.monotonic() - started
    if resp.status_code != 200:
        # A 503 means "we could not look", which is an outage and NOT a wrong
        # answer — but it is also not a pass. It is reported as an ERROR so it can
        # never be quoted as a green case.
        return Attempt(
            ok=False, reasons=[f"HTTP {resp.status_code}: {resp.text[:200]}"],
            actual=f"HTTP {resp.status_code}", seconds=elapsed, searches=1,
            error=f"HTTP {resp.status_code}",
        )
    body = resp.json()
    answer = read_answer(body)
    budget.spent += answer.searches
    reasons = judge(case, answer)
    return Attempt(
        ok=not reasons, reasons=reasons, actual=answer.summary(),
        seconds=elapsed, searches=answer.searches, body=body,
    )


VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_FLAKY = "FLAKY"
VERDICT_ERROR = "ERROR"
VERDICT_SKIP = "SKIP"
VERDICT_UNVERIFIED = "PASS?"
#: A gap somebody wrote down (``known_limitation``). Judged and printed like any
#: other failure — it just does not masquerade as a regression in the pass line.
VERDICT_KNOWN = "KNOWN"
#: A ``known_limitation`` case that PASSED. Not a failure, but never silent: the
#: marker is now a lie and the summary says so.
VERDICT_FIXED = "FIXED"


def verdict_for(case: Case, attempts: list[Attempt]) -> str:
    if not attempts:
        return VERDICT_SKIP
    if all(a.error for a in attempts):
        return VERDICT_ERROR
    oks = [a.ok for a in attempts]
    if case.known_limitation:
        # Written-down gap. It still ran, and its reasons still print under WHY:.
        return VERDICT_FIXED if all(oks) else VERDICT_KNOWN
    if all(oks):
        # A pass on an expectation nobody established is exactly the Oracle
        # mistake. It shows, and it does not count.
        return VERDICT_PASS if case.truth_verified else VERDICT_UNVERIFIED
    if any(oks):
        return VERDICT_FLAKY
    return VERDICT_FAIL


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


#: How much of the actual value to keep before the elision, and how much run-up to
#: show before the character that differs. Both are just enough to recognise the
#: string and to see the difference in context.
_DIFF_HEAD = 12
_DIFF_RUNUP = 8


def _clip_diff(expected: str, actual: str, n: int) -> str:
    """Clip ``actual`` to ``n`` columns, KEEPING the point where it stops matching.

    A plain head-clip hid a real failure in plain sight. Oracle was offered
    ``careers.oracle.com/…/jobs?location=United%20States&locationId=…`` against an
    expectation of ``careers.oracle.com/…/jobs``, and the two are identical for 57
    characters — so the EXPECTED and ACTUAL columns printed the same 62-character
    prefix and the row read as a pass with the word FAIL beside it. The query is
    the whole difference: it scopes the board to one country, and a recipe captured
    through it is a US-only scraper.

    So when the two agree past the width of the column, the middle is elided and
    the window is moved to where they part.
    """
    if len(actual) <= n:
        return actual
    common = 0
    for want_ch, got_ch in zip(expected, actual):
        if want_ch != got_ch:
            break
        common += 1
    if common < n - _DIFF_RUNUP:
        # The divergence is inside the window already — clip normally.
        return _clip(actual, n)
    start = max(_DIFF_HEAD, common - _DIFF_RUNUP)
    return actual[:_DIFF_HEAD] + "…" + _clip(actual[start:], n - _DIFF_HEAD - 1)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="intent_test.py",
        description="Intent test for POST /api/companies/search-by-name (spends real money).",
    )
    p.add_argument("--base-url", default=os.environ.get("NAME_SEARCH_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--cases", default=str(_HERE / "cases.toml"))
    p.add_argument("--case", action="append", default=[], metavar="KEY",
                   help="run only these cases (repeatable)")
    p.add_argument("--tag", action="append", default=[], metavar="TAG",
                   help="run only cases with these tags (repeatable)")
    p.add_argument("--runs", type=int, default=1,
                   help="repeat every case N times; anything short of N/N is FLAKY, not PASS")
    p.add_argument("--max-searches", type=int, default=60,
                   help="hard ceiling on paid Browserbase searches for this INVOCATION "
                        "— all runs together, not per run. One full pass is ~38, so "
                        "--runs N wants roughly 40*N")
    p.add_argument("--json", default=None, help="write the full result record here")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--validate-only", action="store_true",
                   help="load and check cases.toml, spend nothing, exit")
    p.add_argument("--replay", default=None, metavar="RESULTS.JSON",
                   help="re-judge a previous run's recorded responses. Spends NOTHING. "
                        "Use this whenever you change an assertion — every response body "
                        "is stored, so tightening a rule costs $0 instead of another run.")
    args = p.parse_args(argv)

    try:
        cases = load_cases(Path(args.cases))
    except CaseFileError as exc:
        print(f"\ncases.toml is invalid:\n  {exc}\n", file=sys.stderr)
        return 2

    if args.case:
        wanted = set(args.case)
        cases = [c for c in cases if c.key in wanted]
        missing = wanted - {c.key for c in cases}
        if missing:
            print(f"no such case(s): {sorted(missing)}", file=sys.stderr)
            return 2
    if args.tag:
        tags = set(args.tag)
        cases = [c for c in cases if tags & set(c.tags)]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2

    print(f"\n{'=' * 100}")
    print("INTENT TEST — type a company name, get its job board")
    print(f"{'=' * 100}")
    print(f"endpoint   POST {args.base_url}/api/companies/search-by-name  (the real one, over HTTP)")
    print(f"cases      {len(cases)} × {args.runs} run(s)")
    print(f"budget     {args.max_searches} searches max "
          f"(~${args.max_searches * USD_PER_SEARCH:.2f} of real Browserbase spend)")
    unverified = [c.key for c in cases if not c.truth_verified]
    if unverified:
        print(f"UNVERIFIED ground truth in: {', '.join(unverified)} — these can never PASS")
    if args.validate_only:
        print("\n--validate-only: cases.toml is valid. Nothing was spent.\n")
        return 0

    if args.replay:
        # Re-judge stored bodies. No client, no budget, no money. The elapsed times
        # and search counts are the ORIGINAL run's, and are reported as such.
        record = json.loads(Path(args.replay).read_text(encoding="utf-8"))
        stored = {c["key"]: c.get("attempts", []) for c in record.get("cases", [])}
        results: dict[str, list[Attempt]] = {}
        budget = Budget(0)
        print(f"\nREPLAY of {args.replay} — no searches, no cost\n")
        for case in cases:
            attempts = []
            for a in stored.get(case.key, []):
                body = a.get("body")
                if body is None:
                    continue
                ans = read_answer(body)
                reasons = judge(case, ans)
                budget.spent += a.get("searches", 0)
                attempts.append(Attempt(
                    ok=not reasons, reasons=reasons, actual=ans.summary(),
                    seconds=a.get("seconds", 0.0), searches=a.get("searches", 0), body=body,
                ))
            results[case.key] = attempts
        return _report(cases, results, budget, 0.0, args, replayed=True)

    token = os.environ.get("NAME_SEARCH_TOKEN")
    if not token:
        from e2e.shared.auth.mint import PRIMARY_USER, mint_token
        token = mint_token(PRIMARY_USER)
    client = httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=args.timeout,
    )

    budget = Budget(args.max_searches)
    results: dict[str, list[Attempt]] = {}
    started = time.monotonic()
    print()
    try:
        for case in cases:
            attempts: list[Attempt] = []
            for run_no in range(args.runs):
                if not budget.can_afford():
                    print(f"  BUDGET STOP before {case.key} "
                          f"({budget.spent}/{budget.max} searches spent)")
                    break
                att = run_case(client, case, budget)
                attempts.append(att)
                mark = "ok " if att.ok else "BAD"
                suffix = f" run {run_no + 1}/{args.runs}" if args.runs > 1 else ""
                print(f"  {mark} {case.key:<12}{suffix} {att.seconds:5.1f}s  {_clip(att.actual, 88)}")
                for r in att.reasons:
                    print(f"        ↳ {r}")
            results[case.key] = attempts
    except KeyboardInterrupt:
        print("\ninterrupted — the table below covers only the cases that ran\n")
    finally:
        client.close()
    elapsed = time.monotonic() - started
    return _report(cases, results, budget, elapsed, args)


def _report(
    cases: list[Case],
    results: dict[str, list[Attempt]],
    budget: Budget,
    elapsed: float,
    args: argparse.Namespace,
    *,
    replayed: bool = False,
) -> int:
    """The table and the one line a human reads in five seconds."""
    rows = []
    for case in cases:
        attempts = results.get(case.key, [])
        v = verdict_for(case, attempts)
        actual = attempts[-1].actual if attempts else "(not run)"
        if v == VERDICT_FLAKY:
            n_ok = sum(1 for a in attempts if a.ok)
            actual = f"{n_ok}/{len(attempts)} runs correct — {actual}"
        secs = (sum(a.seconds for a in attempts) / len(attempts)) if attempts else 0.0
        rows.append((case, v, actual, secs))

    w_in, w_exp, w_act = 14, 46, 62
    print(f"\n{'-' * 152}")
    print(f"{'CASE':<12} {'INPUT':<{w_in}} {'EXPECTED':<{w_exp}} {'ACTUAL':<{w_act}} "
          f"{'VERDICT':<8} {'TIME':>6}")
    print(f"{'-' * 152}")
    for case, v, actual, secs in rows:
        # The ACTUAL column is clipped AGAINST the expectation, not on its own, so
        # a value that agrees for longer than the column is wide still shows where
        # it stops agreeing. See ``_clip_diff``.
        shown = _clip_diff(case.expected_text, actual, w_act)
        print(f"{case.key:<12} {_clip(case.input, w_in):<{w_in}} "
              f"{_clip(case.expected_text, w_exp):<{w_exp}} {shown:<{w_act}} "
              f"{v:<8} {secs:>5.1f}s")
    print(f"{'-' * 152}")

    # EVERY REASON, IN FULL, under the table. The table is 152 columns wide and a
    # URL is not, so the row can only ever hint at a difference; this is where the
    # two values are printed whole, for anyone reading the summary file after the
    # run rather than watching it.
    bad = [(case, v) for case, v, _, _ in rows
           if v in (VERDICT_FAIL, VERDICT_FLAKY, VERDICT_ERROR, VERDICT_KNOWN)]
    if bad:
        print("\nWHY:")
        for case, v in bad:
            for i, att in enumerate(results.get(case.key, []), start=1):
                if att.ok:
                    continue
                run = f" run {i}" if len(results.get(case.key, [])) > 1 else ""
                print(f"  {case.key}{run} [{v}]")
                print(f"      expected  {case.expected_text}")
                print(f"      actual    {att.actual}")
                for r in att.reasons:
                    print(f"      ↳ {r}")

    counts = {v: sum(1 for _, verd, _, _ in rows if verd == v)
              for v in (VERDICT_PASS, VERDICT_FAIL, VERDICT_FLAKY, VERDICT_ERROR,
                        VERDICT_SKIP, VERDICT_UNVERIFIED, VERDICT_KNOWN,
                        VERDICT_FIXED)}
    # THE PASS LINE COUNTS ONLY THE CASES THAT CLAIM TO WORK. A case carrying a
    # ``known_limitation`` is a gap somebody wrote down, not a claim — counting it
    # in the denominator would make the headline permanently red for something we
    # already know, which is the fastest way to teach a reader to ignore the
    # headline. It is printed instead, in full, on its own line and under WHY:.
    graded = [(case, v) for case, v, _, _ in rows if not case.known_limitation]
    total = len(graded)
    passing = sum(1 for _, v in graded if v == VERDICT_PASS)
    # The parenthetical explains the N/M line, so it describes the same rows.
    graded_counts = {v: sum(1 for _, verd in graded if verd == v) for v in counts}

    if replayed:
        print(f"\ncost       $0.00 — replayed from disk. The {budget.spent} search(es) "
              f"below were paid for by the original run.")
    else:
        print(f"\ncost       {budget.spent} paid searches  ≈ ${budget.usd:.3f}   "
              f"(wall clock {elapsed:.0f}s)")
    detail = ", ".join(
        f"{n} {name.lower()}" for name, n in (
            ("failing", graded_counts[VERDICT_FAIL]),
            ("flaky", graded_counts[VERDICT_FLAKY]),
            ("errored", graded_counts[VERDICT_ERROR]),
            ("not run", graded_counts[VERDICT_SKIP]),
            ("unverified-truth", graded_counts[VERDICT_UNVERIFIED]),
        ) if n
    )
    weak = [c.key for c, v, _, _ in rows if c.weak and v in (VERDICT_PASS, VERDICT_UNVERIFIED)]
    if weak:
        print(f"weak       {len(weak)} passing case(s) rest on a host-only or "
              f"negative-only check: {', '.join(weak)}")

    # THE KNOWN GAPS, NAMED, every run. They are outside the pass line, so this is
    # the only thing standing between "documented limitation" and "quietly ignored".
    known = [(c, v) for c, v, _, _ in rows if c.known_limitation]
    for case, v in known:
        state = {VERDICT_KNOWN: "STILL FAILING", VERDICT_FIXED: "NOW PASSING"}.get(v, v)
        print(f"known      {case.key}: {case.known_limitation} [{state}]")
    fixed = [c.key for c, v in known if v == VERDICT_FIXED]
    if fixed:
        print(f"known      {', '.join(fixed)} PASSED — the known_limitation is now "
              f"false. Delete it so the case counts, or say what changed.")

    print(f"\n>>> {passing}/{total} passing" + (f"  ({detail})" if detail else "")
          + (f"  [+{len(known)} known limitation(s), outside the count: "
             f"{', '.join(c.key for c, _ in known)}]" if known else ""))
    if passing != total:
        print(">>> THIS FEATURE IS NOT DONE. A claim that it is, without a green run "
              "of this suite, is not supportable.")
    print()

    if args.json:
        Path(args.json).write_text(json.dumps({
            "base_url": args.base_url,
            "runs": args.runs,
            "searches": budget.spent,
            "usd": round(budget.usd, 4),
            "elapsed_seconds": round(elapsed, 1),
            "passing": passing,
            "total": total,
            "counts": counts,
            "cases": [
                {
                    "key": c.key, "input": c.input, "expected": c.expected_text,
                    "truth": c.truth, "truth_verified": c.truth_verified,
                    "known_limitation": c.known_limitation or None,
                    "weak": c.weak, "tags": c.tags, "verdict": v, "actual": actual,
                    "attempts": [
                        {"ok": a.ok, "reasons": a.reasons, "seconds": round(a.seconds, 2),
                         "searches": a.searches, "actual": a.actual, "body": a.body}
                        for a in results.get(c.key, [])
                    ],
                }
                for c, v, actual, _ in rows
            ],
        }, indent=2), encoding="utf-8")
        print(f"full record → {args.json}\n")

    return 0 if passing == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
