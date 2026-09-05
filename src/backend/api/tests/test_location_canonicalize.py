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
    canonical_remote_scope,
    canonicalize,
    canonicalize_parts,
    render_canonical_name,
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

    def test_country_label_derived_from_code(self):
        c = canonicalize(_Loc("United States", "country", None, None, "USA"))
        assert c.country == "US"
        # Derived from the ISO-2 code now, not carried over from the model. It
        # happens to equal the old preserved label, which is the point: the
        # derivation reproduces the intended label without depending on the
        # model to spell it the same way twice.
        assert c.canonical_name == "United States"

    def test_remote_label_derived(self):
        c = canonicalize(_Loc("Remote (US)", "remote", None, None, "US", "us"))
        assert c.canonical_name == "Remote (US)"
        assert c.country == "US"
        assert c.remote_scope == "us"

    def test_remote_label_is_derived_not_echoed(self):
        """A junk label + junk scope still produces the canonical rendering."""
        c = canonicalize(_Loc("REMOTE - usa (anywhere in US)", "remote", None, None,
                              "United States", "zone_1"))
        assert c.country == "US"
        assert c.remote_scope == "us"
        assert c.canonical_name == "Remote (US)"

    def test_region_kind_label_derived(self):
        c = canonicalize(_Loc("California, US", "region", None, "CA", "US"))
        assert (c.region, c.country) == ("CA", "US")
        # USPS code expanded back to the state name for the label.
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


class TestCanonicalRemoteScope:
    """remote_scope is part of `uq_locations_canonical`, so an unvalidated value
    forges a new `locations` row. Prod reached 113 distinct values for what
    should be ~60 -- 23 rows all named "Remote (US)", 14 all named "Remote"."""

    def test_macro_regions_pass_through(self):
        for token in ("global", "amer", "namer", "latam", "emea", "eu", "apac"):
            assert canonical_remote_scope(token, kind="remote", canon_country=None) == token

    def test_case_and_spelling_variants_collapse(self):
        for raw in ("Global", "GLOBAL", "worldwide", "Worldwide", "anywhere"):
            assert canonical_remote_scope(raw, kind="remote", canon_country=None) == "global"
        for raw in ("AMER", "americas", "Americas", "AMERICAS"):
            assert canonical_remote_scope(raw, kind="remote", canon_country=None) == "amer"
        for raw in ("APAC", "apac", "Asia Pacific"):
            assert canonical_remote_scope(raw, kind="remote", canon_country=None) == "apac"

    def test_country_names_and_codes_collapse_to_iso2(self):
        assert canonical_remote_scope("Brazil", kind="remote", canon_country="BR") == "br"
        assert canonical_remote_scope("br", kind="remote", canon_country="BR") == "br"
        assert canonical_remote_scope("United States", kind="remote", canon_country="US") == "us"
        assert canonical_remote_scope("USA", kind="remote", canon_country="US") == "us"
        assert canonical_remote_scope("UK", kind="remote", canon_country="GB") == "gb"

    def test_non_geographic_words_fall_back_to_country(self):
        """'country'/'region'/'state'/'full' describe HOW remote, not WHERE."""
        for junk in ("country", "region", "regional", "state", "full", "partial",
                     "unspecified", "local", "remote-friendly",
                     "telecommuting_permitted"):
            assert canonical_remote_scope(junk, kind="remote", canon_country="US") == "us"
            assert canonical_remote_scope(junk, kind="remote", canon_country=None) is None

    def test_remote_is_a_tautology_not_a_global_claim(self):
        """remote_scope='remote' says the row IS remote -- which kind already
        says -- not that it is worldwide. Treating it as 'global' would widen a
        US-only remote role to the whole planet. Prod has 16 such rows carrying
        countries US/GB and regions NY/MN/PA/TX/CA."""
        assert canonical_remote_scope("remote", kind="remote", canon_country="US") == "us"
        assert canonical_remote_scope("remote", kind="remote", canon_country="GB") == "gb"
        assert canonical_remote_scope("remote", kind="remote", canon_country=None) is None
        assert canonical_remote_scope("fully remote", kind="remote", canon_country="US") == "us"

    def test_genuine_global_claims_still_map_to_global(self):
        for raw in ("worldwide", "anywhere", "world", "global"):
            assert canonical_remote_scope(
                raw, kind="remote", canon_country=None) == "global"

    def test_ats_junk_falls_back_to_country(self):
        assert canonical_remote_scope("zone_1", kind="remote", canon_country="US") == "us"
        assert canonical_remote_scope("US-Eastern", kind="remote", canon_country="US") == "us"
        assert canonical_remote_scope("Bay Area, CA", kind="remote", canon_country="US") == "us"

    def test_whole_label_in_the_scope_column_is_unwrapped(self):
        assert canonical_remote_scope("Remote (US)", kind="remote", canon_country="US") == "us"
        assert canonical_remote_scope(
            "Remote (Philippines)", kind="remote", canon_country="PH") == "ph"

    def test_two_letter_ambiguity_resolved_by_country(self):
        """CA is California AND Canada; IN is Indiana AND India."""
        # With a US country, a 2-letter scope is a STATE -> country-level scope.
        assert canonical_remote_scope("CA", kind="remote", canon_country="US") == "us"
        assert canonical_remote_scope("IN", kind="remote", canon_country="US") == "us"
        # With no country to anchor it, it reads as an ISO-2 country code.
        assert canonical_remote_scope("CA", kind="remote", canon_country=None) == "ca"

    def test_scope_is_none_for_non_remote_kinds(self):
        for kind in ("city", "region", "country"):
            assert canonical_remote_scope("us", kind=kind, canon_country="US") is None

    def test_never_raises_on_arbitrary_input(self):
        for junk in ("", "   ", "???", "Remote (India, Australia, New Zealand)",
                     "United States & Canada", "EMEA/AMER"):
            canonical_remote_scope(junk, kind="remote", canon_country=None)


