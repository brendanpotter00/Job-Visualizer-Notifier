"""Tests for database service layer (services/database.py)."""

import json

from api.services.database import _build_where, _ensure_json_string


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
