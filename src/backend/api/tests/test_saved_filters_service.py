"""Unit tests for saved_filters_service.py.

Covers the security/correctness invariants flagged as untested in the PR review:
ownership scoping, active-pointer validation, the built-in read-only guard,
case-insensitive duplicate-name detection (incl. the reserved built-in name),
the per-user list cap, UniqueViolation -> DuplicateListName remap, and the
delete-NULLs-active-pointer transaction.

Follows the test_user_preferences_service.py pattern: real ``db_conn`` fixture
(per-worker schema), psycopg2 ``RealDictCursor`` rows.
"""

import psycopg2
import pytest
from psycopg2 import sql

from api.services.saved_filters_service import (
    BUILTIN_SWE_LIST_ID,
    BUILTIN_SWE_LIST_NAME,
    MAX_KEYWORD_LISTS_PER_USER,
    BuiltinListReadOnly,
    DuplicateListName,
    KeywordListLimitReached,
    KeywordListNotFound,
    UnknownActiveList,
    create_keyword_list,
    default_saved_filters,
    delete_keyword_list,
    get_saved_filters,
    list_keyword_lists,
    update_keyword_list,
    upsert_saved_filters,
)

from .conftest import _insert_user, _make_user


def _seed_user(db_conn, overrides=None) -> str:
    user = _make_user(overrides)
    _insert_user(db_conn, user)
    return user["id"]


def _two_users(db_conn) -> tuple[str, str]:
    a = _seed_user(db_conn, {"email": "a@example.com", "auth0_id": "auth0|a"})
    b = _seed_user(db_conn, {"email": "b@example.com", "auth0_id": "auth0|b"})
    return a, b


def _upsert_defaults(db_conn, user_id, **overrides):
    """Upsert with sensible defaults, overriding individual fields."""
    base = {
        "recent_time_window": "3h",
        "trend_time_window": "7d",
        "locations": [],
        "recent_active_keyword_list_id": None,
        "trend_active_keyword_list_id": None,
    }
    base.update(overrides)
    return upsert_saved_filters(db_conn, user_id, **base)


# --- Scalar saved filters -----------------------------------------------------


class TestGetSavedFilters:
    def test_returns_defaults_when_no_row(self, db_conn):
        user_id = _seed_user(db_conn)
        assert get_saved_filters(db_conn, user_id) == default_saved_filters()

    def test_round_trips_an_upsert(self, db_conn):
        user_id = _seed_user(db_conn)
        _upsert_defaults(
            db_conn,
            user_id,
            recent_time_window="24h",
            trend_time_window="30d",
            locations=["San Francisco, CA, US"],
        )
        got = get_saved_filters(db_conn, user_id)
        assert got["recent_time_window"] == "24h"
        assert got["trend_time_window"] == "30d"
        assert got["locations"] == ["San Francisco, CA, US"]

    def test_isolates_users(self, db_conn):
        a, b = _two_users(db_conn)
        _upsert_defaults(db_conn, a, recent_time_window="24h")
        # b has no row -> defaults, never a's data.
        assert get_saved_filters(db_conn, b) == default_saved_filters()
        assert get_saved_filters(db_conn, a)["recent_time_window"] == "24h"


class TestActivePointerValidation:
    def test_builtin_pointer_is_always_valid(self, db_conn):
        user_id = _seed_user(db_conn)
        row = _upsert_defaults(
            db_conn,
            user_id,
            recent_active_keyword_list_id=BUILTIN_SWE_LIST_ID,
            trend_active_keyword_list_id=BUILTIN_SWE_LIST_ID,
        )
        assert row["recent_active_keyword_list_id"] == BUILTIN_SWE_LIST_ID

    def test_owned_pointer_is_valid(self, db_conn):
        user_id = _seed_user(db_conn)
        lst = create_keyword_list(db_conn, user_id, name="Backend", tags=[])
        row = _upsert_defaults(
            db_conn, user_id, trend_active_keyword_list_id=lst["id"]
        )
        assert row["trend_active_keyword_list_id"] == lst["id"]

    def test_unknown_pointer_raises(self, db_conn):
        user_id = _seed_user(db_conn)
        with pytest.raises(UnknownActiveList):
            _upsert_defaults(
                db_conn, user_id, trend_active_keyword_list_id="does-not-exist"
            )

    def test_unowned_pointer_raises(self, db_conn):
        a, b = _two_users(db_conn)
        a_list = create_keyword_list(db_conn, a, name="A list", tags=[])
        # b cannot point at a's list.
        with pytest.raises(UnknownActiveList):
            _upsert_defaults(
                db_conn, b, trend_active_keyword_list_id=a_list["id"]
            )

    def test_rejected_upsert_does_not_persist(self, db_conn):
        user_id = _seed_user(db_conn)
        with pytest.raises(UnknownActiveList):
            _upsert_defaults(
                db_conn, user_id, recent_active_keyword_list_id="nope"
            )
        # The failed upsert rolled back -> still defaults (no partial row).
        assert get_saved_filters(db_conn, user_id) == default_saved_filters()


