"""Unit tests for the PURE location canonicalizer (api/services/location_canonicalize.py).

Runs in the normal backend suite: no API key, no network, no DB. This is the real
regression net for the canonicalization rules (the LLM eval is downstream of a
different boundary and does not exercise this pass).
"""

from __future__ import annotations

from dataclasses import dataclass

from api.services.location_canonicalize import (
    canonical_country,
    canonical_region,
    canonicalize,
    canonicalize_parts,
)


@dataclass
class _Loc:
    """Minimal stand-in for CanonicalLocation / LocationSpec (the 6 attrs)."""

    canonical_name: str
    kind: str
    city: str | None = None
    region: str | None = None
    country: str | None = None
    remote_scope: str | None = None


class TestCanonicalCountry:
    def test_full_names_map_to_iso2(self):
        assert canonical_country("Brazil") == "BR"
        assert canonical_country("India") == "IN"
        assert canonical_country("Sweden") == "SE"
        assert canonical_country("Germany") == "DE"
        assert canonical_country("United States") == "US"

    def test_uk_maps_to_gb(self):
        assert canonical_country("UK") == "GB"
        assert canonical_country("United Kingdom") == "GB"
        assert canonical_country("GBR") == "GB"
        assert canonical_country("GB") == "GB"

    def test_two_letter_passthrough_uppercased(self):
        assert canonical_country("us") == "US"
        assert canonical_country("DE") == "DE"

    def test_none_and_blank(self):
        assert canonical_country(None) is None
        assert canonical_country("   ") is None

    def test_unmappable_returned_unchanged(self):
        # Not ISO-2, not in the dict -> returned as-is (caller logs it).
        assert canonical_country("Atlantis") == "Atlantis"


class TestCanonicalRegion:
    def test_us_full_state_name_to_usps(self):
        assert canonical_region("California", "US", "city") == "CA"
        assert canonical_region("texas", "US", "city") == "TX"

    def test_us_two_letter_preserved(self):
        assert canonical_region("CA", "US", "city") == "CA"
        assert canonical_region("ca", "US", "city") == "CA"

    def test_non_us_region_dropped(self):
        assert canonical_region("Bavaria", "DE", "city") is None
        assert canonical_region("QLD", "AU", "region") is None
        assert canonical_region("Karnataka", "IN", "city") is None

    def test_region_equals_country_dropped(self):
        # "Dublin, IE, IE" -> region collapses to None.
        assert canonical_region("IE", "IE", "city") is None

    def test_macro_region_without_country_preserved(self):
        assert canonical_region("EMEA", None, "region") == "EMEA"
        assert canonical_region("Europe", None, "region") == "Europe"

    def test_none(self):
        assert canonical_region(None, "US", "city") is None


class TestCanonicalize:
    def test_city_label_recomputed_us(self):
        c = canonicalize(_Loc("Cupertino, CA, USA", "city", "Cupertino", "CA", "USA"))
        assert (c.city, c.region, c.country) == ("Cupertino", "CA", "US")
        assert c.canonical_name == "Cupertino, CA, US"

    def test_city_non_us_drops_region_in_label(self):
        c = canonicalize(_Loc("Berlin, Berlin, Germany", "city", "Berlin", "Berlin", "Germany"))
        assert (c.region, c.country) == (None, "DE")
        assert c.canonical_name == "Berlin, DE"

    def test_uk_city_label(self):
        c = canonicalize(_Loc("London, England, UK", "city", "London", "England", "UK"))
        assert (c.region, c.country) == (None, "GB")
        assert c.canonical_name == "London, GB"

    def test_country_label_preserved_code_fixed(self):
        c = canonicalize(_Loc("United States", "country", None, None, "USA"))
        assert c.country == "US"
        assert c.canonical_name == "United States"  # label preserved (eval-locked)

    def test_remote_label_preserved(self):
        c = canonicalize(_Loc("Remote (US)", "remote", None, None, "US", "us"))
        assert c.canonical_name == "Remote (US)"
        assert c.country == "US"
        assert c.remote_scope == "us"

    def test_region_kind_label_preserved(self):
        c = canonicalize(_Loc("California, US", "region", None, "CA", "US"))
        assert (c.region, c.country) == ("CA", "US")
        assert c.canonical_name == "California, US"

    def test_idempotent(self):
        once = canonicalize(_Loc("Bangalore, KA, India", "city", "Bangalore", "KA", "India"))
        twice = canonicalize_parts(
            kind=once.kind,
            canonical_name=once.canonical_name,
            city=once.city,
            region=once.region,
            country=once.country,
            remote_scope=once.remote_scope,
        )
        assert once == twice
        assert twice.canonical_name == "Bangalore, IN"
