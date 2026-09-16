"""The fixture corpus — ONE source of truth for both tiers (PLAN.md §1, §3).

`add-companies/boards.py` is the shape this mirrors: the API tier imports it as
a plain top-level module, the UI tier reads `ui/corpus.ts` (which shells out to
`--json` below rather than re-declaring anything), and neither tier hard-codes a
title or a slug of its own.

WHY THIS SECTION SEEDS INSTEAD OF USING THE CORPUS
--------------------------------------------------
`add-companies` needs the real 46k-job clone: AC-06 compares a discovered
board's titles against every published company's, so an empty seed makes it
vacuous. This section is the opposite. The behaviours under test are
*set-membership* facts about one SQL operator (`&&`), and the source database
carries **three** `software_engineering` rows and **zero** subcategory arrays —
the corpus is not evidence here, it is noise that every assertion would have to
scope out. So the section runs on a schema-only database
(`ensure_db.sh --schema-only`) and seeds exactly the eleven rows below.

Eleven rows also means every case can assert an EXACT SET rather than a
count or a "contains". A filter case that only checks its matches are present
cannot catch the defect that matters — a filter that returns too much.

THE COMPANY SCOPE IS PART OF THE FIXTURE, NOT A CONVENIENCE
-----------------------------------------------------------
Every query in the API tier carries `?company=...`. That is legitimate — the
filter set ANDs, so scoping by company is the same mechanism SC-03 asserts —
and it is what makes `OTHER_COMPANY` below a real decoy rather than a row that
happens to sit somewhere else. The one place the scope is DROPPED is SC-03's
own cross-company assertion, which is where it has to be.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The 17 slugs, exactly as `enrichment_writer.SUBCATEGORY_SLUGS` holds them.
#: Re-declared rather than imported ON PURPOSE: a gate that reads the taxonomy
#: out of the code it is gating cannot notice the code dropping a slug. The
#: API tier asserts these two lists agree (`test_taxonomy.py`, SC-00), which is
#: the only place the import direction is allowed to close.
EXPECTED_SUBCATEGORY_SLUGS = [
    "ai_engineering",
    "backend",
    "data_engineering",
    "devops_sre",
    "embedded_systems",
    "forward_deployed",
    "frontend",
    "full_stack",
    "growth_engineering",
    "infrastructure_platform",
    "ml_engineering",
    "mobile",
    "product_engineering",
    "qa_testing",
    "quantitative",
    "robotics_autonomy",
    "security",
]

#: The parent every subcategory hangs off (`SUBCATEGORY_PARENT`).
SWE_CATEGORY = "software_engineering"

#: A category that may NOT carry subcategories — the SC-01 control.
NON_SWE_CATEGORY = "product_manager"

#: The one-way widening, as the feature declares it
#: (`SUBCATEGORY_FILTER_EXPANSION`). Selecting either key also surfaces
#: `full_stack`; selecting `full_stack` stays exact. SC-04 is this table.
EXPECTED_WIDENING = {"frontend": ["frontend", "full_stack"], "backend": ["backend", "full_stack"]}


@dataclass(frozen=True)
class Company:
    id: str
    display_name: str


@dataclass(frozen=True)
class Job:
    """One seeded `job_listings` row.

    `subcategories` is a TRISTATE and the distinction is the whole of SC-06:

      * ``None``  -> SQL NULL   -> "never evaluated", still in the backfill queue
      * ``[]``    -> SQL ``'{}'`` -> "evaluated, no specialty applies" (TERMINAL)
      * ``[...]`` -> the labelled case, ORDERED, index 0 is the primary

    A dataclass default of ``[]`` would quietly erase the first case, which is
    the same mistake `JobListingResponse.subcategories` documents at the wire.
    Hence the three named constructors below (`_labelled` / `_never_evaluated` /
    `_evaluated_empty`): a fixture that means NULL has to SAY so, and `is_null`
    records which of the two the author meant so `test_sc06` can check the
    database really holds it.
    """

    key: str
    title: str
    company: "Company"
    level: str
    category: str = SWE_CATEGORY
    subcategories: list[str] | None = None
    #: True when `subcategories` is meant to be SQL NULL rather than `'{}'`.
    #: Set by the constructors below, never by hand.
    is_null: bool = False

    @property
    def job_id(self) -> str:
        return self.key

    @property
    def source_id(self) -> str:
        return SOURCE_ID


#: Every seeded row shares one `source_id`. It is NOT prefixed `custom:` or
#: `recipe:` — those namespaces are subject to
#: `database._ORPHANED_CUSTOM_PREDICATE`, which drops a row whose `companies`
#: row is missing. A plain namespace keeps the fixtures on the same public read
#: path the real published boards take.
SOURCE_ID = "e2e_subcategories"

PRIMARY_COMPANY = Company(id="e2e-subcat-primary", display_name="E2E Subcat Primary")
#: SC-03's cross-company decoy: carries `backend`, differs only in company.
OTHER_COMPANY = Company(id="e2e-subcat-other", display_name="E2E Subcat Other")

ALL_COMPANIES = [PRIMARY_COMPANY, OTHER_COMPANY]


def _labelled(key: str, title: str, level: str, slugs: list[str], company: Company = PRIMARY_COMPANY) -> Job:
    return Job(key=key, title=title, company=company, level=level, subcategories=list(slugs))


def _never_evaluated(key: str, title: str, level: str, category: str = SWE_CATEGORY) -> Job:
    return Job(
        key=key, title=title, company=PRIMARY_COMPANY, level=level,
        category=category, subcategories=None, is_null=True,
    )


def _evaluated_empty(key: str, title: str, level: str) -> Job:
    return Job(key=key, title=title, company=PRIMARY_COMPANY, level=level, subcategories=[])


# --- The corpus ------------------------------------------------------------
#
# Read this table as the case list. Every row exists because at least one case
# would be weaker without it; the "why" column is not decoration.
#
#   key            subcats                    why it is here
#   -------------  -------------------------  --------------------------------
#   J-BACKEND      {backend}                  SC-02 match, SC-03 (senior) match
#   J-BACKEND-MID  {backend}                  SC-03: matches the SUBCATEGORY but
#                                             not the LEVEL — the AND decoy
#   J-FRONTEND     {frontend}                 SC-04: widening source
#   J-FULLSTACK    {full_stack}               SC-04: the row `frontend` and
#                                             `backend` must BOTH surface, and
#                                             that `full_stack` alone returns
#                                             ALONE
#   J-PAIR         {infrastructure_platform,  the two-slug ceiling, ordered.
#                   backend}                  `&&` must match on a NON-primary
#                                             slug too
#   J-MOBILE       {mobile}                   SC-02 subject — a slug with no
#                                             widening, so SC-02 cannot pass
#                                             for SC-04's reason
#   J-SECURITY     {security}                 SC-02 decoy: a DIFFERENT slug,
#                                             which must be absent
#   J-NULL         NULL                       SC-01 must include it, SC-06 must
#                                             hide it and serialize it as null
#   J-EMPTY        '{}'                       the other half of SC-06 — `&&` is
#                                             false, not NULL, and the wire must
#                                             say [] not null
#   J-PM           NULL, category=pm          SC-01 control: the parent filter
#                                             must not reach outside its category
#   J-OTHER-BACK   {backend} @ OTHER_COMPANY  SC-03's company decoy
JOBS: list[Job] = [
    _labelled("J-BACKEND", "Senior Backend Engineer", "senior", ["backend"]),
    _labelled("J-BACKEND-MID", "Backend Engineer II", "mid", ["backend"]),
    _labelled("J-FRONTEND", "Frontend Engineer", "mid", ["frontend"]),
    _labelled("J-FULLSTACK", "Full Stack Engineer", "senior", ["full_stack"]),
    _labelled("J-PAIR", "Platform Engineer, Backend Systems", "senior",
              ["infrastructure_platform", "backend"]),
    _labelled("J-MOBILE", "Mobile Engineer, iOS", "mid", ["mobile"]),
    _labelled("J-SECURITY", "Security Engineer", "senior", ["security"]),
    _never_evaluated("J-NULL", "Software Engineer, Unevaluated", "mid"),
    _evaluated_empty("J-EMPTY", "Software Engineer, Generalist", "mid"),
    _never_evaluated("J-PM", "Product Manager, Platform", "senior", category=NON_SWE_CATEGORY),
    _labelled("J-OTHER-BACK", "Backend Engineer, Other Co", "senior", ["backend"],
              company=OTHER_COMPANY),
]

BY_KEY: dict[str, Job] = {j.key: j for j in JOBS}


def keys(*names: str) -> set[str]:
    """`keys("J-BACKEND", "J-PAIR")` — a set literal that fails loudly on a typo.

    A misspelled key in an expected-set literal silently weakens the assertion
    (the row is "expected absent" instead of "expected present"), which is the
    one way a set-equality case can go green while testing nothing.
    """
    missing = [n for n in names if n not in BY_KEY]
    if missing:
        raise KeyError(f"unknown fixture key(s): {missing}; known: {sorted(BY_KEY)}")
    return set(names)


#: Every SWE row of the primary company — SC-01's expected set. Note it
#: INCLUDES the NULL and the `'{}'` rows and EXCLUDES the product-manager row.
PRIMARY_SWE_KEYS = {
    j.key for j in JOBS if j.company is PRIMARY_COMPANY and j.category == SWE_CATEGORY
}

#: Everything the primary company owns, whatever its category.
PRIMARY_ALL_KEYS = {j.key for j in JOBS if j.company is PRIMARY_COMPANY}


def expected_for_subcategory(slug: str, *, company: Company | None = PRIMARY_COMPANY) -> set[str]:
    """The set a `?subcategory=<slug>` query must return, derived from the
    fixture table and :data:`EXPECTED_WIDENING` — NOT from the code under test.

    This is the oracle. It applies the widening itself, so SC-04 is asserting
    an independently-computed answer rather than re-running
    `job_search.expand_subcategories` and comparing it to itself.
    """
    wanted = set(EXPECTED_WIDENING.get(slug, [slug]))
    out = set()
    for job in JOBS:
        if company is not None and job.company is not company:
            continue
        if job.subcategories and wanted & set(job.subcategories):
            out.add(job.key)
    return out


__all__ = [
    "ALL_COMPANIES",
    "BY_KEY",
    "Company",
    "EXPECTED_SUBCATEGORY_SLUGS",
    "EXPECTED_WIDENING",
    "Job",
    "JOBS",
    "NON_SWE_CATEGORY",
    "OTHER_COMPANY",
    "PRIMARY_ALL_KEYS",
    "PRIMARY_COMPANY",
    "PRIMARY_SWE_KEYS",
    "SOURCE_ID",
    "SWE_CATEGORY",
    "expected_for_subcategory",
    "keys",
]


def _as_json() -> str:
    """The corpus, for the UI tier.

    `ui/corpus.ts` shells out to this rather than re-declaring the eleven rows
    in TypeScript — the same trick `add-companies/ui/boards.ts` uses against
    `boards.py`, and for the same reason: two hand-maintained copies of a
    fixture table drift, and the drift shows up as a UI case asserting a title
    the seeder never wrote.
    """
    import json

    return json.dumps(
        {
            "sourceId": SOURCE_ID,
            "sweCategory": SWE_CATEGORY,
            "nonSweCategory": NON_SWE_CATEGORY,
            "subcategorySlugs": EXPECTED_SUBCATEGORY_SLUGS,
            "widening": EXPECTED_WIDENING,
            "companies": [{"id": c.id, "displayName": c.display_name} for c in ALL_COMPANIES],
            "jobs": [
                {
                    "key": j.key,
                    "title": j.title,
                    "companyId": j.company.id,
                    "level": j.level,
                    "category": j.category,
                    "subcategories": j.subcategories,
                }
                for j in JOBS
            ],
        },
        indent=2,
    )


if __name__ == "__main__":
    import sys as _sys

    if "--json" in _sys.argv[1:]:
        print(_as_json())
    else:
        print(f"{len(JOBS)} fixture jobs across {len(ALL_COMPANIES)} companies")
        for _j in JOBS:
            _state = "NULL" if _j.is_null else (_j.subcategories or "{}")
            print(f"  {_j.key:<14} {_j.level:<7} {_j.category:<22} {_state}")
