"""Unit tests for feedback_service.py."""

from datetime import datetime, timedelta, timezone

from psycopg2 import sql

from api.services.feedback_service import list_feedback, submit_feedback

from .conftest import _insert_user, _make_user


def _seed_user(db_conn, overrides=None):
    user = _make_user(overrides)
    _insert_user(db_conn, user)
    return user["id"]


def _insert_feedback_row(
    db_conn, fid, message="m", created_at=None, user_id=None,
    user_email=None, display_name=None,
):
    cur = db_conn.cursor()
    if created_at is None:
        cur.execute(
            sql.SQL(
                "INSERT INTO {} (id, message, user_id, user_email, display_name)"
                " VALUES (%s, %s, %s, %s, %s)"
            ).format(sql.Identifier("feedback")),
            (fid, message, user_id, user_email, display_name),
        )
    else:
        cur.execute(
            sql.SQL(
                "INSERT INTO {} (id, message, user_id, user_email, display_name,"
                " created_at) VALUES (%s, %s, %s, %s, %s, %s)"
            ).format(sql.Identifier("feedback")),
            (fid, message, user_id, user_email, display_name, created_at),
        )
    db_conn.commit()


class TestSubmitFeedback:
    def test_anonymous_insert_has_null_user_fields(self, db_conn):
        row = submit_feedback(
            db_conn, "great app", user_id=None, user_email=None, display_name=None
        )
        assert row["message"] == "great app"
        assert row["user_id"] is None
        assert row["user_email"] is None
        assert row["display_name"] is None
        assert row["id"]  # uuid hex generated
        assert row["created_at"] is not None

    def test_snapshot_insert_persists_values(self, db_conn):
        user_id = _seed_user(db_conn)
        row = submit_feedback(
            db_conn, "thanks", user_id=user_id,
            user_email="test@example.com", display_name="Tester",
        )
        assert row["user_id"] == user_id
        assert row["user_email"] == "test@example.com"
        assert row["display_name"] == "Tester"

    def test_user_delete_nulls_fk_but_keeps_snapshot(self, db_conn):
        """ON DELETE SET NULL: deleting the user nulls user_id but the
        email/display_name snapshot and the row itself survive (audit-correct)."""
        user_id = _seed_user(db_conn)
        row = submit_feedback(
            db_conn, "keep me", user_id=user_id,
            user_email="test@example.com", display_name="Tester",
        )
        cur = db_conn.cursor()
        cur.execute(
            sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier("users")),
            (user_id,),
        )
        db_conn.commit()
        cur.execute(
            sql.SQL(
                "SELECT user_id, user_email, display_name, message FROM {}"
                " WHERE id = %s"
            ).format(sql.Identifier("feedback")),
            (row["id"],),
        )
        after = cur.fetchone()
        assert after is not None, "feedback row must survive user deletion"
        assert after["user_id"] is None
        assert after["user_email"] == "test@example.com"
        assert after["display_name"] == "Tester"
        assert after["message"] == "keep me"


class TestListFeedback:
    def test_empty_state_returns_empty_list(self, db_conn):
        assert list_feedback(db_conn, limit=50, offset=0) == []

    def test_ordering_newest_first(self, db_conn):
        base = datetime(2026, 6, 1, tzinfo=timezone.utc)
        _insert_feedback_row(db_conn, "a", "oldest", created_at=base)
        _insert_feedback_row(db_conn, "b", "middle", created_at=base + timedelta(hours=1))
        _insert_feedback_row(db_conn, "c", "newest", created_at=base + timedelta(hours=2))
        rows = list_feedback(db_conn, limit=50, offset=0)
        assert [r["message"] for r in rows] == ["newest", "middle", "oldest"]

    def test_pagination_limit_and_offset(self, db_conn):
        base = datetime(2026, 6, 1, tzinfo=timezone.utc)
        for i in range(5):
            _insert_feedback_row(
                db_conn, f"id{i}", f"m{i}", created_at=base + timedelta(hours=i)
            )
        # Newest-first: m4, m3, m2, m1, m0
        page1 = list_feedback(db_conn, limit=2, offset=0)
        page2 = list_feedback(db_conn, limit=2, offset=2)
        assert [r["message"] for r in page1] == ["m4", "m3"]
        assert [r["message"] for r in page2] == ["m2", "m1"]
