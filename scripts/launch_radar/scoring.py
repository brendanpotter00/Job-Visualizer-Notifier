"""Deterministic scoring (CONTRACT §6.6).

The rubric data and the point values are copied verbatim from the POC
(``poc.py``). Two changes: the talent score is ``None`` (shown as a dash)
when no leader has any people data, never 0; and the VC score is ``None`` when
the brief is missing or names no investor and no parseable amount. Reasons are
written for a person reading the card.

Talent is a 50/50 blend (``talent_scores``): up to 50 points from the leaders
(``score_talent``'s 0-94, rescaled) plus up to 50 from the rest of the team (the
``team_stats`` tally, ``score_team``). A part with no data is missing, never 0:
when only one part is known it is doubled, and when neither is, Talent is None.

Inputs come from Parallel outputs and are untrusted: they are only ever matched
against these fixed name lists, never evaluated.
"""

from __future__ import annotations

import math
import re
from fractions import Fraction
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


# ---- the 50/50 talent blend -------------------------------------------------------------
PART_MAX = 50  # each part of the blend: the leaders and the team
LEADERS_MAX = sum(spec["cap"] for spec in TALENT_RUBRIC.values())  # score_talent's ceiling (94)
# The team's half is schools + employers only. Prior exits are a leaders' signal (``score_talent``):
# the team tally no longer asks for them, and an old card's ``ex_founders_with_exit`` is ignored.
TEAM_SCHOOL_POINTS = 25
TEAM_EMPLOYER_POINTS = 25
TEAM_FULL_SHARE = Fraction(1, 2)  # full school / employer points at a share of one half (see score_team)
TEAM_FULL_SAMPLE = 5  # fewer profiles count proportionally (3 of 5 = 60%); the rest follows the leaders
TALENT_BASES = ("leaders", "team", "both")
TALENT_KEYS = ("talent", "talent_leaders", "talent_team", "talent_basis", "talent_reasons", "talent_team_reasons")


def half_up(x: float | Fraction) -> int:
    """Round half up (``round`` is banker's rounding: 12.5 -> 12, which no reader could explain)."""
    return math.floor(x + Fraction(1, 2))


def leaders_part(leaders_raw: int | None) -> int | None:
    """``score_talent``'s 0-94 rescaled to the leaders' 0-50 half of the blend."""
    return None if leaders_raw is None else half_up(Fraction(leaders_raw * PART_MAX, LEADERS_MAX))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _tally(v: Any) -> list[tuple[str, int]]:
    """``[(name, count)]`` from a stored tally; anything malformed is dropped."""
    out = []
    for item in v if isinstance(v, list) else []:
        if not isinstance(item, dict):
            continue
        name, count = item.get("name"), item.get("count")
        if isinstance(name, str) and isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            out.append((name, count))
    return out