# --- Keyword lists ------------------------------------------------------------


class TestListKeywordLists:
    def test_builtin_is_appended_last(self, db_conn):
        user_id = _seed_user(db_conn)
        create_keyword_list(db_conn, user_id, name="Backend", tags=[])
        lists = list_keyword_lists(db_conn, user_id)
        assert lists[-1]["id"] == BUILTIN_SWE_LIST_ID
        assert lists[-1]["is_builtin"] is True
        assert lists[0]["name"] == "Backend"
        assert lists[0]["is_builtin"] is False

    def test_only_builtin_for_user_with_no_lists(self, db_conn):
        user_id = _seed_user(db_conn)
        lists = list_keyword_lists(db_conn, user_id)
        assert [l["id"] for l in lists] == [BUILTIN_SWE_LIST_ID]

    def test_isolates_users(self, db_conn):
        a, b = _two_users(db_conn)
        create_keyword_list(db_conn, a, name="A list", tags=[])
        # b sees only the built-in, never a's list.
        assert [l["id"] for l in list_keyword_lists(db_conn, b)] == [
            BUILTIN_SWE_LIST_ID
        ]


class TestCreateKeywordList:
    def test_creates_with_position_appended(self, db_conn):
        user_id = _seed_user(db_conn)
        first = create_keyword_list(db_conn, user_id, name="One", tags=[])
        second = create_keyword_list(db_conn, user_id, name="Two", tags=[])
        assert first["position"] == 0
        assert second["position"] == 1

    def test_duplicate_name_case_insensitive_raises(self, db_conn):
        user_id = _seed_user(db_conn)
        create_keyword_list(db_conn, user_id, name="Backend", tags=[])
        with pytest.raises(DuplicateListName):
            create_keyword_list(db_conn, user_id, name="backend", tags=[])

    def test_reserved_builtin_name_raises(self, db_conn):
        user_id = _seed_user(db_conn)
        with pytest.raises(DuplicateListName):
            create_keyword_list(
                db_conn, user_id, name=BUILTIN_SWE_LIST_NAME, tags=[]
            )

    def test_reserved_builtin_name_is_case_insensitive(self, db_conn):
        user_id = _seed_user(db_conn)
        with pytest.raises(DuplicateListName):
            create_keyword_list(
                db_conn, user_id, name="software engineering", tags=[]
            )

    def test_same_name_allowed_for_different_users(self, db_conn):
        a, b = _two_users(db_conn)
        create_keyword_list(db_conn, a, name="Backend", tags=[])
        # Same name, different owner -> allowed (scoping is per-user).
        created = create_keyword_list(db_conn, b, name="Backend", tags=[])
        assert created["name"] == "Backend"

    def test_cap_enforced(self, db_conn):
        user_id = _seed_user(db_conn)
        for i in range(MAX_KEYWORD_LISTS_PER_USER):
            create_keyword_list(db_conn, user_id, name=f"List {i}", tags=[])
        with pytest.raises(KeywordListLimitReached):
            create_keyword_list(db_conn, user_id, name="One too many", tags=[])

    def test_unique_violation_remaps_to_duplicate(self, db_conn, monkeypatch):
        """If the case-insensitive pre-check is bypassed (e.g. a concurrent
        insert), the uq_user_keyword_lists_user_name index backstops it and the
        UniqueViolation is re-mapped to DuplicateListName (not a raw 500)."""
        import api.services.saved_filters_service as svc

        user_id = _seed_user(db_conn)
        create_keyword_list(db_conn, user_id, name="Backend", tags=[])
        # Force the pre-check to miss so the DB unique index is what fires.
        monkeypatch.setattr(svc, "_name_taken", lambda *a, **k: False)
        with pytest.raises(DuplicateListName):
            create_keyword_list(db_conn, user_id, name="Backend", tags=[])


