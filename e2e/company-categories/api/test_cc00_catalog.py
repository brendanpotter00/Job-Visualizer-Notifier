"""CC-00 — one source: the facets equal the committed JSON, which equals the
seeded tables.

`company_categories.json` is read by both halves of the product: the backend
seeds `company_categories` / `company_category_members` from it on boot and
serves the list as `companyCategories` on `GET /api/jobs/facets`, and the SPA
bundles the same file as its fallback. If any of the three disagree, the
dropdown would offer a type the search does not know, or the landing card would
promise companies the filter does not return.
"""

from __future__ import annotations

from conftest import FACETS, dump_json, fixtures


def test_cc00_facets_equal_the_json_in_order(http, case_dir):
    resp = http.get(FACETS)
    assert resp.status_code == 200, f"GET {FACETS} answered {resp.status_code}: {resp.text[:300]}"
    facets = resp.json()
    dump_json(case_dir / "facets.json", facets)
    assert "companyCategories" in facets, (
        "GET /api/jobs/facets has no companyCategories key: the SPA would fall back to its "
        "bundled list and never show the server's"
    )
    cats = fixtures.load_categories()
    assert [c["slug"] for c in cats] == fixtures.EXPECTED_SLUGS, (
        "the committed JSON is not the ten approved types in their display order"
    )
    served = [(o["slug"], o["label"], o["sortOrder"], o.get("parentSlug")) for o in facets["companyCategories"]]
    expected = [(c["slug"], c["label"], i, None) for i, c in enumerate(cats)]
    assert served == expected, f"facets {served} != JSON {expected}"


def test_cc00_tables_equal_the_json(db_conn):
    cats = fixtures.load_categories()
    with db_conn.cursor() as cur:
        cur.execute("SELECT slug, label, definition, sort_order FROM company_categories ORDER BY sort_order")
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT category_slug, company_id FROM company_category_members "
            "ORDER BY category_slug, position"
        )
        members: dict[str, list[str]] = {}
        for r in cur.fetchall():
            members.setdefault(r["category_slug"], []).append(r["company_id"])
    assert [(r["slug"], r["label"], r["definition"], r["sort_order"]) for r in rows] == [
        (c["slug"], c["label"], c["definition"], i) for i, c in enumerate(cats)
    ], "company_categories does not hold the JSON's categories in order"
    for c in cats:
        assert members.get(c["slug"]) == c["companyIds"], (
            f"company_category_members for {c['slug']} is not the JSON's companyIds in order"
        )


def test_cc00_the_fixture_membership_agrees_with_the_json():
    """The restated oracle in fixtures.COMPANY_TYPES is what every other case
    computes its expected set from; it has to describe the real data."""
    cats = fixtures.load_categories()
    for company, expected in fixtures.COMPANY_TYPES.items():
        actual = {c["slug"] for c in cats if company in c["companyIds"]}
        assert actual == expected, (
            f"fixtures.COMPANY_TYPES[{company!r}] = {sorted(expected)}, the JSON says {sorted(actual)}"
        )
