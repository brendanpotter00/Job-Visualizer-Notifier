"""Curated golden cases for the location-normalization eval.

Hand-written edge cases that stress the Tier-2 prompt (``llm_client.SYSTEM_PROMPT``
+ ``FEW_SHOT_GUIDE``). Each case is a dict:

    {
        "id":       stable slug (used in the report + baseline diffing),
        "raw":      the input string sent to the model,
        "category": grouping for the per-category accuracy breakdown,
        "expected": ordered list of expected locations (only the 5 compared
                    fields matter: kind/city/region/country/remote_scope),
        "gating":   True  -> counts toward the headline gating accuracy,
                    False -> reported but NOT pass/fail (ambiguous by design),
        "notes":    why the case exists / why it's non-gating,
        "expect_below_floor": (optional) True for inputs designed to come back
                    below CONFIDENCE_FLOOR — checked via the confidence report.
    }

Rules:
* Do NOT reuse the model's few-shot inputs verbatim (memorized examples are
  worthless): "San Francisco, CA"; "Sunnyvale, CA, USA; Kirkland, WA, USA";
  "Remote - United States"; "Remote"; "US - AZ - Remote".
* Region/country-scoped remotes and other genuinely-ambiguous shapes are
  ``gating: False`` (per the eval design decision) — the schema must REPRESENT
  them (verified by unit tests), but the headline number stays clean.
"""

from __future__ import annotations


# --- compact builders for the 5 compared fields ------------------------------

def _city(city, region, country="US"):
    return {"kind": "city", "city": city, "region": region, "country": country, "remote_scope": None}


def _region(region, country="US"):
    return {"kind": "region", "city": None, "region": region, "country": country, "remote_scope": None}


def _country(country):
    return {"kind": "country", "city": None, "region": None, "country": country, "remote_scope": None}


def _remote(scope, region=None, country=None):
    return {"kind": "remote", "city": None, "region": region, "country": country, "remote_scope": scope}


