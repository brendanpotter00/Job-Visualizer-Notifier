"""The onboarding section's fixtures — ONE source of truth for both tiers.

The API tier imports this module; the UI tier reads it through `ui/corpus.ts`,
which shells out to `--json` below instead of re-declaring anything (the
`subcategories/fixtures.py` pattern, for the same reason: two hand-kept copies
of a fixture table drift, and the drift reads as a product regression).

Three things live here:

* the IDENTITY rules — every case mints its own brand-new identity whose `sub`
  starts with :data:`IDENTITY_PREFIX` (PLAN.md §4). The prefix is also the
  fence the purge helper refuses to cross;
* the one PRE-EXISTING account — already stamped, the way the migration's
  backfill left every account that existed at deploy time (OB-09 / OB-U9);
* a five-row JOB CORPUS, so "the list opens with the answers applied" is a
  visible fact and not only filter text. Every row but one is a decoy for the
  headline answers, and each decoy fails exactly ONE of the four answers, so a
  dropped dimension shows up as one specific row that should not be there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Every identity this section creates has a `sub` starting with this, and the
#: purge helper refuses any other. Never reuse shared/auth's `primary` / `other`
#: identities: other sections own their state.
IDENTITY_PREFIX = "e2e|onboarding-"
EMAIL_PREFIX = "e2e+onboarding-"
EMAIL_DOMAIN = "jvn.test"

SWE = "software_engineering"
PM = "product_manager"

SAN_FRANCISCO = "San Francisco, CA, US"
NEW_YORK = "New York, NY, US"

#: What a brand-new `user_saved_filters` row must get for its time windows: the
#: app defaults (Recent 'all', Trend '90d'). Written out here, NOT imported from
#: `saved_filters_service.default_saved_filters()`, because the column's own DB
#: defaults are the stale '3h' / '7d' and a gate that reads the expected value
#: out of the code it gates cannot notice the code changing it.
NEW_ROW_RECENT_WINDOW = "all"
NEW_ROW_TREND_WINDOW = "90d"


@dataclass(frozen=True)
class Answers:
    """The four answers, exactly as `POST /api/users/onboarding` takes them."""

    category: list[str] = field(default_factory=list)
    subcategory: list[str] = field(default_factory=list)
    level: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)

    def body(self, *, skipped: bool, step: int) -> dict[str, object]:
        return {
            "skipped": skipped,
            "category": list(self.category),
            "subcategory": list(self.subcategory),
            "level": list(self.level),
            "locations": list(self.locations),
            "step": step,
        }

    def as_saved(self) -> dict[str, list[str]]:
        return {
            "category": list(self.category),
            "subcategory": list(self.subcategory),
            "level": list(self.level),
            "locations": list(self.locations),
        }


#: OB-U1's answers: Software Engineering → Backend, Entry, San Francisco.
HEADLINE = Answers(category=[SWE], subcategory=["backend"], level=["entry"], locations=[SAN_FRANCISCO])

#: A deliberately DIFFERENT set, for "the first answers win" (OB-04).
OTHER = Answers(category=[PM], subcategory=[], level=["senior"], locations=[NEW_YORK])


@dataclass(frozen=True)
class PreexistingAccount:
    sub: str
    email: str
    user_id: str
    #: Fixed and in the past, so "unchanged" is checkable to the microsecond.
    stamped_at: str


#: The account that existed before the feature shipped. Seeded STAMPED, with no
#: saved-filters row, by `seed.py` on every run.
PREEXISTING = PreexistingAccount(
    sub=f"{IDENTITY_PREFIX}preexisting",
    email=f"{EMAIL_PREFIX}preexisting@{EMAIL_DOMAIN}",
    user_id="e2eonboardingpreexisting",
    stamped_at="2026-01-15T12:00:00+00:00",
)


# --- The job corpus ---------------------------------------------------------

SOURCE_ID = "e2e_onboarding"
COMPANY_ID = "e2e-onboarding-co"
COMPANY_NAME = "E2E Onboarding Co"


@dataclass(frozen=True)
class Job:
    key: str
    title: str
    category: str
    level: str
    #: None = SQL NULL (never evaluated); a non-SWE row carries NULL.
    subcategories: list[str] | None
    #: Canonical `locations.canonical_name` the row is tagged with.
    location: str
    #: The raw `job_listings.location` text a card shows.
    raw_location: str


#   key                 cat  subcats     level   place  why
#   ------------------  ---  ----------  ------  -----  ------------------------------
#   OB-MATCH            SWE  {backend}   entry   SF     the ONE row the headline shows
#   OB-DECOY-FRONTEND   SWE  {frontend}  entry   SF     fails only the specialty
#   OB-DECOY-SENIOR     SWE  {backend}   senior  SF     fails only the level
#   OB-DECOY-NEW-YORK   SWE  {backend}   entry   NY     fails only the location
#   OB-PM               PM   NULL        entry   SF     fails only the category; the ONE
#                                                       row Product Manager shows (OB-U5)
JOBS: list[Job] = [
    Job("OB-MATCH", "Backend Engineer I", SWE, "entry", ["backend"], SAN_FRANCISCO, "San Francisco, CA"),
    Job("OB-DECOY-FRONTEND", "Frontend Engineer I", SWE, "entry", ["frontend"], SAN_FRANCISCO, "San Francisco, CA"),
    Job("OB-DECOY-SENIOR", "Senior Backend Engineer", SWE, "senior", ["backend"], SAN_FRANCISCO, "San Francisco, CA"),
    Job("OB-DECOY-NEW-YORK", "Backend Engineer I, New York", SWE, "entry", ["backend"], NEW_YORK, "New York, NY"),
    Job("OB-PM", "Associate Product Manager", PM, "entry", None, SAN_FRANCISCO, "San Francisco, CA"),
]
BY_KEY: dict[str, Job] = {j.key: j for j in JOBS}

#: The product's two expansions, restated from the plan rather than imported
#: (same reason as the time windows above): Backend also surfaces Full Stack,
#: Entry also surfaces New Grad.
_SUBCATEGORY_WIDENING = {"backend": {"backend", "full_stack"}, "frontend": {"frontend", "full_stack"}}
_LEVEL_WIDENING = {"entry": {"entry", "new_grad"}}


def expected_keys(answers: Answers) -> list[str]:
    """The rows the Recent list must show for `answers`, derived from the
    fixture table — the ORACLE, not a call into the code under test.

    Implements the decided rules: every dimension ANDs; a specialty narrows only
    software-engineering rows, so another selected role keeps all its rows.
    """
    wanted_subs: set[str] = set()
    for s in answers.subcategory:
        wanted_subs |= _SUBCATEGORY_WIDENING.get(s, {s})
    wanted_levels: set[str] = set()
    for lv in answers.level:
        wanted_levels |= _LEVEL_WIDENING.get(lv, {lv})
    other_role_picked = any(c != SWE for c in answers.category)
    out: list[str] = []
    for job in JOBS:
        if answers.category and job.category not in answers.category:
            continue
        if wanted_subs and (job.category == SWE or not other_role_picked):
            if not wanted_subs & set(job.subcategories or []):
                continue
        if wanted_levels and job.level not in wanted_levels:
            continue
        if answers.locations and job.location not in answers.locations:
            continue
        out.append(job.key)
    return out


def _as_json() -> str:
    import json

    def _answers(a: Answers) -> dict[str, object]:
        return {**a.as_saved(), "expectedKeys": expected_keys(a)}

    return json.dumps(
        {
            "identityPrefix": IDENTITY_PREFIX,
            "emailPrefix": EMAIL_PREFIX,
            "emailDomain": EMAIL_DOMAIN,
            "preexisting": {
                "sub": PREEXISTING.sub,
                "email": PREEXISTING.email,
                "stampedAt": PREEXISTING.stamped_at,
            },
            "headline": _answers(HEADLINE),
            "productManagerOnly": _answers(Answers(category=[PM])),
            "everything": _answers(Answers()),
            "jobs": [
                {
                    "key": j.key,
                    "title": j.title,
                    "category": j.category,
                    "level": j.level,
                    "subcategories": j.subcategories,
                    "location": j.location,
                }
                for j in JOBS
            ],
        },
        indent=2,
    )


if __name__ == "__main__":
    import sys

    if "--json" in sys.argv[1:]:
        print(_as_json())
    else:
        for _j in JOBS:
            print(f"  {_j.key:<18} {_j.category:<22} {_j.level:<7} {_j.location:<22} {_j.subcategories}")
        print(f"headline -> {expected_keys(HEADLINE)}")
