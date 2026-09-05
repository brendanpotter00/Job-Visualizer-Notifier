"""Deterministic post-LLM canonicalization of location structured fields.

PURE module (stdlib only, no DB / no network) so it is unit-testable without an
ANTHROPIC_API_KEY and can be imported by BOTH the live pipeline
(``location_normalization.persist_llm_result`` /
``location_admin._upsert_location``) and the one-off backfill
(``scripts/one_off/2026-06-14_canonicalize_locations.py``). Sharing one
``canonicalize`` entry point guarantees the live writes and the historical
backfill can never drift apart.

Why this exists
---------------
Hierarchical location FILTERING in the frontend compares ``region`` + ``country``
codes across a job's tags (a region tag matches its cities; a country tag matches
everything in-country). That only works if those codes are CONSISTENT. The Tier-2
Haiku normalizer emits the same physical place several ways — ``Germany`` vs
``DE``, ``UK`` vs ``GB``, ``Berlin``/``North Holland``/ISO as region — so each
rendering becomes a separate ``locations`` row and the hierarchy mis-groups. See
``docs/implementations/locationNormalization/FOLLOWUP-canonical-fragmentation.md``.

Rules (lowest-risk, deterministic)
----------------------------------
* country -> ISO-3166-1 alpha-2 (``Brazil`` -> ``BR``, ``UK`` -> ``GB``). An
  unmappable value is returned UNCHANGED and logged at WARNING — never guessed.
* region -> for US, USPS 2-letter (full state names mapped, anything else
  dropped); for any other country, dropped to ``None`` (no reliable intl subdivision map, and the eval
  scorer does not alias region names). ``region == country`` is collapsed to
  ``None``. A ``kind='region'`` row with no country (macro-regions like ``EMEA``)
  is left untouched.
* remote_scope -> coerced onto a CLOSED vocabulary: ``global``, a macro region
  (``amer``/``namer``/``latam``/``emea``/``eu``/``apac``), or a lowercase ISO-2
  country code. Unrecognised values fall back to the row's own country rather
  than being rejected, so a bad scope costs the scope, never the location.
* canonical_name -> recomputed deterministically for EVERY kind. The label is a
  pure function of the canonicalized tuple, so one physical place renders exactly
  one way. This is safe because the eval scorer compares structured fields only
  (``api/eval/scoring.py``) -- ``canonical_name`` is not part of the match.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

_TWO_LETTER = re.compile(r"^[A-Z]{2}$")


# --- country: name / variant -> ISO-3166-1 alpha-2 ---------------------------
# Curated for the ~30 countries seen in prod plus common neighbours. Keys are
# upper-cased + whitespace-collapsed. Extend when verification flags a miss.
_COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    # full names
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "AMERICA": "US",
    "UNITED KINGDOM": "GB",
    "GREAT BRITAIN": "GB",
    "BRAZIL": "BR",
    "INDIA": "IN",
    "SWEDEN": "SE",
    "GERMANY": "DE",
    "NETHERLANDS": "NL",
    "SPAIN": "ES",
    "FRANCE": "FR",
    "ITALY": "IT",
    "PORTUGAL": "PT",
    "POLAND": "PL",
    "IRELAND": "IE",
    "LUXEMBOURG": "LU",
    "BELGIUM": "BE",
    "AUSTRIA": "AT",
    "SWITZERLAND": "CH",
    "DENMARK": "DK",
    "NORWAY": "NO",
    "FINLAND": "FI",
    "CANADA": "CA",
    "MEXICO": "MX",
    "CHILE": "CL",
    "COLOMBIA": "CO",
    "ECUADOR": "EC",
    "AUSTRALIA": "AU",
    "NEW ZEALAND": "NZ",
    "JAPAN": "JP",
    "CHINA": "CN",
    "SOUTH KOREA": "KR",
    "KOREA": "KR",
    "SINGAPORE": "SG",
    "HONG KONG": "HK",
    "TAIWAN": "TW",
    "MALAYSIA": "MY",
    "INDONESIA": "ID",
    "THAILAND": "TH",
    "PHILIPPINES": "PH",
    "ISRAEL": "IL",
    "UNITED ARAB EMIRATES": "AE",
    "QATAR": "QA",
    "EGYPT": "EG",
    "SERBIA": "RS",
    "LITHUANIA": "LT",
    "BULGARIA": "BG",
    # Seen in prod's remote_scope column but previously unmapped, so
    # canonical_country left them unchanged and each spelling forged its own row.
    "ARGENTINA": "AR",
    "COSTA RICA": "CR",
    "CYPRUS": "CY",
    "CROATIA": "HR",
    "ESTONIA": "EE",
    "PERU": "PE",
    "ROMANIA": "RO",
    "RUSSIA": "RU",
    "SAUDI ARABIA": "SA",
    "SOUTH AFRICA": "ZA",
    "UKRAINE": "UA",
    "URUGUAY": "UY",
    "VIETNAM": "VN",
    # code aliases / non-ISO 2-letter
    "USA": "US",
    "U.S.": "US",
    "U.S.A.": "US",
    "UK": "GB",
    "GBR": "GB",
}


def canonical_country(raw: str | None) -> str | None:
    """Return the ISO-3166-1 alpha-2 code for a raw country value.

    ``None``/blank -> ``None``. A known name/variant -> its ISO-2 code. An
    already-2-letter code passes through uppercased (``UK`` -> ``GB``). Anything
    else is returned UNCHANGED and logged (so verification surfaces it rather
    than us guessing a wrong code).
    """
    if raw is None:
        return None
    s = " ".join(str(raw).split()).strip().upper()
    if not s:
        return None
    mapped = _COUNTRY_NAME_TO_ISO2.get(s)
    if mapped:
        return mapped
    if _TWO_LETTER.match(s):
        return "GB" if s == "UK" else s
    logger.warning("canonical_country: unmappable country %r left unchanged", raw)
    return raw


# --- region: US -> USPS 2-letter; non-US -> dropped --------------------------
_US_STATE_NAME_TO_USPS: dict[str, str] = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT",
    "DISTRICT OF COLUMBIA": "DC", "DELAWARE": "DE", "FLORIDA": "FL",
    "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY",
    "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO",
    "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN",
    "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA",
    "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}
_US_STATE_CODES: frozenset[str] = frozenset(_US_STATE_NAME_TO_USPS.values())


def canonical_region(raw: str | None, canon_country: str | None, kind: str) -> str | None:
    """Return the canonical region for a (region, canonicalized-country, kind).

    * US country  -> USPS 2-letter (full state name mapped; unknown DROPPED + logged).
    * Other country -> ``None`` (drop; no reliable international subdivision map).
    * No country + ``kind='region'`` -> left untouched (macro-regions like EMEA).
    * ``region == country`` is collapsed to ``None``.
    """
    if raw is None:
        return None
    s = " ".join(str(raw).split()).strip()
    if not s:
        return None

    if canon_country == "US":
        up = s.upper()
        if _TWO_LETTER.match(up) and up in _US_STATE_CODES:
            region: str | None = up
        else:
            mapped = _US_STATE_NAME_TO_USPS.get(up)
            if mapped:
                region = mapped
            elif canonical_country(s) == canon_country:
                # The region merely RESTATES the country ('United States',
                # 'USA', 'US'). It carries no sub-national information, and
                # keeping it forges one row per spelling. Safe to drop.
                logger.warning(
                    "canonical_region: US region %r just restates the country; dropped", raw
                )
                return None
            else:
                # ANYTHING ELSE IS KEPT, even though it is not a USPS code.
                # An earlier version of this dropped every unrecognised US
                # region. That looked tidy and was badly wrong: prod carries
                # 'Space Coast' (40 jobs), 'Bay Area' (16), 'Southern
                # California' (2), 'Central Texas' (1) and 'California or
                # Arizona' (90). Dropping them does not merely lose detail --
                # every one collapses to the tuple (region, NULL, NULL, US),
                # which uq_locations_canonical then merges into a SINGLE row
                # rendering the generic label "United States". A Florida-coast
                # role would advertise itself as nationwide.
                #
                # Keeping an unmapped region costs one row per spelling (the
                # status quo). Dropping it costs real geography. Prefer the row.
                logger.warning(
                    "canonical_region: US region %r is not a USPS state; kept as-is "
                    "(dropping it would merge distinct places into 'United States')", raw
                )
                region = s
    elif canon_country is not None:
        # Non-US: drop the region (lowest-risk; filter by city or country).
        return None
    else:
        # No country to anchor the region: keep macro-regions (EMEA, Europe) and
        # any other country-less region as-is rather than fabricating geography.
        region = s if kind == "region" else None

    if region is not None and canon_country is not None and region == canon_country:
        return None
    return region


# --- remote_scope: closed vocabulary -----------------------------------------
#
# remote_scope participates in `uq_locations_canonical`, so every distinct value
# forges a distinct `locations` row. Nothing validated it, so the Tier-2 model
# filled it with whatever it felt like and prod accumulated 113 distinct values
# for what should be ~60: case variants ('us'/'US'/'USA'/'United States'), words
# describing the KIND of remoteness rather than WHERE ('country', 'region',
# 'state', 'full', 'partial', 'unspecified'), raw ATS junk ('zone_1',
# 'telecommuting_permitted'), and even whole rendered labels ('Remote (US)').
# The result: 23 rows all named "Remote (US)" and 14 all named "Remote".
#
# The vocabulary below is the one the eval golden set already assumes
# (`_remote("global")`, `_remote("us", ...)`, `_remote("br", ...)`,
# `_remote("emea")`) -- prod drifted away from its own contract because nothing
# enforced it.
#
# Coercion, not rejection: an unrecognised scope falls back to the row's own
# country (or None). Losing the SCOPE is a small loss; rejecting the response
# would retry and eventually mark the job 'failed', losing the location entirely.

_MACRO_REGIONS: frozenset[str] = frozenset(
    {"global", "amer", "namer", "latam", "emea", "eu", "apac"}
)

# Spellings of a macro region that are not the canonical token.
_SCOPE_ALIASES: dict[str, str] = {
    "worldwide": "global", "anywhere": "global", "world": "global",
    "americas": "amer",
    "north america": "namer", "northamerica": "namer",
    "latin america": "latam",
    "european union": "eu",
    "asia pacific": "apac", "asia-pacific": "apac", "asiapac": "apac",
}
# Deliberately NOT aliased, because each would change the MEANING of the scope
# rather than its spelling -- and this path returns before the warning, so the
# change would be silent:
#   "america"       -> 'amer' widens a US-only role to the whole hemisphere
#                      ("America" colloquially means the USA).
#   "europe"        -> 'eu'   narrows Europe to the EU, dropping GB/CH/NO/UA.
#   "south america" -> 'latam' widens to include Mexico and Central America.
# They fall through to the country fallback (or None) and get logged.

# Values that describe HOW remote a role is, not WHERE it may be worked from.
# They carry no geography, so the row's country (if any) becomes the scope.
# NOTE on "remote" / "fully remote": they say the row IS remote -- which we
# already know from kind='remote' -- not WHERE it may be worked from. Reading
# them as "global" would silently widen a US-only remote role to worldwide (prod
# has 16 such rows carrying countries US/GB and regions NY/MN/PA/TX/CA), so they
# belong here, not in _SCOPE_ALIASES.
_NON_GEOGRAPHIC_SCOPES: frozenset[str] = frozenset({
    "country", "region", "regional", "state", "province", "city",
    "remote", "fully remote", "full", "partial", "local", "hybrid", "flexible",
    "unspecified", "none", "null", "n/a", "other",
    "remote-friendly", "remote friendly", "telecommuting-permitted",
    "telecommuting_permitted", "telecommute", "wfh", "work from home",
})

_REMOTE_WRAPPER = re.compile(r"^remote\s*\((?P<inner>.+)\)$")


def canonical_remote_scope(
    raw: str | None, *, kind: str, canon_country: str | None
) -> str | None:
    """Coerce a raw remote_scope onto the closed vocabulary.

    Returns ``None``, a macro region (``global``/``amer``/``namer``/``latam``/
    ``emea``/``eu``/``apac``), or a lowercase ISO-3166-1 alpha-2 country code.
    Never raises.

    ``kind != 'remote'`` always yields ``None`` -- the cross-field invariant on
    ``CanonicalLocation`` already forbids a scope on a non-remote row, and
    enforcing it here too keeps the backfill honest.

    The 2-letter ambiguity (``CA`` is California *and* Canada, ``IN`` Indiana
    *and* India, ``DE`` Delaware *and* Germany) is resolved by the row's own
    country: with ``country='US'`` a 2-letter scope is a STATE, so the scope
    becomes ``us`` and ``region`` keeps the state. Only a country-less row reads
    a bare 2-letter token as an ISO-2 country code.
    """
    if kind != "remote":
        return None

    # canonical_country() returns an UNMAPPABLE value unchanged (by design -- it
    # never guesses), so canon_country is not necessarily an ISO-2 code. Feeding
    # that straight into the scope would put free text back into the "closed"
    # vocabulary and, because remote_scope is part of uq_locations_canonical,
    # would forge one NEW row per unmappable country spelling -- the exact
    # fragmentation this function exists to remove. Prod has rows that would hit
    # this: country='United States & Canada' (175 job links), 'Turkey' (29),
    # 'Canada/USA' (41). Only a real 2-letter code may become a scope.
    country_fallback = (
        canon_country.lower()
        if canon_country and _TWO_LETTER.match(canon_country.upper())
        else None
    )

    if raw is None:
        return country_fallback
    s = " ".join(str(raw).split()).strip().lower()
    if not s:
        return country_fallback

    # "Remote (US)" / "Remote (Philippines)" -- the model sometimes puts the
    # whole rendered label in the scope column. Unwrap and re-read it.
    wrapper = _REMOTE_WRAPPER.match(s)
    if wrapper:
        return canonical_remote_scope(
            wrapper.group("inner"), kind=kind, canon_country=canon_country
        )

    if s in _NON_GEOGRAPHIC_SCOPES:
        if country_fallback is None and canon_country:
            logger.warning(
                "canonical_remote_scope: scope %r carries no geography and country "
                "%r is not an ISO-2 code; dropping the scope to None",
                raw, canon_country,
            )
        return country_fallback
    if s in _MACRO_REGIONS:
        return s
    alias = _SCOPE_ALIASES.get(s)
    if alias:
        return alias

    # A US row's 2-letter scope is a state code, not a country code.
    if canon_country == "US" and _TWO_LETTER.match(s.upper()):
        return "us"

    mapped = canonical_country(s)
    if mapped and _TWO_LETTER.match(mapped.upper()):
        return mapped.lower()

    if country_fallback is not None:
        logger.warning(
            "canonical_remote_scope: unrecognised scope %r; falling back to country %r",
            raw, country_fallback,
        )
    else:
        logger.warning(
            "canonical_remote_scope: unrecognised scope %r and no country to fall back "
            "to; dropping to None", raw,
        )
    return country_fallback


# --- canonical_name (kind-aware) ---------------------------------------------

# ISO-2 -> display name, derived from _COUNTRY_NAME_TO_ISO2 rather than being a
# second hand-maintained map that could drift out of step with it. Dicts preserve
# insertion order, so the FIRST spelling listed for a code wins -- which is why
# the full names are listed before the aliases above ("UNITED STATES" before
# "USA", "UNITED KINGDOM" before "UK").
_ISO2_TO_DISPLAY: dict[str, str] = {}
for _name, _code in _COUNTRY_NAME_TO_ISO2.items():
    _ISO2_TO_DISPLAY.setdefault(_code, _name.title())

# .title() would render DC as "District Of Columbia" (capital "Of"), so the
# handful of names with lowercase particles are spelled out.
_STATE_NAME_OVERRIDES: dict[str, str] = {"DC": "District of Columbia"}

_USPS_TO_STATE_NAME: dict[str, str] = {
    _usps: _STATE_NAME_OVERRIDES.get(_usps, _state.title())
    for _state, _usps in _US_STATE_NAME_TO_USPS.items()
}

# How a macro-region token renders in a label. Anything not listed is uppercased.
_MACRO_REGION_LABELS: dict[str, str] = {"global": "Global"}


def _render_city_name(city: str | None, region: str | None, country: str | None) -> str:
    return ", ".join(part for part in (city, region, country) if part)


def _scope_label(remote_scope: str, region: str | None, country: str | None) -> str:
    """Render a remote scope for display inside ``Remote (...)``.

    * US row carrying a state -> ``AZ, US`` (the prompt's own example; the
      trailing ", US" is what disambiguates the 2-letter state code).
    * macro region -> ``EMEA`` / ``Global``.
    * country scope -> the country's DISPLAY NAME, not its code.

    The display name is load-bearing, not cosmetic: ISO-2 country codes collide
    with USPS state codes, so a bare ``Remote (CA)`` would mean Canada while
    ``Remote (CA, US)`` means California -- two labels one character apart
    meaning different continents.

    ``US`` is the one deliberate exception, kept as a code: it is the only
    country code that cannot be misread as a state (there is no state "US"), it
    is the majority of the corpus, and "Remote (US)" is what the Tier-2 prompt,
    the existing tests, and the dropdown all already say. Every other country
    renders as its display name, with the code as fallback when none is mapped.
    """
    # ORDER MATTERS. The macro-region check must come FIRST: a row can be
    # globally remote while still carrying a US region (an "anywhere, HQ in
    # California" answer gives region='CA', country='US', remote_scope='global').
    # Rendering the state first labelled that row "Remote (CA, US)" -- the stored
    # scope said global while the label the user filters on said California.
    # Silent meaning-narrowing, and the tests only covered remote_scope='us'.
    if remote_scope in _MACRO_REGIONS:
        return _MACRO_REGION_LABELS.get(remote_scope, remote_scope.upper())
    if country == "US" and region:
        return f"{region}, US"
    code = remote_scope.upper()
    if code == "US":
        return "US"
    return _ISO2_TO_DISPLAY.get(code, code)


def render_canonical_name(
    *,
    kind: str,
    city: str | None,
    region: str | None,
    country: str | None,
    remote_scope: str | None,
) -> str | None:
    """Derive the display label from the canonicalized structured columns.

    Returns ``None`` when there is not enough structure to build a label, in
    which case the caller keeps whatever the model supplied.

    Why this is now done for EVERY kind, not just ``city``: ``canonical_name``
    used to be the model's own prose for region/country/remote rows, so the same
    physical scope arrived under many labels while the uniqueness key
    (kind, city, region, country, remote_scope) also varied -- prod ended up with
    23 rows named "Remote (US)" and 14 named "Remote". Making the label a pure
    function of the tuple means one scope renders exactly one way. It is safe to
    change these labels because the eval scorer compares structured fields only
    (see api/eval/scoring.py) -- ``canonical_name`` is not part of the match.
    """
    if kind == "city":
        return _render_city_name(city, region, country) or None

    if kind == "country":
        if country:
            return _ISO2_TO_DISPLAY.get(country, country)
        return None

    if kind == "region":
        if region and country:
            label = _USPS_TO_STATE_NAME.get(region, region) if country == "US" else region
            return f"{label}, {country}"
        if region:
            return region
        if country:
            return _ISO2_TO_DISPLAY.get(country, country)
        return None

    if kind == "remote":
        if remote_scope:
            return f"Remote ({_scope_label(remote_scope, region, country)})"
        if country:
            return f"Remote ({_scope_label(country.lower(), region, country)})"
        return "Remote"

    return None


@dataclass(frozen=True)
class CanonicalParts:
    """The 6 persisted location columns after canonicalization."""

    canonical_name: str
    kind: str
    city: str | None
    region: str | None
    country: str | None
    remote_scope: str | None


def canonicalize_parts(
    *,
    kind: str,
    canonical_name: str,
    city: str | None,
    region: str | None,
    country: str | None,
    remote_scope: str | None,
) -> CanonicalParts:
    """Canonicalize the structured columns + (for cities) recompute the label.

    Pure and idempotent: ``canonicalize_parts(**canonicalize_parts(...))`` yields
    an equal result.
    """
    canon_country = canonical_country(country)
    canon_region = canonical_region(region, canon_country, kind)
    canon_scope = canonical_remote_scope(
        remote_scope, kind=kind, canon_country=canon_country
    )

    # The label is a pure function of the canonicalized tuple, so one physical
    # place renders exactly one way. Falls back to the model's own label only
    # when there is too little structure to build one.
    #
    # This is safe to derive unconditionally because canonical_region now only
    # drops a US region that RESTATES the country ('United States' -> None).
    # An unrecognised-but-real region ('Space Coast', 'Bay Area') is KEPT, so
    # deriving cannot silently promote a regional role to nationwide.
    name = render_canonical_name(
        kind=kind,
        city=city,
        region=canon_region,
        country=canon_country,
        remote_scope=canon_scope,
    ) or canonical_name

    return CanonicalParts(
        canonical_name=name,
        kind=kind,
        city=city,
        region=canon_region,
        country=canon_country,
        remote_scope=canon_scope,
    )


class _LocationLike(Protocol):
    """Structural type for anything ``canonicalize`` can read.

    A ``CanonicalLocation`` (LLM), a ``models.LocationSpec`` (admin), and the
    backfill's row wrapper all satisfy this — they expose the same 6 attributes.
    Declaring it as a Protocol makes a caller passing the wrong shape a
    type error rather than a runtime ``AttributeError``.

    Members are read-only properties (covariant) so a model whose ``kind`` is a
    narrower ``Literal`` (e.g. ``models.LocationSpec``) still matches ``str``.
    """

    @property
    def kind(self) -> str: ...
    @property
    def canonical_name(self) -> str: ...
    @property
    def city(self) -> str | None: ...
    @property
    def region(self) -> str | None: ...
    @property
    def country(self) -> str | None: ...
    @property
    def remote_scope(self) -> str | None: ...


def canonicalize(loc: _LocationLike) -> CanonicalParts:
    """Canonicalize any object exposing the 6 location attributes.

    Accepts a ``CanonicalLocation`` (LLM), a ``models.LocationSpec`` (admin), or
    any object/row wrapper with ``.canonical_name/.kind/.city/.region/.country/
    .remote_scope`` (the backfill). ``confidence`` (if present) is ignored.
    """
    return canonicalize_parts(
        kind=loc.kind,
        canonical_name=loc.canonical_name,
        city=loc.city,
        region=loc.region,
        country=loc.country,
        remote_scope=loc.remote_scope,
    )