class TestUpdateKeywordList:
    def test_builtin_is_read_only(self, db_conn):
        user_id = _seed_user(db_conn)
        with pytest.raises(BuiltinListReadOnly):
            update_keyword_list(
                db_conn, user_id, BUILTIN_SWE_LIST_ID, name="Nope"
            )

    def test_unowned_list_not_found(self, db_conn):
        a, b = _two_users(db_conn)
        a_list = create_keyword_list(db_conn, a, name="A list", tags=[])
        # b cannot patch a's list.
        with pytest.raises(KeywordListNotFound):
            update_keyword_list(db_conn, b, a_list["id"], name="Hijack")

    def test_unknown_list_not_found(self, db_conn):
        user_id = _seed_user(db_conn)
        with pytest.raises(KeywordListNotFound):
            update_keyword_list(db_conn, user_id, "no-such-id", name="X")

    def test_rename_collision_raises(self, db_conn):
        user_id = _seed_user(db_conn)
        create_keyword_list(db_conn, user_id, name="One", tags=[])
        two = create_keyword_list(db_conn, user_id, name="Two", tags=[])
        with pytest.raises(DuplicateListName):
            update_keyword_list(db_conn, user_id, two["id"], name="one")

    def test_rename_to_reserved_builtin_name_raises(self, db_conn):
        user_id = _seed_user(db_conn)
        lst = create_keyword_list(db_conn, user_id, name="Mine", tags=[])
        with pytest.raises(DuplicateListName):
            update_keyword_list(
                db_conn, user_id, lst["id"], name=BUILTIN_SWE_LIST_NAME
            )

    def test_replaces_tags(self, db_conn):
        user_id = _seed_user(db_conn)
        lst = create_keyword_list(
            db_conn, user_id, name="Mine", tags=[{"text": "old", "mode": "include"}]
        )
        updated = update_keyword_list(
            db_conn,
            user_id,
            lst["id"],
            tags=[{"text": "new", "mode": "exclude"}],
        )
        assert updated["tags"] == [{"text": "new", "mode": "exclude"}]

    def test_noop_patch_returns_current_row(self, db_conn):
        user_id = _seed_user(db_conn)
        lst = create_keyword_list(db_conn, user_id, name="Mine", tags=[])
        same = update_keyword_list(db_conn, user_id, lst["id"])
        assert same["id"] == lst["id"]
        assert same["name"] == "Mine"


class TestDeleteKeywordList:
    def test_builtin_is_read_only(self, db_conn):
        user_id = _seed_user(db_conn)
        with pytest.raises(BuiltinListReadOnly):
            delete_keyword_list(db_conn, user_id, BUILTIN_SWE_LIST_ID)

    def test_unowned_list_not_found(self, db_conn):
        a, b = _two_users(db_conn)
        a_list = create_keyword_list(db_conn, a, name="A list", tags=[])
        with pytest.raises(KeywordListNotFound):
            delete_keyword_list(db_conn, b, a_list["id"])

    def test_unknown_list_not_found(self, db_conn):
        user_id = _seed_user(db_conn)
        with pytest.raises(KeywordListNotFound):
            delete_keyword_list(db_conn, user_id, "no-such-id")

    def test_delete_removes_list(self, db_conn):
        user_id = _seed_user(db_conn)
        lst = create_keyword_list(db_conn, user_id, name="Gone", tags=[])
        delete_keyword_list(db_conn, user_id, lst["id"])
        assert [l["id"] for l in list_keyword_lists(db_conn, user_id)] == [
            BUILTIN_SWE_LIST_ID
        ]

    def test_delete_nulls_both_active_pointers(self, db_conn):
        """The list DELETE must NULL any active pointer (recent and/or trend)
        referencing it in the SAME transaction — the pointer is plain TEXT, not
        a FK, so ON DELETE CASCADE does not cover it."""
        user_id = _seed_user(db_conn)
        lst = create_keyword_list(db_conn, user_id, name="Active", tags=[])
        _upsert_defaults(
            db_conn,
            user_id,
            recent_active_keyword_list_id=lst["id"],
            trend_active_keyword_list_id=lst["id"],
        )
        delete_keyword_list(db_conn, user_id, lst["id"])
        prefs = get_saved_filters(db_conn, user_id)
        assert prefs["recent_active_keyword_list_id"] is None
        assert prefs["trend_active_keyword_list_id"] is None

    def test_delete_leaves_unrelated_pointer_intact(self, db_conn):
        user_id = _seed_user(db_conn)
        keep = create_keyword_list(db_conn, user_id, name="Keep", tags=[])
        gone = create_keyword_list(db_conn, user_id, name="Gone", tags=[])
        _upsert_defaults(
            db_conn,
            user_id,
            recent_active_keyword_list_id=keep["id"],
            trend_active_keyword_list_id=gone["id"],
        )
        delete_keyword_list(db_conn, user_id, gone["id"])
        prefs = get_saved_filters(db_conn, user_id)
        # Only the pointer referencing the deleted list is NULLed.
        assert prefs["recent_active_keyword_list_id"] == keep["id"]
        assert prefs["trend_active_keyword_list_id"] is None


class TestDatabaseErrorRollback:
    def test_create_rolls_back_on_db_error(self):
        from unittest.mock import MagicMock

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = psycopg2.OperationalError("conn lost")
        with pytest.raises(psycopg2.OperationalError):
            create_keyword_list(mock_conn, "user-id", name="X", tags=[])
        mock_conn.rollback.assert_called_once()
