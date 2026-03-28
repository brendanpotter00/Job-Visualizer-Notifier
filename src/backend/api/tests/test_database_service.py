"""Tests for database service layer (services/database.py)."""

import json

from api.services.database import _ensure_json_string


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
