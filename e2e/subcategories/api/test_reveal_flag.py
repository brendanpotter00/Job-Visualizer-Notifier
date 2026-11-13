"""SC-05 — the reveal flag gates the UI, and ONLY the UI.

`app_settings.swe_subcategories_enabled` is a rollout switch flipped by hand
once subcategory coverage clears 90%. The asymmetry it ships with is
deliberate and documented in `subcategoryReveal.tsx`:

    the backend does NOT gate `?subcategory=` on it, so flipping it off hides
    the CONTROL — it does not stop a value a user already saved from filtering.

That is a decision, not an oversight: a clobber-on-mount guard would destroy
legitimately saved selections. It is also exactly the kind of decision that
gets "tidied up" later by someone who reads the flag as a feature gate, so it
needs a case. The UI half (control absent, results unchanged) is
`ui/reveal-flag.spec.ts`; this file is the wire half.

The flag's OFF state is written as an ABSENT ROW, because that is what ships:
`app_settings` has no seed row by design, so "missing key" is the real-world
off. The explicit-`false` path is covered by flipping on, then off again.
"""

from __future__ import annotations

import fixtures
import seed
from conftest import DB_DSN, SETTINGS, db, dump_json, result_keys, search


def _settings(http) -> dict:
    resp = http.get(SETTINGS)
    assert resp.status_code == 200, (
        f"GET {SETTINGS} answered {resp.status_code} — this endpoint is unauthenticated "
        f"and must never fail: a 500 here blanks the flag for every visitor mid-deploy. "
        f"Body: {resp.text[:300]}"
    )
    return resp.json()


def test_sc05_the_public_endpoint_reports_the_flag_both_ways(http, case_dir):
    """`GET /api/jobs/settings` is the only thing the browser reads the flag from."""
    conn = db.connect(DB_DSN)
    try:
        seed.set_reveal_flag(conn, True)
        on = _settings(http)
        seed.set_reveal_flag(conn, False)
        off = _settings(http)
    finally:
        conn.close()
    dump_json(case_dir / "settings.json", {"on": on, "off": off})

    assert on == {"sweSubcategoriesEnabled": True}, (
        f"with the flag set, GET {SETTINGS} answered {on!r}. The body must carry "
        "exactly the camelCase key the frontend reads, and nothing else — the "
        "response model names its fields precisely so a future admin-only setting "
        "cannot leak by being added to one dict."
    )
    assert off == {"sweSubcategoriesEnabled": False}, (
        f"with the flag row absent, GET {SETTINGS} answered {off!r}. An absent key "
        "means the code default, and for a reveal flag the code default is False — "
        "hidden-when-unset is the correct failure direction."
    )


def test_sc05_the_backend_does_not_gate_the_filter_on_the_flag(http, case_dir):
    """The whole point of the case. Flag OFF, `?subcategory=` still filters.

    If this ever goes red, do NOT change it to match: read
    `features/settings/subcategoryReveal.tsx` first. Making the backend gate on
    the flag silently breaks every saved filter the moment the flag is flipped
    back, which is the thing the asymmetry exists to prevent.
    """
    conn = db.connect(DB_DSN)
    try:
        seed.set_reveal_flag(conn, True)
        with_flag = result_keys(
            search(http, status="OPEN", subcategory="backend",
                   company=fixtures.PRIMARY_COMPANY.id, limit=100)
        )
        seed.set_reveal_flag(conn, False)
        without_flag = result_keys(
            search(http, status="OPEN", subcategory="backend",
                   company=fixtures.PRIMARY_COMPANY.id, limit=100)
        )
    finally:
        conn.close()
    dump_json(case_dir / "filter-by-flag.json",
              {"flagOn": sorted(with_flag), "flagOff": sorted(without_flag)})

    assert without_flag == with_flag, (
        f"?subcategory=backend returned {sorted(without_flag)} with the reveal flag "
        f"OFF but {sorted(with_flag)} with it ON. The backend must not gate the "
        "filter on a UI reveal switch — a user's saved subcategory filter has to "
        "keep working when the switch is off."
    )
    assert without_flag == fixtures.expected_for_subcategory("backend"), (
        "with the flag off the filter returned the wrong set entirely — it is not "
        "merely ungated, it is broken"
    )
    assert without_flag != fixtures.PRIMARY_SWE_KEYS, (
        "with the flag off, ?subcategory=backend returned every SWE row — the filter "
        "was silently dropped rather than applied. That is the failure mode a "
        "'did my matches come back' assertion cannot see."
    )


def test_sc05_the_facets_endpoint_publishes_the_children_regardless_of_the_flag(
    http, case_dir
):
    """`GET /api/jobs/facets` is data, not a reveal decision.

    The frontend combines the flag with the facets LENGTH
    (`flag && (facets?.subcategories?.length ?? 0) > 0`) precisely because the
    two are independent: facets are cached for an hour, the flag for a minute.
    If the backend started emptying `subcategories` when the flag is off, a warm
    facets cache would out-live the flip in the wrong direction.
    """
    conn = db.connect(DB_DSN)
    try:
        seed.set_reveal_flag(conn, False)
        resp = http.get("/api/jobs/facets")
        assert resp.status_code == 200, f"GET /api/jobs/facets: {resp.status_code}"
        body = resp.json()
    finally:
        conn.close()
    dump_json(case_dir / "facets.json", body)

    slugs = sorted(option["slug"] for option in body.get("subcategories", []))
    assert slugs == sorted(fixtures.EXPECTED_SUBCATEGORY_SLUGS), (
        f"GET /api/jobs/facets published {len(slugs)} subcategory options with the "
        f"reveal flag OFF; expected all {len(fixtures.EXPECTED_SUBCATEGORY_SLUGS)}. "
        "The facets endpoint is not the reveal switch."
    )
    parents = {option.get("parentSlug") for option in body["subcategories"]}
    assert parents == {fixtures.SWE_CATEGORY}, (
        f"every subcategory must hang off {fixtures.SWE_CATEGORY!r}; got parents "
        f"{parents!r}"
    )