class TestRenderCanonicalName:
    def test_city(self):
        assert render_canonical_name(
            kind="city", city="Austin", region="TX", country="US",
            remote_scope=None) == "Austin, TX, US"

    def test_country_uses_display_name(self):
        assert render_canonical_name(
            kind="country", city=None, region=None, country="BR",
            remote_scope=None) == "Brazil"

    def test_region_expands_us_state_code(self):
        assert render_canonical_name(
            kind="region", city=None, region="NY", country="US",
            remote_scope=None) == "New York, US"

    def test_macro_region_without_country(self):
        assert render_canonical_name(
            kind="region", city=None, region="EMEA", country=None,
            remote_scope=None) == "EMEA"

    def test_remote_us_stays_a_code(self):
        assert render_canonical_name(
            kind="remote", city=None, region=None, country="US",
            remote_scope="us") == "Remote (US)"

    def test_remote_other_countries_use_display_names(self):
        """ISO-2 collides with USPS: a bare 'Remote (CA)' would read as California."""
        assert render_canonical_name(
            kind="remote", city=None, region=None, country="CA",
            remote_scope="ca") == "Remote (Canada)"
        assert render_canonical_name(
            kind="remote", city=None, region=None, country="BR",
            remote_scope="br") == "Remote (Brazil)"

    def test_remote_us_state_scoped(self):
        assert render_canonical_name(
            kind="remote", city=None, region="AZ", country="US",
            remote_scope="us") == "Remote (AZ, US)"

    def test_remote_unscoped(self):
        assert render_canonical_name(
            kind="remote", city=None, region=None, country=None,
            remote_scope=None) == "Remote"

    def test_returns_none_when_there_is_no_structure(self):
        assert render_canonical_name(
            kind="country", city=None, region=None, country=None,
            remote_scope=None) is None


