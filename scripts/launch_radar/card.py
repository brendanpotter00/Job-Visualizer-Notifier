"""Build the card payload the loop POSTs (CONTRACT §4, snake_case).

Everything here comes from Parallel outputs or web pages, so it is untrusted:
only known keys are copied, strings are type-checked and clipped, URLs must be
http(s), and every count is cast to an int (Task outputs can return integers
as floats, e.g. ``6.0``).
"""

from __future__ import annotations

import math
import re
from typing import Any

from .ats import pr_ready, safe_http_url
from .scoring import score_talent, score_vc

MAX_SOURCES = 40
MAX_FACTS = 6
MAX_SIGNALS = 4
EVENT_TYPES = ("funding", "launch", "other")


# ---- small coercions ------------------------------------------------------------
def to_int(v: Any) -> int | None:
    """int from an int, a float (``6.0``) or a numeric string (``"12"``, ``"10+"``)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(round(v)) if math.isfinite(v) else None
    if isinstance(v, str):
        m = re.search(r"\d+", v)
        return int(m.group(0)) if m else None
    return None


def text(v: Any, limit: int = 500) -> str | None:
    if not isinstance(v, str):
        return None
    s = " ".join(v.split())
    return s[:limit] if s else None


def texts(v: Any, limit: int = 300, max_items: int | None = None) -> list[str]:
    out = [t for t in (text(x, limit) for x in (v if isinstance(v, list) else [])) if t]
    return out[:max_items] if max_items is not None else out


def dicts(v: Any) -> list[dict[str, Any]]:
    return [x for x in (v if isinstance(v, list) else []) if isinstance(x, dict)]


def profile_url(v: Any) -> str | None:
    """FindAll urls may lack a scheme (``cognition.ai``)."""
    if isinstance(v, str) and v.strip() and "://" not in v:
        v = "https://" + v.strip()
    return safe_http_url(v)


def _attr(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


# ---- leaders -----------------------------------------------------------------------
def _summary(edu: list[dict[str, Any]], roles: list[dict[str, Any]], founded: list[dict[str, Any]]) -> str | None:
    parts: list[str] = []
    school = next((text(e.get("school"), 120) for e in edu if text(e.get("school"))), None)
    if school:
        parts.append(school)
    # One entry per employer: two roles at the same company (a promotion) must not read "Ex-Ramp, Venue, Ramp".
    unique: dict[str, str] = {}
    for c in (text(r.get("company"), 60) for r in roles):
        if c and c.casefold() not in unique:
            unique[c.casefold()] = c
    employers = list(unique.values())
    if employers:
        parts.append("Ex-" + ", ".join(employers[:3]))
    exits = [f for f in founded if f.get("outcome") in ("acquired", "ipo") and text(f.get("company"))]
    if exits:
        parts.append("Founded " + ", ".join(
            f"{text(f['company'], 60)} ({'IPO' if f['outcome'] == 'ipo' else 'acquired'})" for f in exits[:2]))
    return ". ".join(parts) if parts else None


_OUTCOMES = ("acquired", "ipo", "shut_down", "operating", "unknown")


def _role_label(role: dict[str, Any]) -> str | None:
    company = text(role.get("company"), 120)
    if not company:
        return None
    title = text(role.get("title"), 80)
    return f"{company} ({title})" if title else company


def _founded_label(f: dict[str, Any]) -> str:
    """POC format: ``Ledgerline (acquired, acq. by Northwind, 2025)``."""
    outcome = f.get("outcome") if f.get("outcome") in _OUTCOMES else "unknown"
    parts = [str(outcome)]
    acquirer, year = text(f.get("acquirer"), 80), text(f.get("exit_year"), 10)
    if acquirer:
        parts.append(f"acq. by {acquirer}")
    if year:
        parts.append(year)
    return f"{text(f.get('company'), 120)} ({', '.join(parts)})"


def build_leader(cd: Any, pedigree: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """One card leader and the matching score input."""
    o = (pedigree or {}).get("content") or {}
    edu, roles, fb = dicts(o.get("education")), dicts(o.get("prior_roles")), dicts(o.get("founded_before"))
    founded_raw = [f for f in fb if text(f.get("company"))]
    url = profile_url(_attr(cd, "url"))
    linkedin = safe_http_url(o.get("linkedin_url"))
    if linkedin is None and url and "linkedin.com/in/" in url.lower():
        linkedin = url
    name = text(_attr(cd, "name"), 200) or "Unknown"
    schools = [" ".join(x for x in (text(e.get("school"), 120), text(e.get("degree"), 40), text(e.get("field"), 80)) if x)
               for e in edu if text(e.get("school"))]
    prior = [label for label in (_role_label(r) for r in roles) if label]
    founded = [_founded_label(f) for f in founded_raw]
    years = to_int(o.get("years_experience"))
    years = years if years is not None and 0 <= years <= 80 else None
    leader = {
        "name": name,
        "title": text(o.get("current_title"), 200),
        "linkedin_url": linkedin,
        "profile_url": url,
        "summary": _summary(edu, roles, founded_raw),
        "schools": schools,
        "prior_companies": prior,
        "founded_before": founded,
        "years_experience": years,
        "industry_experience": text(o.get("industry_experience_summary"), 600),
        "signals": texts(o.get("notable_signals"), 200, MAX_SIGNALS),
    }
    score_input = {
        "name": name,
        "schools": schools,
        "prior_companies": prior,
        "founded_raw": founded_raw,
        "years": years,
        "confidence": (pedigree or {}).get("confidence") or {},
    }
    return leader, score_input


# ---- other blocks ----------------------------------------------------------------------
def build_team_stats(team: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(team, dict):
        return None

    def tally(v: Any) -> list[dict[str, Any]]:
        out = []
        for item in dicts(v):
            name, count = text(item.get("name"), 160), to_int(item.get("count"))
            if name and count is not None and count >= 0:
                out.append({"name": name, "count": count})
        return out

    def count_or_none(v: Any) -> int | None:
        # Unknown stays None (shown as "unknown"); only a real 0 reads as "none found".
        n = to_int(v)
        return None if n is None else max(0, n)

    return {
        "profiles_found": count_or_none(team.get("profiles_found")),
        "team_size_estimate": text(team.get("team_size_estimate"), 80) or "unknown",
        "schools": tally(team.get("schools")),
        "prior_employers": tally(team.get("prior_employers")),
        "ex_founders_with_exit": count_or_none(team.get("ex_founders_with_exit")),
        "sample_names": texts(team.get("sample_names"), 120, 25),
    }


def _split(s: Any) -> list[str]:
    return [x.strip()[:160] for x in s.split(",") if x.strip()] if isinstance(s, str) else []


def build_funding(brief: dict[str, Any] | None) -> dict[str, Any]:
    b = brief or {}
    lr = b.get("latest_round") if isinstance(b.get("latest_round"), dict) else None
    latest = None
    if lr is not None:
        latest = {
            "stage": text(lr.get("stage"), 80),
            "amount_usd": text(lr.get("amount_usd"), 40),
            "announced_at": text(lr.get("announced_at"), 20),
            "lead_investors": texts(lr.get("lead_investors"), 160),
            "other_investors": texts(lr.get("other_investors"), 160),
        }
        if not any(latest.values()):
            latest = None
    prior = [{
        "stage": text(p.get("stage"), 80),
        "amount_usd": text(p.get("amount_usd"), 40),
        "announced_at": text(p.get("announced_at"), 20),
        "lead_investors": [],
        "other_investors": _split(p.get("investors")),
    } for p in dicts(b.get("prior_rounds"))]
    return {"latest_round": latest, "prior_rounds": prior, "total_raised_usd": text(b.get("total_raised_usd"), 40)}


def build_event(company: str, monitor_event: dict[str, Any] | None, brief: dict[str, Any] | None) -> dict[str, Any] | None:
    if monitor_event:
        etype = monitor_event.get("event_type")
        return {
            "type": etype if etype in EVENT_TYPES else "other",
            "headline": text(monitor_event.get("headline"), 300) or company,
            "source_url": safe_http_url(monitor_event.get("source_url")),
            "announced_at": text(monitor_event.get("announced_at"), 20),
            "round": text(monitor_event.get("round"), 80),
            "amount_usd": text(monitor_event.get("amount_usd"), 40),
            "investors": text(monitor_event.get("investors"), 300),
            "origin": "monitor",
        }
    la = (brief or {}).get("latest_announcement")
    if not isinstance(la, dict) or not text(la.get("headline")):
        return None
    kind = la.get("kind") if la.get("kind") in EVENT_TYPES else "other"
    lr = (brief or {}).get("latest_round") if kind == "funding" else None
    lr = lr if isinstance(lr, dict) else {}
    investors = texts(lr.get("lead_investors"), 160) + texts(lr.get("other_investors"), 160)
    return {
        "type": kind,
        "headline": text(la.get("headline"), 300),
        "source_url": safe_http_url(la.get("url")),
        "announced_at": text(la.get("announced_at"), 20),
        "round": text(lr.get("stage"), 80),
        "amount_usd": text(lr.get("amount_usd"), 40),
        "investors": ", ".join(investors)[:300] or None,
        "origin": "task brief",
    }


def citations(basis: Any) -> list[dict[str, Any]]:
    out = []
    for b in basis or []:
        field = _attr(b, "field")
        for c in _attr(b, "citations") or []:
            url = safe_http_url(_attr(c, "url"))
            if url:
                out.append({"url": url, "title": text(_attr(c, "title"), 200),
                            "field": field if isinstance(field, str) else None})
    return out


def dedupe_sources(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for s in group:
            if s["url"] not in seen:
                seen.add(s["url"])
                out.append(s)
    return out[:MAX_SOURCES]


# ---- the payload --------------------------------------------------------------------------
def build_payload(
    *,
    company: str,
    domain: str,
    monitor_event: dict[str, Any] | None,
    brief: dict[str, Any] | None,
    brief_basis: list[Any],
    leaders: list[tuple[Any, dict[str, Any] | None]],
    leaders_dropped: int,
    team: dict[str, Any] | None,
    ats: dict[str, Any],
    run_ids: dict[str, str | None],
    cost_usd: float,
    timings: dict[str, float],
    issues: list[str],
    generated_at: str,
) -> dict[str, Any]:
    built = [build_leader(cd, ped) for cd, ped in leaders]
    talent, talent_reasons = score_talent([s for _, s in built])
    vc, vc_reasons = score_vc(brief)
    b = brief or {}
    sources = dedupe_sources(
        [citations(brief_basis)]
        + [citations((ped or {}).get("basis")) for _, ped in leaders]
        + [citations(_attr(cd, "basis")) for cd, _ in leaders]
    )
    return {
        "company": text(company, 200) or domain,
        "domain": domain,
        "website": safe_http_url(b.get("website_url")) or f"https://{domain}",
        "one_liner": text(b.get("one_liner"), 300),
        "what_they_do": text(b.get("what_they_do"), 2000),
        "blurb": text(b.get("blurb"), 1500),
        "event": build_event(company, monitor_event, brief),
        "scores": {"talent": talent, "vc": vc, "talent_reasons": talent_reasons, "vc_reasons": vc_reasons},
        "leaders": [ld for ld, _ in built],
        "leaders_dropped": int(leaders_dropped),
        "team_stats": build_team_stats(team),
        "funding": build_funding(brief),
        "notable_facts": texts(b.get("notable_facts"), 300, MAX_FACTS),
        "careers_url": safe_http_url(b.get("careers_url")),
        "ats": {k: ats[k] for k in ("provider", "board_token", "board_url", "verified", "job_count", "checked_url")},
        "pr_ready": pr_ready(ats),
        "sources": sources,
        "parallel_run_ids": {k: run_ids.get(k) for k in ("findall_id", "brief_run_id", "team_run_id",
                                                         "pedigree_group_id")},
        "cost_usd": round(float(cost_usd), 4),
        "timings_s": {k: round(float(v), 1) for k, v in timings.items()},
        "issues": [i[:300] for i in issues],
        "generated_at": generated_at,
    }

