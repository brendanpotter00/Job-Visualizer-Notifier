"""EN-00 — the enricher and JVN agree on the taxonomy, over the wire.

A pin under every other case: the enricher nulls any category/level outside its
own ``taxonomy.CATEGORIES``/``LEVELS`` before write-back, and JVN FK-rejects any
outside its dimension tables. If the two sets drift, rows classify "fine" on the
laptop and fail (or silently null) on the server — the exact failure the
taxonomy artifact exists to prevent.

This compares the SANDBOX enricher's own constants (read by its own interpreter
— so ``--enricher-ref`` checks THAT version's taxonomy) against what the running
backend SERVES on ``GET /api/jobs/facets``, i.e. what is actually in the
dimension tables. The unit suite's parity test compares the constants to the
committed artifact; this is the live-server half.

The section's dimension rows come from ``src/backend/taxonomy.json`` (see
``seed.repair_known_drift``), so a red here means the enricher's taxonomy and
JVN's generated artifact disagree — fix the taxonomy, never this test.
"""

from __future__ import annotations

import json

import pytest

_READ = (
    "import json; from job_enricher import taxonomy as t; "
    "print(json.dumps({'categories': sorted(t.CATEGORIES), 'levels': sorted(t.LEVELS), "
    "'subcategories': sorted(getattr(t, 'SUBCATEGORIES', ()))}))"
)


def _both(sandbox, http):
    enricher = json.loads(sandbox.python(_READ))
    resp = http.get("/api/jobs/facets")
    assert resp.status_code == 200, f"/api/jobs/facets answered {resp.status_code}: {resp.text[:300]}"
    facets = resp.json()
    served = {key: sorted(o["slug"] for o in facets.get(key, [])) for key in ("categories", "levels", "subcategories")}
    return enricher, served


@pytest.mark.fast
def test_en00_categories_and_levels_match_the_served_facets(sandbox, http, step):
    step("reading the sandbox enricher's taxonomy and JVN's served facets")
    enricher, served = _both(sandbox, http)
    step("comparing category slugs")
    assert enricher["categories"] == served["categories"], (
        f"category drift: enricher-only {sorted(set(enricher['categories']) - set(served['categories']))}, "
        f"JVN-only {sorted(set(served['categories']) - set(enricher['categories']))}"
    )
    step("comparing level slugs")
    assert enricher["levels"] == served["levels"], (
        f"level drift: enricher-only {sorted(set(enricher['levels']) - set(served['levels']))}, "
        f"JVN-only {sorted(set(served['levels']) - set(enricher['levels']))}"
    )


@pytest.mark.fast
@pytest.mark.v7
def test_en00_subcategory_slugs_match_the_served_facets(sandbox, http, step):
    step("comparing the 17 subcategory slugs")
    enricher, served = _both(sandbox, http)
    assert len(enricher["subcategories"]) == 17, enricher["subcategories"]
    assert enricher["subcategories"] == served["subcategories"]
