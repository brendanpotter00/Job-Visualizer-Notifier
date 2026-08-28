"""Tests for the two admin Custom Companies endpoints (E7 oversight page).

Each test here maps to a claim the page makes, and most of them guard a
specific way the SQL can go quietly wrong:

* an attempt is a COLLAPSE of several ``company_add_attempts`` rows, keyed on
  ``COALESCE(company_id, 'attempt#'||id)`` — a bare ``DISTINCT ON (company_id)``
  would fold every NULL-company_id row into one phantom attempt;
* filters run AFTER the collapse, so a superseded ``refused`` row never
  resurfaces;
* ``live_status`` is derived ONCE in SQL, so the tile and the chips agree;
* production runs a pre-E7 schema, and both endpoints must degrade to
  ``schemaPresent: false`` there rather than 500.

Uses conftest's module-scoped ``test_app`` / ``client`` / ``db_conn``
(``require_admin`` is already overridden) and its autouse ``clean_tables``,
which already truncates all four E7 tables. Seed helpers are local — there is
no shared custom-company seeder.
"""

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2.extras import RealDictCursor

from .conftest import TEST_DB_URL, _insert_user, _make_user

COMPANIES_PATH = "/api/admin/custom-companies"
ATTEMPTS_PATH = "/api/admin/custom-companies/attempts"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed_user(db_conn, user_id="user-1", email=None, display_name=None) -> str:
    _insert_user(
        db_conn,
        _make_user(
            {
                "id": user_id,
                "auth0_id": f"auth0|{user_id}",
                "email": email or f"{user_id}@example.com",
                "display_name": display_name,
            }
        ),
    )
    return user_id


def _seed_company(
    db_conn,
    company_id,
    *,
    display_name=None,
    visibility="user",
    enabled=True,
    health_state="unverified",
    cadence_hours=24,
    provider_config=None,
    created_at="2026-08-01T00:00:00Z",
    ats="discovered",
    board_token="https://example.com/jobs",
) -> str:
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO companies (id, display_name, ats, board_token, enabled, "
        "provider_config, created_at, visibility, cadence_hours, health_state, "
        "consecutive_failures) "
        "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, 0)",
        (
            company_id,
            display_name or company_id,
            ats,
            board_token,
            enabled,
            json.dumps(provider_config if provider_config is not None else {}),
            created_at,
            visibility,
            cadence_hours,
            health_state,
        ),
    )
    db_conn.commit()
    return company_id


def _seed_harvest(
    db_conn,
    company_id,
    *,
    started_at=None,
    verdict="VERIFIED",
    records=10,
    cap_hit=False,
):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO company_harvests (company_id, run_id, started_at, completed_at, "
        "verdict, records_harvested, oracle_kind, cap_hit) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'declared_total', %s)",
        (
            company_id,
            f"run-{uuid.uuid4().hex[:8]}",
            started_at or _now(),
            started_at or _now(),
            verdict,
            records,
            cap_hit,
        ),
    )
    db_conn.commit()


def _seed_link(db_conn, user_id, company_id):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO user_companies (user_id, company_id, canonical_source_key) "
        "VALUES (%s, %s, %s)",
        (user_id, company_id, f"key:{company_id}"),
    )
    db_conn.commit()


def _seed_script(db_conn, company_id, *, transport="http_json", version=1):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO company_scripts (company_id, script, script_version, transport, "
        "oracle_kind) VALUES (%s, '{}'::jsonb, %s, %s, 'declared_total')",
        (company_id, version, transport),
    )
    db_conn.commit()