CURATED_CASES: list[dict] = [
    # ---- simple city (gating) ----
    {"id": "simple-austin", "raw": "Austin, Texas", "category": "simple",
     "expected": [_city("Austin", "TX")], "gating": True, "notes": "full state name -> code"},
    {"id": "simple-boston", "raw": "Boston, MA", "category": "simple",
     "expected": [_city("Boston", "MA")], "gating": True},
    {"id": "simple-seattle", "raw": "Seattle, Washington", "category": "simple",
     "expected": [_city("Seattle", "WA")], "gating": True},
    {"id": "simple-chicago-bare", "raw": "Chicago", "category": "simple",
     "expected": [_city("Chicago", "IL")], "gating": True, "notes": "infer region/country from a famous city"},
    {"id": "verbose-austin-us", "raw": "Austin, Texas, United States", "category": "simple",
     "expected": [_city("Austin", "TX")], "gating": True,
     "notes": "verbose full-name form -> concise codes; prod-confirmed (user-flagged dropdown variant)"},

    # ---- reversed order (gating; very common in prod) ----
    {"id": "reversed-redmond", "raw": "United States, Washington, Redmond", "category": "reversed",
     "expected": [_city("Redmond", "WA")], "gating": True, "notes": "Microsoft order; 1812 prod rows"},
    {"id": "reversed-santa-clara", "raw": "US, CA, Santa Clara", "category": "reversed",
     "expected": [_city("Santa Clara", "CA")], "gating": True, "notes": "reversed w/ codes; 600 prod rows"},
    {"id": "reversed-dash-sf", "raw": "USA - California - San Francisco", "category": "reversed",
     "expected": [_city("San Francisco", "CA")], "gating": True, "notes": "reversed, dash-delimited"},

    # ---- multi-location via ';' (gating; the only prod-common delimiter, 182 distinct) ----
    {"id": "multi-raleigh-durham", "raw": "Raleigh, NC, USA; Durham, NC, USA", "category": "multi",
     "expected": [_city("Raleigh", "NC"), _city("Durham", "NC")], "gating": True},
    {"id": "multi-mtv-austin", "raw": "Mountain View, CA, USA; Austin, TX, USA", "category": "multi",
     "expected": [_city("Mountain View", "CA"), _city("Austin", "TX")], "gating": True},
    {"id": "multi-austin-atlanta", "raw": "Austin, TX, USA; Atlanta, GA, USA", "category": "multi",
     "expected": [_city("Austin", "TX"), _city("Atlanta", "GA")], "gating": True,
     "notes": "user-flagged: appeared as ONE dropdown option; must split into two city tags"},

    # ---- multi-location synthetic delimiters (robustness; '/' and 'or' ~absent in prod) ----
    {"id": "multi-slash", "raw": "Bellevue, WA / Seattle, WA", "category": "multi",
     "expected": [_city("Bellevue", "WA"), _city("Seattle", "WA")], "gating": True,
     "notes": "SYNTHETIC: '/' appears in ~1 distinct prod string"},
    {"id": "multi-or", "raw": "New York or Boston", "category": "multi",
     "expected": [_city("New York", "NY"), _city("Boston", "MA")], "gating": False,
     "notes": "SYNTHETIC + region inference ('New York' city/region) -> non-gating"},
    {"id": "multi-newline", "raw": "Denver, CO\nPhoenix, AZ", "category": "multi",
     "expected": [_city("Denver", "CO"), _city("Phoenix", "AZ")], "gating": True,
     "notes": "newline-delimited multi"},

    # ---- remote, clearly global (gating) ----
    {"id": "remote-worldwide", "raw": "Fully remote, worldwide", "category": "remote",
     "expected": [_remote("global")], "gating": True},
    {"id": "remote-anywhere", "raw": "Remote (Anywhere)", "category": "remote",
     "expected": [_remote("global")], "gating": True},
    {"id": "remote-wfh", "raw": "Work from home", "category": "remote",
     "expected": [_remote("global")], "gating": False,
     "notes": "WFH may map to global remote or be unscoped -> non-gating"},

    # ---- remote, region/country-scoped (NON-gating per design; schema must allow) ----
    {"id": "remote-co", "raw": "US - CO - Remote", "category": "remote_scoped",
     "expected": [_remote("us", region="CO", country="US")], "gating": False,
     "notes": "schema fix: region/country scope preserved; scope label ambiguous"},
    {"id": "remote-montana", "raw": "Remote - Montana", "category": "remote_scoped",
     "expected": [_remote("us", region="MT", country="US")], "gating": False},
    {"id": "remote-brazil", "raw": "BR - Brazil - Remote", "category": "remote_scoped",
     "expected": [_remote("br", country="BR")], "gating": False},
    {"id": "remote-us-only", "raw": "Remote (US only)", "category": "remote_scoped",
     "expected": [_remote("us", country="US")], "gating": False},
    {"id": "remote-emea", "raw": "Remote - EMEA", "category": "remote_scoped",
     "expected": [_remote("eu")], "gating": False, "notes": "EMEA != EU exactly -> non-gating"},

    # ---- building/site codes & parentheticals to strip (gating) ----
    {"id": "paren-hq", "raw": "Costa Mesa, CA (HQ)", "category": "parenthetical",
     "expected": [_city("Costa Mesa", "CA")], "gating": True, "notes": "strip '(HQ)'; 1502 prod rows"},
    {"id": "building-reston", "raw": "Reston, VA (NOVA-01)", "category": "parenthetical",
     "expected": [_city("Reston", "VA")], "gating": True, "notes": "strip site code"},
    {"id": "building-ashville", "raw": "Ashville, OH (Arsenal 1)", "category": "parenthetical",
     "expected": [_city("Ashville", "OH")], "gating": True},
    {"id": "building-atlanta-atl01", "raw": "Atlanta, GA (ATL-01)", "category": "parenthetical",
     "expected": [_city("Atlanta", "GA")], "gating": True, "notes": "strip office code; user-flagged dropdown variant"},
    {"id": "building-austin-dash", "raw": "Austin - 5323", "category": "parenthetical",
     "expected": [_city("Austin", "TX")], "gating": True,
     "notes": "bare city + dash site-number; strip code + infer TX; prod-confirmed (user-flagged)"},
    {"id": "building-mtv-code", "raw": "Mountain View (US-MTV-EMF680)", "category": "parenthetical",
     "expected": [_city("Mountain View", "CA")], "gating": True, "notes": "Workday building code; infer CA/US"},
    {"id": "street-chandler", "raw": "Chandler - 300 N 56th St", "category": "parenthetical",
     "expected": [_city("Chandler", "AZ")], "gating": False, "notes": "strip street addr + region inference -> non-gating"},

    # ---- region-only (gating) ----
    {"id": "region-california", "raw": "California", "category": "region",
     "expected": [_region("CA")], "gating": True},
    {"id": "region-california-named", "raw": "California, United States", "category": "region",
     "expected": [_region("CA")], "gating": True, "notes": "714 prod rows"},
    {"id": "region-texas-named", "raw": "Texas, United States", "category": "region",
     "expected": [_region("TX")], "gating": True},

    # ---- country-only (gating) ----
    {"id": "country-japan", "raw": "Japan", "category": "country",
     "expected": [_country("JP")], "gating": True},
    {"id": "country-singapore", "raw": "Singapore", "category": "country",
     "expected": [_country("SG")], "gating": True, "notes": "274 prod rows"},
    {"id": "country-us-bare", "raw": "United States", "category": "country",
     "expected": [_country("US")], "gating": True, "notes": "348 prod rows"},

    # ---- macro-region code with a firm product mapping (gating) ----
    {"id": "macro-amer", "raw": "AMER", "category": "macro_region",
     "expected": [_country("US")], "gating": True,
     "notes": "product decision: 'AMER' (Americas hiring region; Vercel/Supabase "
              "use it) normalizes to US. Enforced by a SYSTEM_PROMPT rule, NOT a "
              "few-shot input, so this case still tests rule-following not "
              "memorization. Gating (unlike the ambiguous EMEA/APAC region codes) "
              "because the mapping is a deliberate, fixed product choice."},

    # ---- accents (NON-gating; checks the model doesn't choke / how it renders diacritics) ----
    {"id": "accent-zurich", "raw": "Zürich, Switzerland", "category": "accents",
     "expected": [_city("Zürich", None, "CH")], "gating": False, "notes": "verify diacritics handling in output"},
    {"id": "accent-saopaulo", "raw": "São Paulo, Brazil", "category": "accents",
     "expected": [_city("São Paulo", None, "BR")], "gating": False},

    # ---- misspelling (NON-gating; does the model correct it?) ----
    {"id": "misspell-cincinnati", "raw": "Cincinatti, OH", "category": "misspelling",
     "expected": [_city("Cincinnati", "OH")], "gating": False, "notes": "input misspelled; does model fix it?"},
    {"id": "country-code-gbr", "raw": "Farnborough, GBR", "category": "misspelling",
     "expected": [_city("Farnborough", None, "GB")], "gating": False, "notes": "3-letter country code GBR -> GB"},

    # ---- international canonical consistency (NON-gating; intl is inherently
    #      flaky run-to-run). These assert the MODEL's output; the deterministic
    #      post-LLM canonicalize() pass (services/location_canonicalize.py) is the
    #      real guarantee and is covered by tests/test_location_canonicalize.py.
    #      Promote to gating only after --repeat 3 shows 3/3 stability. ----
    {"id": "intl-berlin", "raw": "Berlin, Germany", "category": "intl_canonical",
     "expected": [_city("Berlin", None, "DE")], "gating": False,
     "notes": "country full-name -> DE; region omitted for non-US"},
    {"id": "intl-london-uk", "raw": "London, United Kingdom", "category": "intl_canonical",
     "expected": [_city("London", None, "GB")], "gating": False,
     "notes": "UK -> GB (scorer alias bridges); region omitted"},
    {"id": "intl-bangalore", "raw": "Bangalore, India", "category": "intl_canonical",
     "expected": [_city("Bangalore", None, "IN")], "gating": False},
    {"id": "intl-amsterdam", "raw": "Amsterdam, Netherlands", "category": "intl_canonical",
     "expected": [_city("Amsterdam", None, "NL")], "gating": False},
    {"id": "country-brazil-name", "raw": "Brazil", "category": "intl_canonical",
     "expected": [_country("BR")], "gating": False, "notes": "full country name -> BR"},
    {"id": "country-sweden-name", "raw": "Sweden", "category": "intl_canonical",
     "expected": [_country("SE")], "gating": False, "notes": "full country name -> SE"},

    # ---- ambiguous (NON-gating) ----
    {"id": "ambiguous-multiple-loc", "raw": "United States, Multiple Locations, Multiple Locations",
     "category": "ambiguous", "expected": [_country("US")], "gating": False, "notes": "550 prod rows; not a real place"},
    {"id": "ambiguous-greater-seattle", "raw": "Greater Seattle Area", "category": "ambiguous",
     "expected": [_city("Seattle", "WA")], "gating": False, "notes": "metro area, 334 prod rows"},
    {"id": "ambiguous-emea-bare", "raw": "EMEA", "category": "ambiguous",
     "expected": [_region("EMEA", None)], "gating": False},

    # ---- low-confidence by design (NON-gating; asserted via the confidence flag) ----
    {"id": "lowconf-various", "raw": "Various", "category": "low_confidence",
     "expected": [], "gating": False, "expect_below_floor": True, "notes": "vague -> expect confidence < 0.5"},
    {"id": "lowconf-tbd", "raw": "TBD", "category": "low_confidence",
     "expected": [], "gating": False, "expect_below_floor": True},
]
