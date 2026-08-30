"""AC-25 — renaming a tracked board, and the rename surviving what re-derives names.

The endpoint is ordinary CRUD. What these cases exist for is the rule that makes it
worth having: ``companies.display_name`` is re-derived from the URL by more than one
path, so a rename stored in that column would be silently reverted by an ordinary
re-add. AC-25b and AC-25c are the two halves of that rule; AC-25 and AC-25d are the
CRUD and the boundary.

All four are FAST — one Cisco add each, no harvest wait, no LLM, no live discovery.
AC-25c reaches the re-discovery path by driving the production function the discovery
task calls, against this suite's real database, which is the same hermetic technique
AC-16..AC-24 use (`conftest.py` puts `src/backend` on `sys.path` for exactly this). The
alternative — a genuinely refused board, re-added — costs a browser session and an LLM
call to reach a branch whose whole content is one UPDATE.
"""

from __future__ import annotations

import boards
from conftest import db, find_company, require_reachable

from e2e.shared.auth.mint import PRIMARY_USER

CISCO_URL = boards.CISCO.url

#: What the user types. Deliberately the owner's real example: a Y-Combinator-hosted
#: board belongs to the company on the page, not to YC, and the derived label said YC.
NEW_NAME = "Raindrop"


def _add_cisco(http) -> str:
    """One tracked ATS board owned by the primary user. 201 lands in ~2s — no harvest
    wait, which is what keeps every case in this file out of the `live` set."""
    require_reachable(boards.CISCO)
    resp = http.post("/api/users/companies", json={"url": CISCO_URL})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