def _seed_attempt(
    db_conn,
    *,
    user_id,
    outcome,
    submitted_url="https://example.com/careers",
    normalized_url=None,
    company_id=None,
    created_at=None,
    error_detail=None,
    resolved_ats="discovered",
    board_token=None,
) -> int:
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO company_add_attempts (user_id, submitted_url, normalized_url, "
        "outcome, error_detail, resolved_ats, board_token, company_id, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            user_id,
            submitted_url,
            normalized_url,
            outcome,
            error_detail,
            resolved_ats,
            board_token,
            company_id,
            created_at or _now(),
        ),
    )
    row = cur.fetchone()
    db_conn.commit()
    return int(row["id"])


def _get(client, path, **params):
    resp = client.get(path, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestAdminCustomCompaniesGate:
    def test_non_admin_gets_403(self, test_app, db_conn):
        from api.auth.dependencies import require_admin

        saved = test_app.dependency_overrides.pop(require_admin, None)
        try:
            anon = TestClient(test_app)
            for path in (COMPANIES_PATH, ATTEMPTS_PATH):
                assert anon.get(path).status_code in (401, 403), path
        finally:
            if saved is not None:
                test_app.dependency_overrides[require_admin] = saved


class TestAttemptCollapse:
    def test_two_audit_rows_collapse_to_one_attempt(self, client, db_conn):
        """The request path writes discovery_pending, the worker writes the
        terminal row. One submission, one row on the page."""
        user = _seed_user(db_conn)
        start = _now() - timedelta(minutes=5)
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="discovery_pending",
            company_id="u-abc",
            created_at=start,
        )
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="added",
            company_id="u-abc",
            created_at=start + timedelta(seconds=30),
        )

        data = _get(client, ATTEMPTS_PATH)
        assert data["total"] == 1
        row = data["attempts"][0]
        assert row["auditRowCount"] == 2
        assert row["outcome"] == "added"
        assert row["rawOutcome"] == "added"
        assert row["attemptKey"] == "u-abc"
        assert row["decidedInS"] == 30

    def test_null_company_id_rows_do_not_collapse(self, client, db_conn):
        """unsupported/empty/probe_failed write no company_id. A bare
        DISTINCT ON (company_id) would fold them into a single phantom row."""
        user = _seed_user(db_conn)
        _seed_attempt(db_conn, user_id=user, outcome="unsupported", company_id=None)
        _seed_attempt(db_conn, user_id=user, outcome="unsupported", company_id=None)

        data = _get(client, ATTEMPTS_PATH)
        assert data["total"] == 2
        keys = {r["attemptKey"] for r in data["attempts"]}
        assert len(keys) == 2
        assert all(k.startswith("attempt#") for k in keys)
        assert data["byOutcome"]["unsupported"] == 2

    def test_decided_in_s_only_for_immediately_preceding_pending(
        self, client, db_conn
    ):
        """An idempotent re-add is NOT "N days to decide". decided_in_s is null
        unless the row immediately before the terminal one was the pending."""
        user = _seed_user(db_conn)
        base = _now() - timedelta(days=3)
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="discovery_pending",
            company_id="u-abc",
            created_at=base,
        )
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="added",
            company_id="u-abc",
            created_at=base + timedelta(seconds=20),
        )
        # Days later the user pastes the same URL again — idempotent re-add.
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="added",
            company_id="u-abc",
            created_at=_now(),
        )

        data = _get(client, ATTEMPTS_PATH)
        assert data["total"] == 1
        assert data["attempts"][0]["decidedInS"] is None
        assert data["attempts"][0]["auditRowCount"] == 3


