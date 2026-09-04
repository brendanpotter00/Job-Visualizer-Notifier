"""Tests for database service layer (services/database.py)."""

import json

from api.services.database import (
    _build_where,
    _ensure_json_string,
    get_job_by_id,
    get_jobs,
)
from .conftest import _insert_job, _make_job


class TestEnsureJsonString:
    """Verify JSONB auto-parsing from psycopg2 is re-serialized correctly."""

    def test_dict_returns_json_string(self):
        result = _ensure_json_string({"key": "value"})
        assert result == json.dumps({"key": "value"})
        assert isinstance(result, str)

    def test_list_returns_json_string(self):
        result = _ensure_json_string([1, 2, 3])
        assert result == json.dumps([1, 2, 3])

    def test_none_returns_empty_object(self):
        assert _ensure_json_string(None) == "{}"

    def test_string_returned_unchanged(self):
        s = '{"already": "json"}'
        assert _ensure_json_string(s) == s


def _render(where) -> str:
    """Render a psycopg2 Composable to inspect the literal SQL fragments.

    _build_where returns a ``sql.Composable``; its string form exposes the
    column names each condition targets (e.g. ``enrichment_category``) so a
    test can assert the right column is filtered without a live cursor.
    """
    return str(where)


class TestBuildWhere:
    """The WHERE-builder gained ``category`` + ``level`` (with the new_grad⊂entry
    expansion). These are pure-function checks: assert the emitted params and
    that the intended enrichment columns appear in the SQL."""

    def test_no_filters_is_empty(self):
        where, params = _build_where()
        assert params == []
        assert "WHERE" not in _render(where)

    def test_level_entry_expands_to_entry_and_new_grad(self):
        where, params = _build_where(level="entry")
        # entry surfaces new-grad roles too (load-bearing hierarchy case).
        assert params == [["entry", "new_grad"]]
        assert "enrichment_level" in _render(where)

    def test_level_new_grad_stays_exact(self):
        where, params = _build_where(level="new_grad")
        assert params == [["new_grad"]]

    def test_level_senior_stays_exact(self):
        where, params = _build_where(level="senior")
        assert params == [["senior"]]

    def test_category_filters_on_enrichment_category(self):
        where, params = _build_where(category="software_engineering")
        assert params == ["software_engineering"]
        assert "enrichment_category" in _render(where)

    def test_category_and_level_combined(self):
        where, params = _build_where(category="business_ops", level="entry")
        assert params == ["business_ops", ["entry", "new_grad"]]

    def test_combined_with_status_and_company(self):
        where, params = _build_where(
            company="google", status="OPEN", category="data_scientist", level="new_grad"
        )
        # Order mirrors the builder: company, status, category, level.
        assert params == ["google", "OPEN", "data_scientist", ["new_grad"]]
        rendered = _render(where)
        assert "company = %s" in rendered
        assert "status = %s" in rendered
        assert "enrichment_category" in rendered
        assert "enrichment_level" in rendered

    def test_hidden_company_predicate_absent_by_default(self):
        # Admin/diagnostic callers (get_stats, get_scrape_runs) rely on the
        # default staying off — a deactivated company must stay visible there.
        where, params = _build_where(company="google")
        assert params == ["google"]
        assert "NOT EXISTS" not in _render(where)

    def test_hidden_company_predicate_added_when_requested(self):
        where, params = _build_where(exclude_hidden_companies=True)
        rendered = _render(where)
        assert "WHERE" in rendered
        assert "NOT EXISTS" in rendered
        assert "c.enabled" in rendered
        # The predicate is a static correlated subquery — it must not add
        # placeholders, or every caller's param ordering would shift.
        assert params == []

    def test_hidden_company_predicate_composes_with_other_filters(self):
        where, params = _build_where(
            company="google", status="OPEN", exclude_hidden_companies=True
        )
        # Param order and count are unchanged by the guard.
        assert params == ["google", "OPEN"]
        rendered = _render(where)
        assert "company = %s" in rendered
        assert "status = %s" in rendered
        assert "NOT EXISTS" in rendered


# --- SWE subcategories: the tri-state must survive BOTH read paths ----------
#
# `_LIST_COLUMNS` is imported by `services/job_search.py`, so aliasing the column
# there serializes it on the list path AND on /api/jobs/search with one edit. The
# detail route takes a different route entirely (`SELECT job_listings.*`), which
# is why `_row_to_job_dict` needs its own rename shim — and why the assertions
# below are run against the DETAIL route as well as the list route.


class TestSubcategorySerialization:
    THREE_STATES = (
        ("sub-labelled", ["backend", "ai_engineering"]),
        ("sub-never", None),
        ("sub-empty", []),
    )

    def _seed(self, db_conn):
        for job_id, subcats in self.THREE_STATES:
            _insert_job(
                db_conn,
                _make_job(
                    {
                        "id": job_id,
                        "source_id": "sub-src",
                        "enrichment_subcategories": subcats,
                    }
                ),
            )
        db_conn.commit()

    def test_list_path_serializes_all_three_states(self, db_conn):
        self._seed(db_conn)
        rows = {
            j["id"]: j
            for j in get_jobs(db_conn, limit=100)
            if j["source_id"] == "sub-src"
        }

        assert rows["sub-labelled"]["subcategories"] == ["backend", "ai_engineering"]
        # NOT [] — "never evaluated" is a different fact from "nothing applies".
        assert rows["sub-never"]["subcategories"] is None
        assert rows["sub-empty"]["subcategories"] == []

    def test_detail_path_serializes_all_three_states(self, db_conn):
        """The detail route returns RAW column names, so it needs the shim in
        `_row_to_job_dict`. Passing on the list path proves nothing here."""
        self._seed(db_conn)

        labelled = get_job_by_id(db_conn, "sub-src", "sub-labelled")
        never = get_job_by_id(db_conn, "sub-src", "sub-never")
        empty = get_job_by_id(db_conn, "sub-src", "sub-empty")

        assert labelled is not None and never is not None and empty is not None
        assert labelled["subcategories"] == ["backend", "ai_engineering"]
        assert never["subcategories"] is None
        assert empty["subcategories"] == []
        # And the raw column name must not leak alongside the alias.
        assert "enrichment_subcategories" not in labelled

    def test_order_is_preserved_index_zero_is_primary(self, db_conn):
        _insert_job(
            db_conn,
            _make_job(
                {
                    "id": "sub-order",
                    "source_id": "sub-src2",
                    "enrichment_subcategories": ["infrastructure_platform", "backend"],
                }
            ),
        )
        db_conn.commit()
        row = get_job_by_id(db_conn, "sub-src2", "sub-order")
        assert row is not None
        assert row["subcategories"] == ["infrastructure_platform", "backend"]
