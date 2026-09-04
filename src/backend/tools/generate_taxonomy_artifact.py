"""Regenerate ``src/backend/taxonomy.json`` — the ONE artifact both repos read.

    cd src/backend && ../../.venv/bin/python tools/generate_taxonomy_artifact.py

NOTE ON THE DIRECTORY NAME: this lives in `tools/`, not `scripts/`, deliberately.
`pyproject.toml` sets `pythonpath = [".", "../.."]` for pytest, so a
`src/backend/scripts/` directory becomes a NAMESPACE PACKAGE that shadows the
repo-root `scripts` package — and `services/database.py` does
`from scripts.shared.database import Connection`. The shadowing is order-dependent
and would fail intermittently rather than loudly.

WHY THE ARTIFACT EXISTS
-----------------------
Every taxonomy guard in this repo is INTRA-repo: code vs migration vs API. The
enricher has its own intra-repo guards. Nothing compared ACROSS the two — which
is exactly how the live drift survived: ``job_categories`` had 7 seeded rows,
``CATEGORY_SLUGS`` had 7, and the enricher's ``taxonomy.CATEGORIES`` had 6, for
months, with every test green on both sides.

This epic widens that surface from 6 slugs to 21. ``taxonomy.json`` is committed
so the enricher can VENDOR it with a recorded sha256 and assert set equality
against its own constants.

IT IS GENERATED, NOT HAND-TYPED. The inputs are the migration seeds and
``services/enrichment_writer.py``. Hand-editing it would make it a fourth
independent copy of the taxonomy — the precise failure it exists to prevent.

Subcategory LABELS are the one thing that originates here: phase 1 ships
``job_subcategories`` empty, so there is no seed migration to read them from yet.
When SCHEMA-7 lands the seed, its label list and this one must agree, and
``api/tests/test_taxonomy_artifact.py`` is where that is asserted.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_SRC_BACKEND = Path(__file__).resolve().parents[1]
_REPO_ROOT = _SRC_BACKEND.parents[1]
for _p in (str(_SRC_BACKEND), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.services.enrichment_writer import (  # noqa: E402
    CATEGORY_SLUGS,
    LEVEL_SLUGS,
    SUBCATEGORY_PARENT,
    SUBCATEGORY_SLUGS,
    SUBCATEGORY_SOURCES,
)

ARTIFACT_PATH = _SRC_BACKEND / "taxonomy.json"

# The display labels for the 15 subcategories. Sole origin until SCHEMA-7's seed
# migration lands; asserted against that seed once it does.
SUBCATEGORY_LABELS = {
    "ai_engineering": "AI Engineering",
    "backend": "Backend",
    "data_engineering": "Data Engineering",
    "devops_sre": "DevOps & Site Reliability",
    "embedded_systems": "Embedded & Low-Level Systems",
    "forward_deployed": "Forward Deployed",
    "frontend": "Frontend",
    "full_stack": "Full Stack",
    "infrastructure_platform": "Infrastructure & Platform",
    "ml_engineering": "Machine Learning",
    "mobile": "Mobile",
    "qa_testing": "QA & Testing",
    "quantitative": "Quantitative & Trading Systems",
    "robotics_autonomy": "Robotics & Autonomy",
    "security": "Security",
}


def _load_migration(pattern: str) -> Any:
    path = next((_SRC_BACKEND / "alembic" / "versions").glob(pattern))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_artifact() -> dict[str, Any]:
    """Derive the artifact from the migrations + the code constants."""
    seed = _load_migration("*add_enrichment_tables*.py")
    intern = _load_migration("*add_intern_level*.py")
    retire = _load_migration("*retire_project_manager_category*.py")

    removed = set(retire.REMOVED_CATEGORIES)
    categories = [
        {"slug": slug, "label": label, "sort_order": order, "parent_slug": None}
        for slug, label, order in seed.CATEGORY_SEED
        if slug not in removed
    ]

    reranked = dict(getattr(intern, "_RERANK", {}))
    levels = [
        {
            "slug": slug,
            "label": label,
            "sort_order": reranked.get(slug, rank),
            "parent_slug": parent,
        }
        for slug, label, rank, parent in list(seed.LEVEL_SEED) + list(intern.ADDED_LEVELS)
    ]
    levels.sort(key=lambda row: row["sort_order"])

    subcategories = [
        {
            "slug": slug,
            "label": SUBCATEGORY_LABELS[slug],
            "sort_order": index,
            "parent_slug": SUBCATEGORY_PARENT,
        }
        for index, slug in enumerate(sorted(SUBCATEGORY_SLUGS))
    ]

    # Fail here rather than emit a wrong artifact.
    assert {c["slug"] for c in categories} == set(CATEGORY_SLUGS)
    assert {level["slug"] for level in levels} == set(LEVEL_SLUGS)
    assert {s["slug"] for s in subcategories} == set(SUBCATEGORY_SLUGS)

    return {
        "categories": categories,
        "levels": levels,
        "subcategories": subcategories,
        "subcategory_sources": sorted(SUBCATEGORY_SOURCES),
    }


def main() -> None:
    ARTIFACT_PATH.write_text(json.dumps(build_artifact(), indent=2) + "\n")
    print(f"wrote {ARTIFACT_PATH}")


if __name__ == "__main__":
    main()