class TestDerivedOutcome:
    def test_pending_newer_than_grace_is_pending_not_stuck(self, client, db_conn):
        user = _seed_user(db_conn)
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="discovery_pending",
            company_id="u-fresh",
            created_at=_now(),
        )
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="discovery_pending",
            company_id="u-old",
            created_at=_now() - timedelta(minutes=41),
        )

        data = _get(client, ATTEMPTS_PATH)
        by_key = {r["attemptKey"]: r for r in data["attempts"]}
        assert by_key["u-fresh"]["outcome"] == "pending"
        assert by_key["u-old"]["outcome"] == "stuck"
        # The raw column value is preserved for diagnosis either way.
        assert by_key["u-fresh"]["rawOutcome"] == "discovery_pending"
        assert by_key["u-old"]["rawOutcome"] == "discovery_pending"
        assert data["byOutcome"]["pending"] == 1
        assert data["byOutcome"]["stuck"] == 1

    def test_error_detail_split_keeps_colons_in_the_reason(self, client, db_conn):
        """split_part(x, ': ', 2) would truncate at the SECOND ': ' — and real
        reasons contain colons."""
        user = _seed_user(db_conn)
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="refused",
            company_id="u-abc",
            error_detail="finding the jobs feed: a: b",
        )
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="refused",
            company_id="u-def",
            error_detail="no separator here",
        )

        rows = {r["attemptKey"]: r for r in _get(client, ATTEMPTS_PATH)["attempts"]}
        assert rows["u-abc"]["failedStep"] == "finding the jobs feed"
        assert rows["u-abc"]["failureReason"] == "a: b"
        # No ": " at all: the whole string is still worth showing as the reason.
        assert rows["u-def"]["failedStep"] is None
        assert rows["u-def"]["failureReason"] == "no separator here"


class TestCompanySideJoins:
    def test_deleted_company_degrades(self, client, db_conn):
        """Deleting a custom company HARD-deletes the companies row; most
        historical attempts point at an id that is gone. LEFT JOIN or the audit
        log silently loses them."""
        user = _seed_user(db_conn)
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="added",
            company_id="u-gone",
            submitted_url="https://deleted.example.com/careers",
        )

        data = _get(client, ATTEMPTS_PATH)
        row = data["attempts"][0]
        assert row["companyId"] == "u-gone"
        assert row["companyExists"] is False
        assert row["companyDisplayName"] is None
        assert row["companyLiveStatus"] is None
        assert row["discoverySteps"] is None
        assert row["submittedUrl"] == "https://deleted.example.com/careers"

    def test_already_public_points_at_public_company(self, client, db_conn):
        user = _seed_user(db_conn)
        _seed_company(db_conn, "amazon", visibility="public", health_state=None)
        _seed_attempt(
            db_conn, user_id=user, outcome="already_public", company_id="amazon"
        )

        row = _get(client, ATTEMPTS_PATH)["attempts"][0]
        assert row["outcome"] == "already_public"
        assert row["companyExists"] is True
        assert row["companyVisibility"] == "public"
        # live_status is only meaningful for user-visibility boards.
        assert row["companyLiveStatus"] is None
        # A public company is not a tracked custom company.
        assert _get(client, COMPANIES_PATH)["total"] == 0

    def test_network_blob_never_serialized(self, client, db_conn):
        """provider_config->'discovery'->'network' is the full request log plus
        a payload sample. Only ->'steps' may ride a 25-row page."""
        marker = "NETWORK_BLOB_MARKER_" + "x" * 200_000
        user = _seed_user(db_conn)
        _seed_company(
            db_conn,
            "u-abc",
            provider_config={
                "discovery": {
                    "steps": [
                        {"key": "open_page", "status": "done", "result": "opened"},
                        {"key": "find_feed", "status": "failed", "result": "no feed"},
                    ],
                    "network": {"requests": [marker]},
                }
            },
        )
        _seed_attempt(db_conn, user_id=user, outcome="added", company_id="u-abc")

        resp = client.get(ATTEMPTS_PATH)
        assert resp.status_code == 200
        assert "NETWORK_BLOB_MARKER" not in resp.text
        steps = resp.json()["attempts"][0]["discoverySteps"]
        assert [s["key"] for s in steps] == ["open_page", "find_feed"]
        assert steps[1]["status"] == "failed"


