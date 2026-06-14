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
* region -> for US, USPS 2-letter (full state names mapped); for any other
  country, dropped to ``None`` (no reliable intl subdivision map, and the eval
  scorer does not alias region names). ``region == country`` is collapsed to
  ``None``. A ``kind='region'`` row with no country (macro-regions like ``EMEA``)
  is left untouched.
* canonical_name -> recomputed deterministically ONLY for ``kind='city'`` (the
  322-row fragmentation source). For region/country/remote the human label is
  preserved and only the structured code columns are fixed, so eval-locked labels
  ("United States", "Remote (US)") never churn.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

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

    * US country  -> USPS 2-letter (full state name mapped; unknown left + logged).
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
            region = up
        else:
            mapped = _US_STATE_NAME_TO_USPS.get(up)
            if mapped:
                region = mapped
            else:
                logger.warning("canonical_region: unknown US region %r left unchanged", raw)
                region = raw
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


# --- canonical_name (kind-aware) ---------------------------------------------

def _render_city_name(city: str | None, region: str | None, country: str | None) -> str:
    return ", ".join(part for part in (city, region, country) if part)


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

    if kind == "city" and city:
        name = _render_city_name(city, canon_region, canon_country)
    else:
        # Preserve human label for region/country/remote (eval-locked); only the
        # structured codes above were corrected.
        name = canonical_name

    return CanonicalParts(
        canonical_name=name,
        kind=kind,
        city=city,
        region=canon_region,
        country=canon_country,
        remote_scope=remote_scope,
    )


def canonicalize(loc) -> CanonicalParts:
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
