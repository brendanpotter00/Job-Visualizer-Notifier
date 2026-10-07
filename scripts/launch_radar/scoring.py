"""Deterministic scoring (CONTRACT §6.6).

The rubric data and the point values are copied verbatim from the POC
(``poc.py:570``). Two changes: the talent score is ``None`` (shown as a dash)
when no leader has any people data, never 0; and the VC score is ``None`` when
the brief is missing or names no investor and no parseable amount. Reasons are
written for a person reading the card.

Inputs come from Parallel outputs and are untrusted: they are only ever matched
against these fixed name lists, never evaluated.
"""

from __future__ import annotations

import re
from typing import Any

# ---- scoring rubric (data, verbatim from the POC) ----------------------------
VC_TIERS: dict[str, dict[str, Any]] = {
    "tier1": {
        "lead_points": 60, "participant_points": 45, "extra_points": 10, "extra_cap": 30,
        "names": [
            "Sequoia", "Andreessen Horowitz", "a16z", "Benchmark", "Founders Fund", "Greylock", "Accel",
            "Index Ventures", "Lightspeed", "Kleiner Perkins", "General Catalyst", "Thrive Capital",
            "Khosla Ventures", "Insight Partners", "Coatue", "Tiger Global", "IVP", "Bessemer", "GV",
            "Google Ventures", "Redpoint", "NEA", "New Enterprise Associates", "Conviction", "Kleiner",
        ],
    },
    "tier2": {
        "lead_points": 35, "participant_points": 25, "extra_points": 5, "extra_cap": 15,
        "names": [
            "Felicis", "Initialized", "SV Angel", "First Round", "Craft Ventures", "CRV", "Spark Capital",
            "Menlo Ventures", "Amplify Partners", "Elad Gil", "Nat Friedman", "Daniel Gross", "Box Group",
            "BoxGroup", "Neo", "South Park Commons", "Pear VC", "Abstract Ventures", "Lux Capital",
            "Madrona", "Battery Ventures", "Sapphire", "8VC", "Lerer Hippeau", "Upfront", "Floodgate",
            "Matrix", "Emergence", "Unusual Ventures", "Basis Set", "Gradient", "M12", "NVentures",
            "Salesforce Ventures", "Mayfield", "Costanoa", "Haystack", "XYZ Venture",
        ],
    },
    "yc": {
        "lead_points": 15, "participant_points": 15, "extra_points": 0, "extra_cap": 0,
        "names": ["Y Combinator", "YC"],
    },
}
VC_AMOUNT_BONUS = [(50_000_000, 15), (20_000_000, 10), (10_000_000, 5)]
VC_OTHER_NAMED_POINTS = 10

TALENT_RUBRIC: dict[str, dict[str, Any]] = {
    "top_school": {"points": 8, "cap": 24, "names": [
        "Stanford", "(?-i:MIT)", "Massachusetts Institute of Technology", "Harvard", "Berkeley",
        "Carnegie Mellon", "(?-i:CMU)", "Caltech", "California Institute of Technology", "Princeton", "Yale",
        "Columbia", "Cornell", "University of Pennsylvania", "Wharton", "Oxford", "Cambridge", "ETH Zurich",
        "(?-i:IIT)", "Indian Institute of Technology", "University of Toronto", "Waterloo", "Georgia Tech",
        "Georgia Institute of Technology", "(?-i:UIUC)", "Illinois Urbana", "University of Washington",
        "Tsinghua", "Peking University", "Imperial College", "(?-i:UCLA)", "University of Michigan",
    ]},
    "top_employer": {"points": 10, "cap": 30, "names": [
        "OpenAI", "Anthropic", "DeepMind", "Google", "Meta", "Facebook", "Apple", "Stripe", "SpaceX", "Tesla",
        "Microsoft", "Amazon", "(?-i:AWS)", "Nvidia", "Airbnb", "Uber", "Palantir", "Databricks", "Netflix",
        "Scale AI", "Figma", "Coinbase", "Jane Street", "Two Sigma", "Citadel", "Snowflake", "Datadog",
        "Ramp", "Plaid", "Robinhood", "LinkedIn", "Twitter", "Dropbox", "Instacart", "DoorDash", "Brex",
    ]},
    "prior_exit": {"points": 15, "cap": 30},
    "senior_experience": {"points": 5, "cap": 10, "min_years": 10},
}
CONFIDENCE_WEIGHT: dict[str | None, float] = {"high": 1.0, "medium": 0.8, "low": 0.5, None: 0.8}