class TestLiveStatus:
    def _seed_matrix(self, db_conn):
        user = _seed_user(db_conn)
        now = _now()

        _seed_company(db_conn, "u-live")
        _seed_link(db_conn, user, "u-live")
        _seed_harvest(db_conn, "u-live", started_at=now - timedelta(hours=1))

        # No user_companies row at all — a data-integrity problem regardless of
        # whether it harvests, so orphan outranks every other branch.
        _seed_company(db_conn, "u-orphan")
        _seed_harvest(db_conn, "u-orphan", started_at=now - timedelta(hours=1))

        _seed_company(db_conn, "u-never")
        _seed_link(db_conn, user, "u-never")

        _seed_company(db_conn, "u-failed-verdict")
        _seed_link(db_conn, user, "u-failed-verdict")
        _seed_harvest(
            db_conn,
            "u-failed-verdict",
            started_at=now - timedelta(hours=1),
            verdict="FAILED",
        )

        _seed_company(db_conn, "u-zero-records")
        _seed_link(db_conn, user, "u-zero-records")
        _seed_harvest(
            db_conn, "u-zero-records", started_at=now - timedelta(hours=1), records=0
        )

        _seed_company(db_conn, "u-disabled", enabled=False, health_state="refused")
        _seed_link(db_conn, user, "u-disabled")
        _seed_harvest(db_conn, "u-disabled", started_at=now - timedelta(hours=1))

        # Older than 2 x cadence_hours.
        _seed_company(db_conn, "u-stale", cadence_hours=24)
        _seed_link(db_conn, user, "u-stale")
        _seed_harvest(db_conn, "u-stale", started_at=now - timedelta(hours=51))
        return user

    def test_live_status_matrix(self, client, db_conn):
        self._seed_matrix(db_conn)
        rows = {r["id"]: r for r in _get(client, COMPANIES_PATH, limit=200)["companies"]}

        assert rows["u-live"]["liveStatus"] == "live"
        assert rows["u-orphan"]["liveStatus"] == "orphan"
        assert rows["u-never"]["liveStatus"] == "never_harvested"
        assert rows["u-failed-verdict"]["liveStatus"] == "failing"
        assert rows["u-zero-records"]["liveStatus"] == "failing"
        assert rows["u-disabled"]["liveStatus"] == "failing"
        assert rows["u-stale"]["liveStatus"] == "stale"

        # liveReason is null IFF live — an unexplained non-live chip is a dead end.
        for row in rows.values():
            assert (row["liveReason"] is None) == (row["liveStatus"] == "live"), row["id"]

        assert rows["u-orphan"]["liveReason"] == "no owner row"
        assert rows["u-never"]["liveReason"] == "never harvested"
        assert rows["u-disabled"]["liveReason"] == "disabled"
        assert rows["u-failed-verdict"]["liveReason"] == "last harvest FAILED"
        assert rows["u-zero-records"]["liveReason"] == "harvested 0 records"
        assert "cadence 24 h" in rows["u-stale"]["liveReason"]

    def test_summary_matches_rows(self, client, db_conn):
        """The tile and the chips are derived from the same SQL CASE. Paging
        through every row must reproduce summary.liveCount exactly."""
        self._seed_matrix(db_conn)

        summary = _get(client, COMPANIES_PATH, limit=1)["summary"]
        seen = []
        offset = 0
        while True:
            page = _get(client, COMPANIES_PATH, limit=2, offset=offset)
            seen.extend(page["companies"])
            offset += 2
            if offset >= page["total"]:
                break

        assert len(seen) == summary["trackedCount"] == 7
        assert sum(1 for r in seen if r["liveStatus"] == "live") == summary["liveCount"]
        assert summary["liveCount"] == 1
        assert summary["byLiveStatus"] == {
            "live": 1,
            "orphan": 1,
            "never_harvested": 1,
            "failing": 3,
            "stale": 1,
        }
        assert summary["byHealthState"] == {"unverified": 6, "refused": 1}

    def test_owner_and_script_columns(self, client, db_conn):
        user = _seed_user(db_conn, email="owner@example.com", display_name="Owner")
        second = _seed_user(db_conn, user_id="user-2", email="second@example.com")
        _seed_company(db_conn, "u-abc", display_name="Atlassian")
        _seed_link(db_conn, user, "u-abc")
        _seed_link(db_conn, second, "u-abc")
        _seed_script(db_conn, "u-abc", transport="browser_fetch", version=3)
        _seed_harvest(db_conn, "u-abc", records=232, cap_hit=True)

        row = _get(client, COMPANIES_PATH)["companies"][0]
        assert row["displayName"] == "Atlassian"
        assert row["ownerEmail"] == "owner@example.com"
        assert row["ownerDisplayName"] == "Owner"
        assert row["ownerCount"] == 2  # shared board
        assert row["transport"] == "browser_fetch"
        assert row["scriptVersion"] == 3
        assert row["recordsHarvested"] == 232
        assert row["capHit"] is True
        assert row["lastHarvestAgeS"] is not None and row["lastHarvestAgeS"] >= 0


