"""Tests for the Tier-1 location-normalization service.

normalize_string tests are pure (no DB). lookup_alias tests are integration
tests against a real Postgres via the module-scoped ``db_conn`` fixture in
conftest.py (per-module test_<hex> schema with the ORM tables materialized and
search_path pinned).

NOTE: conftest's autouse ``clean_tables`` fixture does NOT truncate the four
location tables, so each lookup_alias test cleans them itself via the
``clean_location_tables`` fixture below to stay isolated.
"""

import pytest
from psycopg2 import sql

from api.services.location_normalization import lookup_alias, normalize_string


class TestNormalizeString:
    def test_lowercases(self):
        assert normalize_string("San Francisco") == "san francisco"

    def test_trims_leading_and_trailing(self):
        assert normalize_string("   San Francisco   ") == "san francisco"

    def test_collapses_internal_whitespace_runs(self):
        assert normalize_string("  San   Francisco ,  CA  ") == "san francisco , ca"

    def test_collapses_tabs_and_newlines(self):
        assert normalize_string("San\tFrancisco\n,\nCA") == "san francisco , ca"

    def test_normalizes_unicode_dashes(self):
        assert normalize_string("Remote – United States") == "remote - united states"
        assert normalize_string("Remote — US") == "remote - us"
        assert normalize_string("A‒B‐C‑D−E") == "a-b-c-d-e"

    def test_normalizes_unicode_quotes(self):
        assert normalize_string("O’Fallon") == "o'fallon"
        assert normalize_string("“Remote”") == '"remote"'

    def test_nfkc_folds_compatibility_forms(self):
        assert normalize_string("ＡＢＣ") == "abc"
        assert normalize_string("San Francisco") == "san francisco"

    def test_preserves_accents_on_real_letters(self):
        assert normalize_string("Zürich") == "zürich"
        assert normalize_string("São Paulo") == "são paulo"
        assert normalize_string("München, Bayern") == "münchen, bayern"

    def test_empty_string(self):
        assert normalize_string("") == ""

    def test_all_whitespace_becomes_empty(self):
        assert normalize_string("   \t\n  ") == ""

    def test_none_returns_empty_string(self):
        assert normalize_string(None) == ""

    def test_idempotent(self):
        samples = [
            "San Francisco",
            "  San   Francisco ,  CA  ",
            "Remote – United States",
            "“Remote”",
            "Zürich",
            "São Paulo",
            "",
            "   \t  ",
        ]
        for s in samples:
            once = normalize_string(s)
            assert normalize_string(once) == once, f"not idempotent for {s!r}"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("San Francisco", "san francisco"),
            ("San Francisco, CA", "san francisco, ca"),
            ("  San   Francisco ,  CA  ", "san francisco , ca"),
            ("Mountain View (US-MTV-EMF680)", "mountain view (us-mtv-emf680)"),
            ("Cupertino, California, United States", "cupertino, california, united states"),
            ("United States, Washington, Redmond", "united states, washington, redmond"),
            ("Costa Mesa, CA (HQ)", "costa mesa, ca (hq)"),
            ("Sunnyvale, CA, USA; Kirkland, WA, USA", "sunnyvale, ca, usa; kirkland, wa, usa"),
            ("Remote - United States", "remote - united states"),
            ("Remote", "remote"),
        ],
    )
    def test_real_prod_strings(self, raw, expected):
        assert normalize_string(raw) == expected


_LOCATIONS = sql.Identifier("locations")
_LOCATION_ALIASES = sql.Identifier("location_aliases")
_ALIAS_LOCATIONS = sql.Identifier("alias_locations")


@pytest.fixture
def clean_location_tables(db_conn):
    """Truncate the location tables before each lookup_alias test."""
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("TRUNCATE {}, {}, {} CASCADE").format(
            _ALIAS_LOCATIONS, _LOCATION_ALIASES, _LOCATIONS
        )
    )
    db_conn.commit()


def _insert_location(db_conn, *, canonical_name, kind, city=None, region=None,
                     country=None, remote_scope=None):
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (canonical_name, kind, city, region, country, remote_scope)"
            " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
        ).format(_LOCATIONS),
        (canonical_name, kind, city, region, country, remote_scope),
    )
    row = cur.fetchone()
    db_conn.commit()
    return int(row["id"]) if isinstance(row, dict) else int(row[0])


def _insert_alias(db_conn, raw_text, *, source="llm", confidence=0.95):
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (raw_text, source, confidence) VALUES (%s, %s, %s)"
        ).format(_LOCATION_ALIASES),
        (raw_text, source, confidence),
    )
    db_conn.commit()


def _insert_alias_location(db_conn, raw_text, location_id, position):
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (raw_text, normalized_location_id, position)"
            " VALUES (%s, %s, %s)"
        ).format(_ALIAS_LOCATIONS),
        (raw_text, location_id, position),
    )
    db_conn.commit()


@pytest.mark.usefixtures("clean_location_tables")
class TestLookupAlias:
    def test_miss_returns_none(self, db_conn):
        assert lookup_alias(db_conn, "Nowhere, XX") is None

    def test_single_location_hit(self, db_conn):
        loc_id = _insert_location(
            db_conn, canonical_name="San Francisco, CA, US", kind="city",
            city="San Francisco", region="CA", country="US",
        )
        _insert_alias(db_conn, "san francisco")
        _insert_alias_location(db_conn, "san francisco", loc_id, position=0)
        assert lookup_alias(db_conn, "San Francisco") == [loc_id]

    def test_multi_location_hit_in_position_order(self, db_conn):
        sunnyvale = _insert_location(
            db_conn, canonical_name="Sunnyvale, CA, US", kind="city",
            city="Sunnyvale", region="CA", country="US",
        )
        kirkland = _insert_location(
            db_conn, canonical_name="Kirkland, WA, US", kind="city",
            city="Kirkland", region="WA", country="US",
        )
        key = "sunnyvale, ca, usa; kirkland, wa, usa"
        _insert_alias(db_conn, key)
        _insert_alias_location(db_conn, key, kirkland, position=1)
        _insert_alias_location(db_conn, key, sunnyvale, position=0)
        result = lookup_alias(db_conn, "Sunnyvale, CA, USA; Kirkland, WA, USA")
        assert result == [sunnyvale, kirkland]

    def test_pre_normalization_makes_variants_hit_same_row(self, db_conn):
        loc_id = _insert_location(
            db_conn, canonical_name="San Francisco, CA, US", kind="city",
            city="San Francisco", region="CA", country="US",
        )
        _insert_alias(db_conn, "san francisco")
        _insert_alias_location(db_conn, "san francisco", loc_id, position=0)
        assert lookup_alias(db_conn, "  SAN FRANCISCO  ") == [loc_id]
        assert lookup_alias(db_conn, "san francisco") == [loc_id]
        assert lookup_alias(db_conn, "San Francisco") == [loc_id]

    def test_present_but_empty_alias_returns_empty_list_not_none(self, db_conn):
        _insert_alias(db_conn, "ghost city")
        assert lookup_alias(db_conn, "Ghost City") == []