class TestRenamePersists:
    """AC-25."""

    def test_ac25_a_renamed_board_keeps_its_new_name(self, http, db_conn):
        company_id = _add_cisco(http)
        derived = db.company_row(db_conn, company_id)["display_name"]

        resp = http.patch(
            f"/api/users/companies/{company_id}", json={"displayName": NEW_NAME}
        )
        assert resp.status_code == 200, (
            f"AC-25: renaming your own board must succeed, got "
            f"{resp.status_code}: {resp.text}"
        )
        assert resp.json()["displayName"] == NEW_NAME
        assert resp.json()["id"] == company_id

        listed = find_company(http, company_id)
        assert listed is not None, "AC-25: the renamed board must still be in the list"
        assert listed["displayName"] == NEW_NAME, (
            "AC-25: the list is what the user actually reads — a rename the list does "
            "not show did not happen"
        )

        row = db.company_row(db_conn, company_id)
        assert row["user_display_name"] == NEW_NAME
        assert row["display_name"] == derived, (
            "AC-25: the DERIVED name must be preserved in its own column — it is what "
            "re-discovery keeps maintaining, and collapsing the two columns is exactly "
            "the change AC-25b and AC-25c exist to catch"
        )

    def test_ac25a_an_invisible_only_name_is_refused_with_a_reason(self, http, db_conn):
        """AC-25a. Whitespace and zero-width characters are non-empty on the wire and
        empty to a reader. The refusal has to carry a machine-readable ``reason``, or
        the UI renders generic copy for a case it knows how to explain."""
        company_id = _add_cisco(http)

        resp = http.patch(
            f"/api/users/companies/{company_id}", json={"displayName": " ​ "}
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["reason"] == "name_empty", resp.text

        too_long = http.patch(
            f"/api/users/companies/{company_id}", json={"displayName": "x" * 101}
        )
        assert too_long.status_code == 422, too_long.text
        assert too_long.json()["reason"] == "name_too_long", too_long.text

        assert db.company_row(db_conn, company_id)["user_display_name"] is None, (
            "AC-25a: a refused rename must write nothing"
        )


class TestRenameSurvivesReDerivation:
    """AC-25b, AC-25c — the non-obvious half.

    If either of these ever fails, the feature is worse than not shipping it: a user
    renames a board, does something ordinary, and silently gets the old name back.
    """

    def test_ac25b_a_rename_survives_re_adding_the_same_url(self, http, db_conn):
        """AC-25b. Re-pasting a URL you already track is idempotent and answers 200 with
        the existing row — and that answer, and the row behind it, must be the name the
        user chose."""
        company_id = _add_cisco(http)
        http.patch(f"/api/users/companies/{company_id}", json={"displayName": NEW_NAME})

        readd = http.post("/api/users/companies", json={"url": CISCO_URL})
        assert readd.status_code == 200, (
            f"AC-25b: re-adding a tracked board must be idempotent, got "
            f"{readd.status_code}: {readd.text}"
        )
        assert readd.json()["id"] == company_id, "AC-25b: no second row"
        assert readd.json()["displayName"] == NEW_NAME, (
            "AC-25b: the re-add's own response must carry the user's name — a body "
            "showing the derived name makes a correct row look like it reverted"
        )
        assert find_company(http, company_id)["displayName"] == NEW_NAME
        assert db.company_row(db_conn, company_id)["user_display_name"] == NEW_NAME

    def test_ac25c_a_rename_survives_a_re_discovery(self, http, db_conn):
        """AC-25c. THE ONE THAT WOULD HAVE BITTEN.

        ``custom_companies_service._promote_to_tracked`` runs
        ``SET display_name = %s`` every time discovery accepts a board, and
        ``restart_refused_discovery`` runs the same statement on the retry of a refused
        one — which is the only retry the UI offers. Driven here directly, against this
        suite's real database and the row a real HTTP add just created, because the
        statement is what is under test and reaching it through a live discovery costs a
        browser session and an LLM call to prove the same UPDATE.
        """
        import api.services.custom_companies_service as svc

        company_id = _add_cisco(http)
        http.patch(f"/api/users/companies/{company_id}", json={"displayName": NEW_NAME})
        user_id = db.user_id_for_email(db_conn, PRIMARY_USER["email"])
        assert user_id is not None

        promoted = svc._promote_to_tracked(
            db_conn,
            user_id=user_id,
            company_id=company_id,
            submitted_url=CISCO_URL,
            normalized_url=CISCO_URL,
            # The freshly DERIVED label the discovery task always hands in.
            display_name="Jobs Cisco",
            script={"kind": "http_json"},
            script_version=1,
            transport="http_json",
            oracle_kind="self_consistent",
        )
        assert promoted is not None, "AC-25c: the promote must have matched the row"
        assert promoted["display_name"] == NEW_NAME, (
            "AC-25c: the promote path's own return value must be the EFFECTIVE name; "
            "the add response is built from it"
        )

        row = db.company_row(db_conn, company_id)
        assert row["user_display_name"] == NEW_NAME, (
            "AC-25c: re-discovery must not be able to reach the user's name at all"
        )
        assert row["display_name"] == "Jobs Cisco", (
            "AC-25c: ...while the derived column IS refreshed, which is the point of "
            "keeping both"
        )
        assert find_company(http, company_id)["displayName"] == NEW_NAME, (
            "AC-25c: and the list — the thing the user reads — still says Raindrop"
        )


class TestRenameOwnership:
    """AC-25d — AC-10's isolation guarantee, extended to the new mutation."""

    def test_ac25d_user_b_cannot_rename_user_as_company(self, http, other_http, db_conn):
        company_id = _add_cisco(http)
        http.patch(f"/api/users/companies/{company_id}", json={"displayName": NEW_NAME})

        # B IS A REAL USER with their own row and their own board. Without that, the
        # 404 below arrives from the "this email owns nothing" branch and proves nothing
        # about ownership — the same trap the backend unit test fell into.
        b_resp = other_http.post("/api/users/companies", json={"url": CISCO_URL})
        assert b_resp.status_code == 201, b_resp.text
        b_company_id = str(b_resp.json()["id"])
        assert b_company_id != company_id, "two users adding one board get two rows"

        stolen = other_http.patch(
            f"/api/users/companies/{company_id}", json={"displayName": "Stolen"}
        )
        assert stolen.status_code == 404, (
            f"AC-25d: user B renaming A's company must 404 — 403 would confirm the id "
            f"exists, and the mutations on this router answer 404 for that reason. Got "
            f"{stolen.status_code}: {stolen.text}"
        )

        assert db.company_row(db_conn, company_id)["user_display_name"] == NEW_NAME, (
            "AC-25d: A's name must be untouched by B's attempt"
        )
        assert db.company_row(db_conn, b_company_id)["user_display_name"] is None, (
            "AC-25d: and B's own row must not have been renamed instead — a WHERE "
            "clause that lost the id would rename the wrong board rather than none"
        )
        assert find_company(http, company_id)["displayName"] == NEW_NAME

    def test_ac25d_an_anonymous_caller_cannot_rename_anything(
        self, http, anon_http, db_conn
    ):
        company_id = _add_cisco(http)
        resp = anon_http.patch(
            f"/api/users/companies/{company_id}", json={"displayName": "Stolen"}
        )
        assert resp.status_code in (401, 403), (
            f"AC-25d: an unauthenticated rename must not be accepted, got "
            f"{resp.status_code}: {resp.text}"
        )
        assert db.company_row(db_conn, company_id)["user_display_name"] is None