class TestFiltersAndPagination:
    def test_pagination_and_total(self, client, db_conn):
        user = _seed_user(db_conn)
        base = _now() - timedelta(hours=1)
        for i in range(3):
            _seed_attempt(
                db_conn,
                user_id=user,
                outcome="added",
                company_id=f"u-{i}",
                created_at=base + timedelta(minutes=i),
            )

        first = _get(client, ATTEMPTS_PATH, limit=2, offset=0)
        assert first["total"] == 3
        assert len(first["attempts"]) == 2
        second = _get(client, ATTEMPTS_PATH, limit=2, offset=2)
        assert second["total"] == 3
        assert len(second["attempts"]) == 1
        # Fixed order is newest-first, and the pages must not overlap.
        ids = [r["id"] for r in first["attempts"]] + [r["id"] for r in second["attempts"]]
        assert ids == sorted(ids, reverse=True)

    def test_filters_apply_after_collapse(self, client, db_conn):
        """A refused row that a later retry superseded must NOT match
        outcome=refused — filtering before the collapse would surface it."""
        user = _seed_user(db_conn)
        base = _now() - timedelta(hours=2)
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="refused",
            company_id="u-retried",
            created_at=base,
        )
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="added",
            company_id="u-retried",
            created_at=base + timedelta(minutes=1),
        )
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="refused",
            company_id="u-still-refused",
            created_at=base + timedelta(minutes=2),
        )

        data = _get(client, ATTEMPTS_PATH, outcome="refused")
        assert data["total"] == 1
        assert data["attempts"][0]["attemptKey"] == "u-still-refused"

    def test_search_and_unknown_filter_values(self, client, db_conn):
        user = _seed_user(db_conn)
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="added",
            company_id="u-a",
            submitted_url="https://jobs.uber.com/en/jobs/",
        )
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="added",
            company_id="u-b",
            submitted_url="https://www.metacareers.com/positions",
        )

        assert _get(client, ATTEMPTS_PATH, search="UBER")["total"] == 1
        assert _get(client, ATTEMPTS_PATH, search="careers")["total"] == 1
        # An unknown filter value is not a 422 — it matches nothing.
        assert _get(client, ATTEMPTS_PATH, outcome="not_a_real_outcome")["total"] == 0
        # A blank param means "no filter", not "match the empty string".
        assert _get(client, ATTEMPTS_PATH, search="")["total"] == 2

    def test_companies_filters(self, client, db_conn):
        user = _seed_user(db_conn, email="owner@example.com")
        _seed_company(db_conn, "u-abc", display_name="Atlassian", health_state="healthy")
        _seed_link(db_conn, user, "u-abc")
        _seed_company(db_conn, "u-def", display_name="Sequoia", health_state="refused")

        assert _get(client, COMPANIES_PATH, health="healthy")["total"] == 1
        assert _get(client, COMPANIES_PATH, health="nope")["total"] == 0
        assert _get(client, COMPANIES_PATH, search="atlas")["total"] == 1
        assert _get(client, COMPANIES_PATH, search="u-def")["total"] == 1
        # Search spans the owner email too.
        assert _get(client, COMPANIES_PATH, search="owner@example")["total"] == 1
        # Summary is never narrowed by the filters.
        assert _get(client, COMPANIES_PATH, health="healthy")["summary"][
            "trackedCount"
        ] == 2

    @pytest.mark.parametrize("path", [COMPANIES_PATH, ATTEMPTS_PATH])
    def test_limit_is_capped_at_200(self, client, path):
        assert client.get(path, params={"limit": 201}).status_code == 422
        assert client.get(path, params={"limit": 0}).status_code == 422
        assert client.get(path, params={"offset": -1}).status_code == 422