def _rx(names: list[str]) -> list[tuple[str, re.Pattern]]:
    out = []
    for n in names:
        label = re.sub(r"^\(\?-i:(.*)\)$", r"\1", n)
        out.append((label, re.compile(r"(?<![A-Za-z0-9])" + n + r"(?![A-Za-z0-9])", re.I)))
    return out


def _match_any(text: str, names: list[str]) -> list[str]:
    return [label for label, rx in _rx(names) if rx.search(text or "")]


def parse_usd(s: Any) -> float | None:
    if not s or not isinstance(s, str):
        return None
    m = re.search(r"([\d,.]+)\s*(billion|million|thousand|bn|[bmk])?\b", s.replace("$", ""), re.I)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    mult = {"b": 1e9, "bn": 1e9, "billion": 1e9, "m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}.get(unit, 1)
    return v * mult


# ---- VC score ------------------------------------------------------------------
_TIER_LABEL = {"tier1": "tier 1", "tier2": "tier 2"}


def _vc_name(tier: str, label: str) -> str:
    return "Y Combinator" if tier == "yc" else label


def score_vc(brief: dict[str, Any] | None) -> tuple[int | None, list[str]]:
    """Points exactly as POC ``score_vc``; None when there is nothing to score."""
    if not brief:
        return None, []
    lr = brief.get("latest_round") or {}
    if not isinstance(lr, dict):
        lr = {}
    leads = [x for x in (lr.get("lead_investors") or []) if isinstance(x, str) and x.strip()]
    others = [x for x in (lr.get("other_investors") or []) if isinstance(x, str) and x.strip()]
    for pr in brief.get("prior_rounds") or []:
        if isinstance(pr, dict) and isinstance(pr.get("investors"), str):
            others += [x.strip() for x in pr["investors"].split(",") if x.strip()]
    amt = parse_usd(lr.get("amount_usd"))
    if not leads and not others and not amt:
        return None, []

    reasons: list[str] = []
    best = 0
    extra = 0.0
    for tier, spec in VC_TIERS.items():
        lead_hits = {h for inv in leads for h in _match_any(inv, spec["names"])}
        part_hits = {h for inv in others for h in _match_any(inv, spec["names"])} - lead_hits
        lead_names = sorted({_vc_name(tier, h) for h in lead_hits})
        part_names = sorted({_vc_name(tier, h) for h in part_hits} - set(lead_names))
        suffix = f" ({_TIER_LABEL[tier]})" if tier in _TIER_LABEL else ""
        if lead_hits:
            best = max(best, spec["lead_points"])
            reasons += [f"{n} led{suffix}" for n in lead_names]
        if part_hits:
            best = max(best, spec["participant_points"])
            reasons += [f"{n} joined{suffix}" for n in part_names]
        n = len(lead_hits | part_hits)
        if n > 1 and spec["extra_points"]:
            add = min(spec["extra_cap"], spec["extra_points"] * (n - 1))
            extra += add
            reasons.append(f"+{n - 1} more {_TIER_LABEL[tier].replace(' ', '-')} investors")
    if best == 0 and (leads or others):
        best = VC_OTHER_NAMED_POINTS
        reasons.append("named investors, none tiered")
    for threshold, pts in VC_AMOUNT_BONUS:
        if amt and amt >= threshold:
            extra += pts
            reasons.append(f"round over ${threshold / 1e6:.0f}M")
            break
    return int(min(100, round(best + extra))), reasons


# ---- talent score ----------------------------------------------------------------
def _weight(conf: dict[str, Any], field: str) -> float:
    return CONFIDENCE_WEIGHT.get(conf.get(field), CONFIDENCE_WEIGHT[None])


def _exit_label(f: dict[str, Any]) -> str:
    outcome = f.get("outcome")
    if outcome == "ipo":
        return f"{f.get('company')}, IPO"
    return f"{f.get('company')}, acquired" + (f" by {f['acquirer']}" if f.get("acquirer") else "")


def has_people_data(leader: dict[str, Any]) -> bool:
    return bool(leader.get("schools") or leader.get("prior_companies") or leader.get("founded_raw")
                or leader.get("years") is not None)


def score_talent(leaders: list[dict[str, Any]]) -> tuple[int | None, list[str]]:
    """Points exactly as POC ``score_talent``; None when no leader has people data.

    Each leader is ``{name, schools: [str], prior_companies: [str],
    founded_raw: [{company, outcome, acquirer, exit_year}], years: int | None,
    confidence: {field: "high" | "medium" | "low" | None}}``. Founding a company
    scores nothing on its own; only an exit (``acquired`` or ``ipo``) counts.
    """
    if not any(has_people_data(ld) for ld in leaders):
        return None, []
    reasons: list[str] = []
    weights_used: set[float] = set()
    totals = {k: 0.0 for k in TALENT_RUBRIC}
    for ld in leaders:
        conf = ld.get("confidence") or {}
        name = ld["name"]
        sh = _match_any(" | ".join(ld.get("schools") or []), TALENT_RUBRIC["top_school"]["names"])
        if sh:
            w = _weight(conf, "education")
            weights_used.add(w)
            totals["top_school"] += TALENT_RUBRIC["top_school"]["points"] * w
            reasons.append(f"{name}: top school ({', '.join(sh)})")
        eh = _match_any(" | ".join(ld.get("prior_companies") or []), TALENT_RUBRIC["top_employer"]["names"])
        if eh:
            w = _weight(conf, "prior_roles")
            weights_used.add(w)
            totals["top_employer"] += TALENT_RUBRIC["top_employer"]["points"] * w
            reasons.append(f"{name}: top employer ({', '.join(sorted(set(eh)))})")
        exits = [f for f in ld.get("founded_raw") or [] if f.get("outcome") in ("acquired", "ipo")]
        if exits:
            w = _weight(conf, "founded_before")
            weights_used.add(w)
            totals["prior_exit"] += TALENT_RUBRIC["prior_exit"]["points"] * w
            reasons.append(f"{name}: prior exit ({'; '.join(_exit_label(f) for f in exits)})")
        yrs = ld.get("years")
        min_years = TALENT_RUBRIC["senior_experience"]["min_years"]
        if isinstance(yrs, int) and yrs >= min_years:
            w = _weight(conf, "years_experience")
            weights_used.add(w)
            totals["senior_experience"] += TALENT_RUBRIC["senior_experience"]["points"] * w
            reasons.append(f"{name}: {min_years}+ years")
    total = 0.0
    labels = {"top_school": "top schools", "top_employer": "top employers", "prior_exit": "prior exits",
              "senior_experience": "experience"}
    for k, v in totals.items():
        capped = min(v, TALENT_RUBRIC[k]["cap"])
        total += capped
        if v > capped:
            reasons.append(f"{labels[k]} capped at {TALENT_RUBRIC[k]['cap']}")
    if CONFIDENCE_WEIGHT["medium"] in weights_used:
        reasons.append("medium-confidence facts count at 80%")
    if CONFIDENCE_WEIGHT["low"] in weights_used:
        reasons.append("low-confidence facts count at 50%")
    return int(min(100, round(total))), reasons
