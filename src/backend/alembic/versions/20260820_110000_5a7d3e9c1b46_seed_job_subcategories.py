"""Phase 2 of the SWE-subcategories epic: SEED the 15 dimension rows.

Scaffolded by ``alembic revision --autogenerate``; the generated
``upgrade``/``downgrade`` bodies came back **EMPTY**, and that emptiness is the
proof there is no schema drift — this is a pure DIMENSION-SEED change, which
autogenerate cannot express (it diffs schema, not data). ``0b61e444ea25:7-12``
documents the same situation for the ``intern`` level. The seed ops below are
hand-added, exactly as ``0fa33aca5bda`` and ``0b61e444ea25`` do.

WHY THIS IS A PUBLISH, NOT A SCHEMA CHANGE
------------------------------------------
``job_subcategories``' only consumer is ``get_facets`` -> the public filter
dropdown. The moment rows exist here, fifteen checkboxes become available to
every reader of ``GET /api/jobs/facets``. That is why SCHEMA-1 shipped the table
EMPTY and this revision is deliberately separate: structure, the write path and
the coverage counters all land and get verified against production while the
dropdown is provably unchanged, and only then does the dimension get published.

The reveal FLAG (``app_settings.swe_subcategories_enabled``) is a second,
independent gate on the UI: this seed makes the options *available*, the flag
makes the tree *visible*. Both exist because they fail in different directions —
the seed cannot be un-published cheaply, the flag can be flipped back in a
second.

THE CANONICAL LIST
------------------
Label-alphabetical, which for this set is also slug-alphabetical, so
``sorted(enrichment_writer.SUBCATEGORY_SLUGS)`` reproduces ``sort_order`` 0..14
exactly. Every row's ``parent_slug`` is ``software_engineering``.

``quantitative`` is labelled **"Quantitative & Trading Systems"**. Some earlier
draft mocks say "Quantitative & Trading"; the MOCK is the thing that gets
corrected, not this table. ``TestTaxonomyParity`` is what holds the six copies of
this list (this seed, ``enrichment_writer.SUBCATEGORY_SLUGS``, the frontend's
``FALLBACK_SUBCATEGORIES``, the enricher's ``taxonomy.SUBCATEGORIES``, the ollama
response schema and SKILL.md §1b) in lock-step.

Idempotent: ``ON CONFLICT (slug) DO NOTHING``, so re-running is a no-op.

DEPLOY CONTEXT
--------------
``SET LOCAL lock_timeout = '5s'`` first in both directions, same line and same
reason as ``7c1a4f2b9e30`` — prod runs with no ``lock_timeout`` at all and this
migration runs inside the FastAPI lifespan. ``job_subcategories`` has fifteen
rows and one reader, so the lock is trivially short; the guard is here for
consistency, not because this statement is the risky one.

DOWNGRADE
---------
Deletes exactly the fifteen slugs this migration inserted — never a bare
``DELETE FROM job_subcategories``, so a hand-added row would survive. The table
itself belongs to ``7c1a4f2b9e30``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
#
# down_revision is SCHEMA-11 (`2e6f81ad4b57`, retire_project_manager_category),
# the current head of the epic's chain. See api/tests/test_alembic_single_head.py
# for the full pinned order.
revision: str = '5a7d3e9c1b46'
down_revision: Union[str, None] = '2e6f81ad4b57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The fifteen rows this migration seeds: (slug, label, sort_order, parent_slug).
#
# Exported so the parity test IMPORTS these rather than re-typing them — the
# `ADDED_LEVELS` pattern at 0b61e444ea25:46-48. The parent stays in the tuple
# because the INSERT needs it and the parity test asserts on it.
ADDED_SUBCATEGORIES = [
    ("ai_engineering", "AI Engineering", 0, "software_engineering"),
    ("backend", "Backend", 1, "software_engineering"),
    ("data_engineering", "Data Engineering", 2, "software_engineering"),
    ("devops_sre", "DevOps & Site Reliability", 3, "software_engineering"),
    ("embedded_systems", "Embedded & Low-Level Systems", 4, "software_engineering"),
    ("forward_deployed", "Forward Deployed", 5, "software_engineering"),
    ("frontend", "Frontend", 6, "software_engineering"),
    ("full_stack", "Full Stack", 7, "software_engineering"),
    ("infrastructure_platform", "Infrastructure & Platform", 8, "software_engineering"),
    ("ml_engineering", "Machine Learning", 9, "software_engineering"),
    ("mobile", "Mobile", 10, "software_engineering"),
    ("qa_testing", "QA & Testing", 11, "software_engineering"),
    ("quantitative", "Quantitative & Trading Systems", 12, "software_engineering"),
    ("robotics_autonomy", "Robotics & Autonomy", 13, "software_engineering"),
    ("security", "Security", 14, "software_engineering"),
]

# Query-time filter-expansion edges, as (widens_into, selected) pairs.
#
# This CANNOT be derived from `parent_slug`: that column holds the CATEGORY
# parent (`software_engineering` on every row), and `full_stack` has TWO
# expansion parents, which one self-FK column cannot express.
#
# This export is the SEED-SIDE MIRROR, read only by `TestTaxonomyParity` so the
# query-time rule and the dimension it describes cannot drift apart. The
# query-time rule itself is
# `api.services.enrichment_writer.SUBCATEGORY_FILTER_EXPANSION` — that is the
# one the search path executes.
SUBCATEGORY_FILTER_EDGES = [
    ("full_stack", "frontend"),
    ("full_stack", "backend"),
]


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    # (empty — no schema change; these are dimension-seed rows, see the module
    # docstring)
    # ### end Alembic commands ###
    op.execute("SET LOCAL lock_timeout = '5s'")

    bind = op.get_bind()
    insert = sa.text(
        "INSERT INTO job_subcategories (slug, label, parent_slug, sort_order) "
        "VALUES (:slug, :label, :parent, :sort_order) "
        "ON CONFLICT (slug) DO NOTHING"
    )
    for slug, label, sort_order, parent in ADDED_SUBCATEGORIES:
        bind.execute(
            insert,
            {"slug": slug, "label": label, "parent": parent, "sort_order": sort_order},
        )


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    # ### end Alembic commands ###
    op.execute("SET LOCAL lock_timeout = '5s'")

    bind = op.get_bind()
    delete = sa.text("DELETE FROM job_subcategories WHERE slug = :slug")
    for slug, _label, _sort_order, _parent in ADDED_SUBCATEGORIES:
        bind.execute(delete, {"slug": slug})