class TestUserRollup:
    def test_rollup_is_unfiltered(self, client, db_conn):
        """The rollup also feeds the User dropdown, so narrowing it by the
        current selection would erase every other option."""
        user = _seed_user(db_conn)
        other = _seed_user(db_conn, user_id="user-2", email="two@example.com")
        _seed_attempt(db_conn, user_id=user, outcome="added", company_id="u-a")
        _seed_attempt(db_conn, user_id=user, outcome="refused", company_id="u-b")
        _seed_attempt(db_conn, user_id=other, outcome="added", company_id="u-c")

        filtered = _get(client, ATTEMPTS_PATH, outcome="refused", user_id=user)
        assert filtered["total"] == 1
        assert filtered["byOutcome"] == {
            "added": 2,
            "already_public": 0,
            "refused": 1,
            "unsupported": 0,
            "empty": 0,
            "probe_failed": 0,
            "pending": 0,
            "stuck": 0,
        }
        by_user = {u["userId"]: u for u in filtered["users"]}
        assert set(by_user) == {user, other}
        assert by_user[user]["attempts"] == 2
        assert by_user[user]["added"] == 1
        assert by_user[user]["refused"] == 1
        assert by_user[other]["attempts"] == 1
        assert filtered["usersTruncated"] is False

    def test_owns_now_differs_from_added(self, client, db_conn):
        """Deleting a custom company hard-deletes the companies row, so a user
        can have added more boards than they own today."""
        user = _seed_user(db_conn)
        for cid in ("u-a", "u-b"):
            _seed_company(db_conn, cid)
            _seed_link(db_conn, user, cid)
            _seed_attempt(db_conn, user_id=user, outcome="added", company_id=cid)
        cur = db_conn.cursor()
        cur.execute("DELETE FROM companies WHERE id = 'u-b'")
        db_conn.commit()

        rollup = _get(client, ATTEMPTS_PATH)["users"][0]
        assert rollup["added"] == 2
        assert rollup["ownsNow"] == 1

    def test_rollup_spans_all_audit_rows(self, client, db_conn):
        """first_attempt_at is over ALL audit rows, so it is the real first
        submit — not the timestamp of the terminal row that superseded it."""
        user = _seed_user(db_conn)
        first = _now() - timedelta(days=4)
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="discovery_pending",
            company_id="u-a",
            created_at=first,
        )
        _seed_attempt(
            db_conn,
            user_id=user,
            outcome="added",
            company_id="u-a",
            created_at=_now(),
        )

        rollup = _get(client, ATTEMPTS_PATH)["users"][0]
        assert rollup["firstAttemptAt"].startswith(first.strftime("%Y-%m-%dT%H:%M"))

    def test_soft_linked_user_without_users_row(self, client, db_conn):
        """company_add_attempts.user_id has NO foreign key. A deleted user must
        leave the audit row visible with a null email, never drop it."""
        _seed_attempt(db_conn, user_id="ghost-user", outcome="added", company_id="u-a")

        data = _get(client, ATTEMPTS_PATH)
        assert data["total"] == 1
        assert data["attempts"][0]["userId"] == "ghost-user"
        assert data["attempts"][0]["userEmail"] is None
        assert data["users"][0]["userId"] == "ghost-user"
        assert data["users"][0]["email"] is None