def _count(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _side_line(noun: str, hits: int, listed: int, profiles: str, pts: int) -> str:
    """``15 of the 48 schools listed across 33 profiles are top schools (+9)``: what was counted, said plainly."""
    if listed == 1:
        return (f"the 1 {noun} listed across {profiles} is a top {noun} (+{pts})" if hits
                else f"the 1 {noun} listed across {profiles} is not a top {noun}")
    where = f"the {listed} {noun}s listed across {profiles}"
    if not hits:
        return f"none of {where} is a top {noun}"
    return f"{hits} of {where} " + (f"is a top {noun}" if hits == 1 else f"are top {noun}s") + f" (+{pts})"


def score_team(team_stats: dict[str, Any] | None, leaders: int | None = None) -> tuple[int | None, list[str]]:
    """The team's 0-50 half of Talent from the card's ``team_stats`` tally.

    Shares, not headcount. The tally lists schools and employers, not people (one person
    can list two schools), so a side's share is its top-list entries over
    ``max(profiles found, entries listed on that side)``: double counting cannot inflate it,
    and profiles with nothing listed still count when the list is short. Schools 25 and
    employers 25, full points at a share of one half. Prior exits are not part of it (they
    are a leaders' signal); an old tally's ``ex_founders_with_exit`` is ignored. Each side is
    rounded once and the part is the sum of the shown integers, so the reason lines add up.

    Missing data is not 0. A side with nothing listed is missing: the other side is scaled
    up to the full 50. Fewer than 5 profiles count proportionally and the
    rest of the part follows ``leaders`` (the leaders' 0-50 part), so as the sample goes to
    0 the card tends to the leaders-only card; with no leaders' part the rest is 0. The tally
    is weighted 1.0: the pipeline does not keep its confidence. None when there is no tally,
    no profile was found, or the tally lists no school and no employer at all.
    """
    if not isinstance(team_stats, dict):
        return None, ["no team tally on this card"]
    n = _count(team_stats.get("profiles_found"))
    if not n:
        return None, ["no public profiles found for the rest of the team"]
    sides = [(tally, key, points, noun)
             for tally, key, points, noun in (
                 (_tally(team_stats.get("schools")), "top_school", TEAM_SCHOOL_POINTS, "school"),
                 (_tally(team_stats.get("prior_employers")), "top_employer", TEAM_EMPLOYER_POINTS, "employer"))
             if sum(c for _, c in tally)]
    if not sides:
        return None, ["the team tally lists no schools or employers"]
    # Both sides listed: 25 + 25 = 50 and the scale is 1. One side missing: that side is scaled up to 50.
    scale = Fraction(PART_MAX, sum(points for _, _, points, _ in sides))
    reasons: list[str] = []
    raw = 0
    profiles = _plural(n, "profile")
    for tally, key, points, noun in sides:
        listed = sum(c for _, c in tally)
        hits = sum(c for name, c in tally if _match_any(name, TALENT_RUBRIC[key]["names"]))
        share = Fraction(hits, max(n, listed))
        pts = half_up(points * scale * min(Fraction(1), share / TEAM_FULL_SHARE))
        raw += pts
        reasons.append(_side_line(noun, hits, listed, profiles, pts))
    if len(sides) == 1:
        present = sides[0][3]
        missing = "employer" if present == "school" else "school"
        reasons.append(f"no {missing} data listed: {present}s are scaled to 50")
    if n >= TEAM_FULL_SAMPLE:
        return raw, reasons
    shrink = Fraction(n, TEAM_FULL_SAMPLE)
    pct = half_up(shrink * 100)
    if leaders is None:
        reasons.append(f"only {profiles} found: counts at {pct}%")
        return half_up(shrink * raw), reasons
    reasons.append(f"only {profiles} found: counts at {pct}%, the other {100 - pct}% follows the leaders' part ({leaders})")
    return half_up(shrink * raw + (1 - shrink) * leaders), reasons


def blend_talent(leaders: int | None, team: int | None) -> tuple[int | None, str | None]:
    """``(talent, talent_basis)``: the sum of both parts, or a lone part doubled (missing data
    is not evidence of a weak team, so it is never scored as 0), or ``(None, None)``.

    A doubled part is rounded before it is doubled, so a leaders-only card can sit 1 above
    the direct rescale (raw 48: ``2 * half_up(48 * 50 / 94)`` = 52, ``48 * 100 / 94`` = 51.06).
    Accepted: it keeps the stored invariant ``talent == 2 * part`` the backend validates."""
    if leaders is not None and team is not None:
        return leaders + team, "both"
    if leaders is not None:
        return 2 * leaders, "leaders"
    if team is not None:
        return 2 * team, "team"
    return None, None


def _talent_fields(leaders: int | None, talent_reasons: list[str], team_stats: Any) -> dict[str, Any]:
    team, team_reasons = score_team(team_stats, leaders)
    talent, basis = blend_talent(leaders, team)
    return {"talent": talent, "talent_leaders": leaders, "talent_team": team, "talent_basis": basis,
            "talent_reasons": talent_reasons, "talent_team_reasons": team_reasons}


def talent_scores(leader_inputs: list[dict[str, Any]], team_stats: dict[str, Any] | None) -> dict[str, Any]:
    """The six talent fields of a card's ``scores`` (``TALENT_KEYS``)."""
    leaders_raw, reasons = score_talent(leader_inputs)
    return _talent_fields(leaders_part(leaders_raw), reasons, team_stats)


def funding_brief(funding: Any) -> dict[str, Any] | None:
    """A stored card's ``funding`` block in the shape ``score_vc`` reads (a brief's rounds)."""
    if not isinstance(funding, dict):
        return None
    prior = []
    for rnd in funding.get("prior_rounds") or []:
        if isinstance(rnd, dict):
            names = [x for x in (rnd.get("lead_investors") or []) + (rnd.get("other_investors") or [])
                     if isinstance(x, str)]
            prior.append({"investors": ", ".join(names)})
    return {"latest_round": funding.get("latest_round"), "prior_rounds": prior}


def rescored_scores(payload: dict[str, Any]) -> dict[str, Any]:
    """A stored card's ``scores`` recomputed from what the card itself stores (no Parallel call).

    The leaders' part is carried, not recomputed: the card does not keep the pedigree
    confidence ``score_talent`` weighs by, and a rescore never changes leader inputs. A
    blended card carries ``talent_leaders``; a legacy card (no ``talent_basis``) stored
    ``score_talent``'s raw 0-94 as ``talent``, which is rescaled exactly. The team part
    is scored from ``team_stats`` and the VC score from ``funding``.
    """
    old = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
    if old.get("talent_basis") in TALENT_BASES:
        leaders = _count(old.get("talent_leaders"))
    else:
        leaders = leaders_part(_count(old.get("talent")))
    talent_reasons = [r for r in old.get("talent_reasons") or [] if isinstance(r, str)]
    vc, vc_reasons = score_vc(funding_brief(payload.get("funding")))
    return {**_talent_fields(leaders, talent_reasons, payload.get("team_stats")), "vc": vc, "vc_reasons": vc_reasons}
