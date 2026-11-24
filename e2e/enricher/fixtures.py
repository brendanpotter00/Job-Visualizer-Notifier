"""The enricher section's corpus — ONE source of truth for the seed, the stub
model and the assertions.

Every row is seeded into the section's own JVN database by ``seed.py``, claimed
by the REAL enricher through the REAL ``/api/internal/enrichment/pending``, and
classified by ``stub_ollama.py``, which answers from THIS table. So a test that
asserts "JVN now says software_engineering / senior" is comparing the database
against the answer the stub was told to give, never against the code under
test.

Rows are grouped per case (``EN01`` ... ``EN10``). A case seeds only its own
group, so each case's exact-set assertions cannot be disturbed by another
case's rows. Ids are unique across groups, because the stub looks answers up
by ``job_listing_id``.

``behaviour`` is how a single row misbehaves on the CLASSIFY call, so one tick
can mix good rows with bad ones (EN-06: "bad output never kills a wave"):

* ``extra_ghost``      the answer comes back WITH a second object for an id the
                        enricher never claimed (a hallucinated id)
* ``invalid_category`` the answer carries a category slug outside the taxonomy
* ``garbled``          a valid ollama envelope whose content is prose, not JSON
* ``http_garbage``     an HTTP 200 whose BODY is not JSON (a broken proxy page)
* ``long_tag``         one tag longer than JVN's MAX_TAG_LENGTH (60), which JVN
                        drops and reports in ``warnings[]``

The stub also answers, by title keyword, a job it does not know (see
``KEYWORD_RULES``), so a stray row can never wedge the stub — but every case
asserts on exact sets, so a stray row still turns the case red.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any

SOURCE_ID = "e2e_enricher"
COMPANY_ID = "e2e-enricher-co"
COMPANY_NAME = "E2E Enricher Co"

#: The model tag prod runs (``enrich_config.OPENCODE_MODEL_DEFAULT``). EN-01
#: asserts every request the stub saw carried exactly this, so a default that
#: drifted would show up here as well as in ``cli health``.
MODEL = "qwen3:32b"

#: Over JVN's ``MAX_TAG_LENGTH`` (60) on purpose — see ``long_tag``.
LONG_TAG = "x" * 61 + "-too-long-for-jvn"

#: The id the ``extra_ghost`` behaviour invents. Never seeded, never claimed.
GHOST_PREFIX = "ghost-"

#: San Francisco, as the location rubric would emit it. Valid for JVN's
#: ``CanonicalLocation`` (kind=city, no remote_scope).
SF_LOCATION = {
    "canonical_name": "San Francisco, CA, US",
    "kind": "city",
    "city": "San Francisco",
    "region": "CA",
    "country": "US",
    "remote_scope": None,
    "confidence": 0.95,
}

_DESCRIPTION = (
    "<div><h2>About the role</h2><p>We build {what} for {company}. You will own "
    "it end to end.</p><ul><li>{years}</li><li>Ship weekly</li></ul>"
    "<p>Benefits: health, dental, a laptop.</p></div>"
)


@dataclass(frozen=True)
class Judge:
    """What the stub's JUDGE says about one row (only rows the enricher routes to
    the judge are ever asked)."""

    passed: bool = True
    confidence: float = 0.95
    needs_human: bool = False
    corrections: dict[str, Any] = field(default_factory=dict)
    notes: str = "e2e stub judge"


DEFAULT_JUDGE = Judge()


@dataclass(frozen=True)
class Job:
    job_id: str
    title: str
    category: str
    level: str
    tags: tuple[str, ...]
    #: v7 shape only; an empty tuple on a non-SWE row is the "evaluated, none
    #: apply" answer the v7 prompt asks for. The v6 tag ignores the key.
    subcategories: tuple[str, ...] = ()
    confidence: float = 0.95
    judge: Judge = DEFAULT_JUDGE
    behaviour: str | None = None
    location: str = "San Francisco, CA"
    what: str = "backend services"
    years: str = "5+ years of experience"

    @property
    def description_html(self) -> str:
        return _DESCRIPTION.format(what=self.what, company=COMPANY_NAME, years=self.years)

    @property
    def level_includes(self) -> list[str]:
        if self.level == "new_grad":
            return ["new_grad", "entry"]
        return [self.level]


def _j(job_id: str, title: str, category: str, level: str, tags: tuple[str, ...], **kw: Any) -> Job:
    return Job(job_id=job_id, title=title, category=category, level=level, tags=tags, **kw)


# --- EN-01: one real wrapper fire enriches the seeded rows end to end -------
EN01 = (
    _j("EN01-SWE-SR", "Senior Software Engineer, Payments", "software_engineering", "senior",
       ("python", "distributed-systems", "payments"), subcategories=("backend",)),
    _j("EN01-PM", "Product Manager, Growth", "product_manager", "mid",
       ("product-strategy", "experimentation"), what="growth experiments"),
    _j("EN01-NEWGRAD", "Software Engineer, New Grad 2027", "software_engineering", "new_grad",
       ("react", "typescript"), subcategories=("frontend",), confidence=0.9,
       years="Graduating in 2026 or 2027"),
    _j("EN01-DS", "Senior Data Scientist", "data_scientist", "senior",
       ("sql", "statistics"), confidence=0.92, what="pricing models"),
)

# --- EN-02: judge routing ---------------------------------------------------
# judge:scope=low_confidence with ceiling 0.85: only rows classified below 0.85
# reach the judge. JVN's job_enrichment.judged is the proof of routing.
EN02 = (
    # Confident -> never judged.
    _j("EN02-CONFIDENT", "Staff Software Engineer, Infrastructure", "software_engineering",
       "senior_plus", ("kubernetes", "go"), subcategories=("infrastructure_platform",),
       confidence=0.96),
    # Unsure + the judge REVISES category and level (its own confidence 0.9 clears
    # the 0.8 level-change rail).
    _j("EN02-REVISED", "Machine Learning Platform Engineer", "data_scientist", "mid",
       ("ml-platform", "python"), confidence=0.55, what="ML training infrastructure",
       judge=Judge(passed=False, confidence=0.9, notes="e2e: this is engineering",
                   corrections={"category": "software_engineering", "level": "senior",
                                "level_includes": ["senior"]})),
    # Unsure + the judge itself is unsure (0.40 < judge:human_floor 0.60) ->
    # needs_human, even though the verdict did not ask for a human.
    _j("EN02-HUMAN", "Solutions Engineer (Hybrid)", "business_ops", "mid",
       ("pre-sales",), confidence=0.5, what="customer integrations",
       judge=Judge(passed=False, confidence=0.4, needs_human=False,
                   notes="e2e: could be engineering or sales")),
    # Unsure + the judge CONFIRMS: judged, passed, nothing changed.
    _j("EN02-CONFIRMED", "Growth Marketing Manager", "growth", "mid",
       ("paid-acquisition",), confidence=0.6, what="acquisition funnels",
       judge=Judge(passed=True, confidence=0.93)),
)

# --- EN-03: the metrics channel ---------------------------------------------
EN03 = (
    _j("EN03-A", "Backend Engineer", "software_engineering", "mid", ("java",),
       subcategories=("backend",), confidence=0.7),
    _j("EN03-B", "Business Operations Analyst", "business_ops", "entry", ("excel",),
       what="planning", years="1+ year of experience"),
)

# --- EN-04: the single-flight lock ------------------------------------------
EN04 = (
    _j("EN04-A", "Site Reliability Engineer", "software_engineering", "mid",
       ("sre", "linux"), subcategories=("devops_sre",)),
)

# --- EN-05: delivery-first under an engine outage ---------------------------
EN05 = (
    _j("EN05-A", "iOS Engineer", "software_engineering", "senior", ("swift", "ios"),
       subcategories=("mobile",)),
    _j("EN05-B", "Hardware Design Engineer", "hardware_engineer", "mid", ("verilog",),
       what="ASICs"),
)

# --- EN-06: bad model output never kills a wave -----------------------------
EN06 = (
    _j("EN06-OK", "Frontend Engineer", "software_engineering", "mid", ("react",),
       subcategories=("frontend",)),
    _j("EN06-GHOST", "Data Engineer", "software_engineering", "mid", ("spark",),
       subcategories=("data_engineering",), behaviour="extra_ghost"),
    _j("EN06-BADSLUG", "Astronaut Liaison", "business_ops", "mid", ("space",),
       behaviour="invalid_category", what="mission planning"),
    _j("EN06-GARBLED", "Security Engineer", "software_engineering", "senior",
       ("appsec",), subcategories=("security",), behaviour="garbled"),
    _j("EN06-HTTPJUNK", "QA Engineer", "software_engineering", "mid", ("selenium",),
       subcategories=("qa_testing",), behaviour="http_garbage"),
    _j("EN06-LONGTAG", "Product Designer", "product_manager", "mid",
       ("figma", LONG_TAG), behaviour="long_tag", what="design systems"),
)

# --- EN-07: idempotent re-delivery ------------------------------------------
EN07 = (
    _j("EN07-A", "Platform Engineer", "software_engineering", "senior",
       ("terraform", "aws"), subcategories=("infrastructure_platform",)),
    _j("EN07-B", "Analytics Engineer", "data_scientist", "mid", ("dbt", "sql"),
       what="the warehouse"),
    _j("EN07-C", "Engineering Manager, Mobile", "software_engineering", "manager",
       ("people-management", "mobile"), subcategories=("mobile",)),
)

# --- EN-08: the JVN kill switch ---------------------------------------------
EN08 = (
    _j("EN08-A", "Embedded Software Engineer", "software_engineering", "mid", ("c", "rtos"),
       subcategories=("embedded_systems",)),
    _j("EN08-B", "Operations Manager", "business_ops", "manager", ("operations",)),
)

# --- EN-09 (v7): the subcategory dark knob ----------------------------------
EN09_A = (
    _j("EN09-A-SWE", "Backend Engineer, Ledger", "software_engineering", "senior",
       ("go", "postgres"), subcategories=("backend",)),
    _j("EN09-A-PM", "Technical Product Manager", "product_manager", "senior", ("apis",)),
)
EN09_B = (
    _j("EN09-B-SWE", "Android Engineer", "software_engineering", "mid", ("kotlin",),
       subcategories=("mobile",)),
    _j("EN09-B-PM", "Product Manager, Payments", "product_manager", "mid", ("payments",)),
)

# --- EN-10: isolation + request accounting ----------------------------------
EN10 = (
    _j("EN10-A", "Robotics Software Engineer", "software_engineering", "mid",
       ("ros", "c++"), subcategories=("robotics_autonomy",)),
    _j("EN10-B", "Quantitative Developer", "software_engineering", "senior",
       ("python", "trading"), subcategories=("quantitative",), confidence=0.7,
       judge=Judge(passed=True, confidence=0.9)),
    _j("EN10-C", "Recruiter", "business_ops", "mid", ("recruiting",), what="hiring"),
)

GROUPS: dict[str, tuple[Job, ...]] = {
    "EN01": EN01, "EN02": EN02, "EN03": EN03, "EN04": EN04, "EN05": EN05,
    "EN06": EN06, "EN07": EN07, "EN08": EN08, "EN09_A": EN09_A, "EN09_B": EN09_B,
    "EN10": EN10,
}
ALL_JOBS: tuple[Job, ...] = tuple(j for g in GROUPS.values() for j in g)
BY_ID: dict[str, Job] = {j.job_id: j for j in ALL_JOBS}
assert len(BY_ID) == len(ALL_JOBS), "fixture job ids must be unique across groups"

# Title keyword fallback for a job the table does not know. First match wins.
KEYWORD_RULES: tuple[tuple[str, str, str], ...] = (
    ("intern", "software_engineering", "intern"),
    ("product manager", "product_manager", "mid"),
    ("data scientist", "data_scientist", "mid"),
    ("engineer", "software_engineering", "mid"),
)


def _fallback_job(job_id: str, source_id: str, title: str) -> Job:
    low = (title or "").lower()
    for needle, category, level in KEYWORD_RULES:
        if needle in low:
            return Job(job_id=job_id, title=title, category=category, level=level,
                       tags=("e2e-unknown",), confidence=0.9)
    return Job(job_id=job_id, title=title, category="business_ops", level="mid",
               tags=("e2e-unknown",), confidence=0.9)


def job_for(item: dict[str, Any]) -> Job:
    jid = str(item.get("job_listing_id") or "")
    return BY_ID.get(jid) or _fallback_job(jid, str(item.get("source_id") or ""),
                                           str(item.get("title") or ""))


def classify_answer(item: dict[str, Any], *, category_override: str | None = None) -> dict[str, Any]:
    """The classify object the stub returns for one ``<job_data>`` element.

    Carries BOTH the v6 keys and the v7 ``subcategories`` pair; the v6 recorder
    simply never reads the extra two."""
    job = job_for(item)
    category = category_override or job.category
    if job.behaviour == "invalid_category" and category_override is None:
        category = "astronaut_engineering"
    is_swe = category == "software_engineering"
    subcats = list(job.subcategories) if is_swe else []
    return {
        "job_listing_id": item.get("job_listing_id"),
        "source_id": item.get("source_id"),
        "category": category,
        "subcategories": subcats,
        "level": job.level,
        "level_includes": job.level_includes,
        "tags": list(job.tags),
        "locations": [dict(SF_LOCATION)],
        "confidence": job.confidence,
        "subcategory_confidence": 0.9 if subcats else None,
        "reasoning": f"e2e stub classify: {job.title!r} -> {category}/{job.level}",
    }


def judge_answer(item: dict[str, Any]) -> dict[str, Any]:
    job = job_for(item)
    verdict = job.judge
    return {
        "job_listing_id": item.get("job_listing_id"),
        "source_id": item.get("source_id"),
        "passed": verdict.passed,
        "confidence": verdict.confidence,
        "needs_human": verdict.needs_human,
        "notes": verdict.notes,
        "reasoning": f"e2e stub judge for {job.title!r}",
        "corrections": dict(verdict.corrections),
    }


def subcategory_answer(item: dict[str, Any]) -> dict[str, Any]:
    job = job_for(item)
    subcats = list(job.subcategories)
    return {
        "job_listing_id": item.get("job_listing_id"),
        "source_id": item.get("source_id"),
        "subcategories": subcats,
        "subcategory_confidence": 0.9 if subcats else None,
    }


def expected_judged(group: tuple[Job, ...], ceiling: float = 0.85) -> set[str]:
    """Ids the enricher should route to the judge under judge:scope=low_confidence
    — computed from the FIXTURE confidence, independently of the enricher.
    ``invalid_category`` rows also go (a nulled facet flags needs_human)."""
    out = set()
    for job in group:
        if job.behaviour in ("garbled", "http_garbage"):
            continue  # never classified, so never judged
        if job.confidence < ceiling or job.behaviour == "invalid_category":
            out.add(job.job_id)
    return out


if __name__ == "__main__":
    if "--json" in sys.argv[1:]:
        print(json.dumps({g: [j.job_id for j in jobs] for g, jobs in GROUPS.items()}, indent=2))