class TestEmptyAndPreE7Schema:
    def test_empty_database_returns_zeroed_envelope(self, client):
        companies = _get(client, COMPANIES_PATH)
        assert companies["schemaPresent"] is True
        assert companies["total"] == 0
        assert companies["summary"]["trackedCount"] == 0
        assert companies["summary"]["attemptCount"] == 0

        attempts = _get(client, ATTEMPTS_PATH)
        assert attempts["total"] == 0
        assert attempts["users"] == []
        # Deterministic keys even at zero rows.
        assert set(attempts["byOutcome"]) == {
            "added",
            "already_public",
            "refused",
            "unsupported",
            "empty",
            "probe_failed",
            "pending",
            "stuck",
        }
        assert set(attempts["byOutcome"].values()) == {0}

    def test_schema_absent_returns_empty_not_500(self, client, monkeypatch):
        """Production has none of the E7 tables. The endpoints must degrade,
        not 500."""
        monkeypatch.setattr(
            "api.services.custom_companies_admin._schema_present", lambda cur: False
        )
        companies = _get(client, COMPANIES_PATH)
        assert companies["schemaPresent"] is False
        assert companies["companies"] == []
        assert companies["total"] == 0
        assert companies["summary"] == {
            "trackedCount": 0,
            "liveCount": 0,
            "byLiveStatus": {},
            "byHealthState": {},
            "attemptCount": 0,
            "userCount": 0,
            "failedCount": 0,
            "refusedCount": 0,
            "stuckCount": 0,
        }

        attempts = _get(client, ATTEMPTS_PATH)
        assert attempts["schemaPresent"] is False
        assert attempts["attempts"] == []
        assert attempts["total"] == 0
        assert attempts["byOutcome"] == {}
        assert attempts["users"] == []
        assert attempts["usersTruncated"] is False

    def test_pre_e7_companies_table_fails_the_guard(self):
        """The real production shape: the E7 tables exist in name only and
        `companies` predates visibility/health_state/cadence_hours. The
        to_regclass probe alone would pass here — the pg_attribute column count
        is what catches it, and both services must return the zeroed envelope
        rather than raising UndefinedColumn.
        """
        from api.services.custom_companies_admin import (
            _schema_present,
            list_add_attempts,
            list_custom_companies,
        )

        schema = "test_pre_e7_" + secrets.token_hex(4)
        conn = psycopg2.connect(TEST_DB_URL, cursor_factory=RealDictCursor)
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA "{schema}"')
                cur.execute(f'SET search_path TO "{schema}"')
                # Pre-E7 companies: no visibility / health_state / cadence_hours.
                cur.execute(
                    "CREATE TABLE companies (id text PRIMARY KEY, display_name text, "
                    "ats text, board_token text, enabled boolean, provider_config jsonb)"
                )
                cur.execute("CREATE TABLE users (id text PRIMARY KEY, email text)")
                for name in (
                    "user_companies",
                    "company_add_attempts",
                    "company_harvests",
                    "company_scripts",
                ):
                    cur.execute(f"CREATE TABLE {name} (company_id text)")
                assert _schema_present(cur) is False
            conn.autocommit = False

            companies = list_custom_companies(conn)
            assert companies["schema_present"] is False
            assert companies["companies"] == []
            attempts = list_add_attempts(conn)
            assert attempts["schema_present"] is False
            assert attempts["attempts"] == []
        finally:
            conn.close()
            drop = psycopg2.connect(TEST_DB_URL)
            drop.autocommit = True
            try:
                with drop.cursor() as cur:
                    cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            finally:
                drop.close()
