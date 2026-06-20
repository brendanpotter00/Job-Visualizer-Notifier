"""Tests for the idempotent curated-company profile seeder.

Includes the load-bearing assertion that script-scraped rows (ats="script") are
inert for every ATS fan-out — the user's explicit requirement that Google /
Apple / Microsoft never get queued or scraped by adding them to the table.
"""

from psycopg2 import sql

from api.services.companies_seed import SCRIPT_ATS, seed_company_profiles
from scripts.shared.database import list_enabled_companies

# Every ATS whose fan-out task calls list_enabled_companies(conn, <ats>). A
# script row must be selected by none of these.
WORKER_ATS = ("greenhouse", "ashby", "lever", "gem", "eightfold", "workday")

# Small fixture standing in for the committed JSON. The three script entries
# carry the row-creation fields; "stripe" is an already-seeded worker company.
PROFILES = {
    "stripe": {"blurb": "Payments infra.", "accomplishment": "Powers online checkout."},
    "google": {
        "blurb": "Search and ads.",
        "accomplishment": "Runs the most-used search engine.",
        "displayName": "Google",
        "ats": "script",
        "boardToken": "google",
    },
    "apple": {
        "blurb": "Consumer hardware.",
        "accomplishment": "Makes the iPhone.",
        "displayName": "Apple",
        "ats": "script",
        "boardToken": "apple",
    },
    "microsoft": {
        "blurb": "Software and cloud.",
        "accomplishment": "Makes Windows and Azure.",
        "displayName": "Microsoft",
        "ats": "script",
        "boardToken": "microsoft",
    },
}


def _insert_company(conn, company_id, ats="greenhouse"):
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token)"
            " VALUES (%s, %s, %s, %s)"
        ).format(sql.Identifier("companies")),
        (company_id, company_id.title(), ats, company_id),
    )
    conn.commit()


def _row(conn, company_id):
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "SELECT id, display_name, ats, blurb, accomplishment, enabled"
            " FROM {} WHERE id = %s"
        ).format(sql.Identifier("companies")),
        (company_id,),
    )
    return cur.fetchone()


def test_inserts_script_rows_and_upserts_blurbs(db_conn):
    _insert_company(db_conn, "stripe", "greenhouse")

    result = seed_company_profiles(db_conn, PROFILES)

    assert result["script_inserted"] == 3
    assert result["updated"] == 4  # stripe + 3 script rows
    assert result["unmatched"] == []

    stripe = _row(db_conn, "stripe")
    assert stripe["blurb"] == "Payments infra."
    assert stripe["accomplishment"] == "Powers online checkout."
    assert stripe["ats"] == "greenhouse"  # untouched

    google = _row(db_conn, "google")
    assert google["ats"] == SCRIPT_ATS == "script"
    assert google["enabled"] is True
    assert google["display_name"] == "Google"
    assert google["blurb"] == "Search and ads."


def test_idempotent(db_conn):
    _insert_company(db_conn, "stripe", "greenhouse")
    seed_company_profiles(db_conn, PROFILES)

    second = seed_company_profiles(db_conn, PROFILES)
    assert second["script_inserted"] == 0  # ON CONFLICT DO NOTHING

    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier("companies"))
    )
    assert cur.fetchone()["n"] == 4  # no duplicate script rows


def test_file_is_source_of_truth_overwrites_existing_content(db_conn):
    _insert_company(db_conn, "stripe", "greenhouse")
    seed_company_profiles(db_conn, {"stripe": {"blurb": "old", "accomplishment": "old"}})

    seed_company_profiles(db_conn, {"stripe": {"blurb": "new", "accomplishment": "new2"}})

    stripe = _row(db_conn, "stripe")
    assert stripe["blurb"] == "new"
    assert stripe["accomplishment"] == "new2"


def test_profile_for_unknown_company_is_unmatched_not_fatal(db_conn):
    # A profile id absent from `companies` is counted/logged, never raised — a
    # company can be removed from the table while its JSON entry lingers.
    result = seed_company_profiles(
        db_conn, {"ghost": {"blurb": "x", "accomplishment": "y"}}
    )
    assert result["updated"] == 0
    assert "ghost" in result["unmatched"]


def test_loads_committed_json_and_backdates_script_rows(db_conn):
    """No `profiles` arg → the real committed company_profiles.json is loaded
    lazily. Validates the file parses, the 3 script rows are created, and their
    created_at is backdated so they don't trip the auto-enroll watermark."""
    result = seed_company_profiles(db_conn)  # loads data/company_profiles.json
    assert result["script_inserted"] == 3  # google/apple/microsoft

    google = _row(db_conn, "google")
    assert google is not None
    assert google["ats"] == SCRIPT_ATS
    assert google["blurb"]  # real researched blurb present

    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT created_at FROM {} WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        ("google",),
    )
    created_at = cur.fetchone()["created_at"]
    # Backdated well into the past so it predates any user's auto-enroll
    # watermark — google/apple/microsoft are backfills, not new launches.
    assert created_at.year <= 2020


def test_script_rows_are_inert_for_every_fanout(db_conn):
    """Hard requirement: script companies must never be enqueued by any ATS
    fan-out. list_enabled_companies(ats) backs every fan-out task — assert it
    returns none of google/apple/microsoft for any worker ATS, and that they
    ARE reachable only under the sentinel ats."""
    seed_company_profiles(db_conn, PROFILES)
    script_ids = {"google", "apple", "microsoft"}

    for ats in WORKER_ATS:
        selected = {c["id"] for c in list_enabled_companies(db_conn, ats)}
        assert script_ids.isdisjoint(selected), (
            f"script rows leaked into the {ats} fan-out: {script_ids & selected}"
        )

    sentinel_selected = {c["id"] for c in list_enabled_companies(db_conn, SCRIPT_ATS)}
    assert script_ids <= sentinel_selected