class TestUsRegionDropOnlyWhenItRestatesTheCountry:
    """Only a US region that RESTATES the country is dropped.

    An earlier version dropped EVERY unrecognised US region. That looked tidy
    and was badly wrong: 'Space Coast' (40 prod jobs), 'Bay Area' (16),
    'Southern California' (2) and 'Central Texas' (1) all collapse to the tuple
    (region, NULL, NULL, US), which uq_locations_canonical then merges into ONE
    row labelled 'United States'. A Florida-coast role would advertise itself as
    nationwide. Keeping an unmapped region costs one row per spelling; dropping
    it costs real geography.
    """

    def test_region_restating_the_country_is_dropped(self):
        assert canonical_region("United States", "US", "remote") is None
        assert canonical_region("USA", "US", "remote") is None
        assert canonical_region("US", "US", "remote") is None

    def test_real_us_metros_are_kept_not_merged(self):
        for metro in ("Space Coast", "Bay Area", "Southern California",
                      "Central Texas", "California or Arizona"):
            assert canonical_region(metro, "US", "region") == metro, (
                f"{metro!r} was dropped; it would merge into the generic US row"
            )

    def test_kept_metros_stay_distinct_from_each_other(self):
        names = {
            canonicalize(_Loc("", "region", None, m, "US")).canonical_name
            for m in ("Space Coast", "Bay Area", "Southern California")
        }
        assert len(names) == 3, f"metros collapsed to the same label: {names}"

    def test_real_states_still_survive(self):
        assert canonical_region("Michigan", "US", "city") == "MI"
        assert canonical_region("MI", "US", "city") == "MI"

    def test_country_restating_region_derives_a_clean_label(self):
        c = canonicalize(_Loc("Remote (United States)", "remote", None,
                              "United States", "US", "country"))
        assert c.region is None
        assert c.canonical_name == "Remote (US)"


class TestScopeCollapseOnRealProdValues:
    """The distinct (scope, region, country) tuples prod actually holds for
    kind='remote' must collapse hard -- that shrinkage IS the fix."""

    def test_prod_variants_collapse(self):
        raw_variants = [
            ("us", None, None), ("US", None, "US"), ("USA", None, "US"),
            ("United States", None, "US"), ("country", None, "US"),
            ("country", "DC", "US"), ("region", "MA", "US"), ("state", "OH", "US"),
            ("remote", None, "US"), ("remote-friendly", None, "US"),
            ("Remote (US)", None, "US"), ("zone_1", None, "US"),
        ]
        collapsed = {
            canonical_remote_scope(scope, kind="remote", canon_country=country)
            for scope, _region, country in raw_variants
        }
        # Twelve prod spellings of "remote, anywhere in the US" -> one value.
        assert collapsed == {"us"}


class TestReviewBlockers:
    """Regression cover for the blockers the Opus review round found."""

    def test_unmappable_country_never_leaks_into_the_scope_vocabulary(self):
        """canonical_country() echoes an unmappable value back unchanged, so the
        scope fallback must re-validate it. Prod rows that would otherwise have
        produced scopes like 'united states & canada' (175 job links)."""
        valid_macro = {"global", "amer", "namer", "latam", "emea", "eu", "apac"}
        for country in ("United States & Canada", "Turkey", "Canada/USA",
                        "Multiple Locations", "Atlantis"):
            out = canonical_remote_scope("country", kind="remote", canon_country=country)
            assert out is None or out in valid_macro or (
                len(out) == 2 and out.isalpha() and out.islower()
            ), f"country={country!r} leaked scope {out!r}"

    def test_macro_scope_is_not_overridden_by_a_us_state(self):
        """A globally-remote role that happens to carry a US region must not be
        labelled as that single state -- the stored scope said global while the
        label the user filters on said California."""
        for scope, want in [("global", "Remote (Global)"), ("emea", "Remote (EMEA)"),
                            ("namer", "Remote (NAMER)")]:
            c = canonicalize(_Loc("", "remote", None, "CA", "US", scope))
            assert c.canonical_name == want

    def test_us_state_scope_still_renders_the_state(self):
        c = canonicalize(_Loc("", "remote", None, "AZ", "US", "us"))
        assert c.canonical_name == "Remote (AZ, US)"

    def test_dc_is_not_title_cased_to_capital_of(self):
        c = canonicalize(_Loc("", "region", None, "DC", "US"))
        assert c.canonical_name == "District of Columbia, US"
