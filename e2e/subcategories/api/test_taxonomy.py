"""SC-00 — the taxonomy the other six cases are written against.

Not one of the user's named behaviours; a PIN under them. Every case below it
asserts something about specific slugs, and all of those assertions go quietly
vacuous if the slug set moves — a filter on a slug nobody publishes any more
matches nothing, and "matches nothing" is what half of them expect.

This is also the one place the import direction is allowed to close.
`fixtures.EXPECTED_SUBCATEGORY_SLUGS` re-declares the 17 rather than importing
them, precisely so a gate cannot read the taxonomy out of the code it is
gating; here the three copies are made to agree:

    fixtures.py  (the gate's own declaration)
      == enrichment_writer.SUBCATEGORY_SLUGS  (the code arbiter)
      == job_subcategories                     (the seeded dimension)
      == GET /api/jobs/facets                  (what the UI tree is built from)

Four places, one list. A slug added to the enricher without a migration, or
seeded without being added to the code, shows up here rather than as a
mystery empty dropdown.
"""

from __future__ import annotations

import fixtures
from conftest import db, DB_DSN, dump_json


def test_sc00_the_gate_and_the_code_agree_on_the_seventeen_slugs():
    from api.services.enrichment_writer import (
        MAX_SUBCATEGORIES,
        SUBCATEGORY_FILTER_EXPANSION,
        SUBCATEGORY_PARENT,
        SUBCATEGORY_SLUGS,
    )

    assert sorted(SUBCATEGORY_SLUGS) == sorted(fixtures.EXPECTED_SUBCATEGORY_SLUGS), (
        "enrichment_writer.SUBCATEGORY_SLUGS has moved away from the list this "
        "section's cases are written against.\n"
        f"  code only:  {sorted(set(SUBCATEGORY_SLUGS) - set(fixtures.EXPECTED_SUBCATEGORY_SLUGS))}\n"
        f"  gate only:  {sorted(set(fixtures.EXPECTED_SUBCATEGORY_SLUGS) - set(SUBCATEGORY_SLUGS))}\n"
        "Update fixtures.EXPECTED_SUBCATEGORY_SLUGS *deliberately*, and check whether "
        "any case's expected set changed with it."
    )
    assert SUBCATEGORY_PARENT == fixtures.SWE_CATEGORY, (
        f"the subcategory dimension now hangs off {SUBCATEGORY_PARENT!r}, not "
        f"{fixtures.SWE_CATEGORY!r} — SC-01's whole premise moved"
    )
    assert MAX_SUBCATEGORIES == 2, (
        f"MAX_SUBCATEGORIES is {MAX_SUBCATEGORIES}; the fixture corpus seeds a "
        "two-slug row (J-PAIR) as the ceiling case and would need a third to stay "
        "honest at a higher cap"
    )
    declared = {k: list(v) for k, v in SUBCATEGORY_FILTER_EXPANSION.items()}
    assert declared == fixtures.EXPECTED_WIDENING, (
        f"the widening table changed: code says {declared!r}, the gate expects "
        f"{fixtures.EXPECTED_WIDENING!r}. SC-04 is exactly this table — if the change "
        "is intended, move fixtures.EXPECTED_WIDENING and re-read SC-04's expected sets."
    )


def test_sc00_the_seeded_dimension_matches(db_conn, case_dir):
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT slug, label, parent_slug, sort_order FROM job_subcategories "
            "ORDER BY sort_order"
        )
        rows = [dict(r) for r in cur.fetchall()]
    dump_json(case_dir / "job_subcategories.json", rows)

    slugs = [r["slug"] for r in rows]
    assert sorted(slugs) == sorted(fixtures.EXPECTED_SUBCATEGORY_SLUGS), (
        f"job_subcategories holds {len(slugs)} rows {slugs!r}; expected the 17 seeded "
        "by migration 5a7d3e9c1b46"
    )
    assert slugs == sorted(slugs), (
        "the seed's sort_order no longer reproduces `sorted(SUBCATEGORY_SLUGS)`. The "
        "seed is DERIVED from that sort on both sides precisely so inserting a slug "
        "renumbers everything after it; a hand-numbered row breaks that."
    )
    assert {r["parent_slug"] for r in rows} == {fixtures.SWE_CATEGORY}, (
        "a subcategory row hangs off something other than software_engineering"
    )


def test_sc00_the_facets_endpoint_publishes_the_same_list(http, case_dir):
    """What the UI tree is actually built from. A dimension seeded correctly but
    not published still gives the user an empty dropdown."""
    resp = http.get("/api/jobs/facets")
    assert resp.status_code == 200, f"GET /api/jobs/facets: {resp.status_code}"
    body = resp.json()
    dump_json(case_dir / "facets.json", body)

    published = sorted(option["slug"] for option in body.get("subcategories", []))
    assert published == sorted(fixtures.EXPECTED_SUBCATEGORY_SLUGS), (
        f"GET /api/jobs/facets published {published!r}; expected the 17 slugs. The "
        "frontend gates the tree on `flag && facets.subcategories.length > 0`, so an "
        "empty or short list here renders a parent row that expands into nothing."
    )
    assert fixtures.SWE_CATEGORY in {o["slug"] for o in body.get("categories", [])}, (
        "the facets response publishes subcategories but not their parent category, "
        "so the tree has nothing to hang them under"
    )
