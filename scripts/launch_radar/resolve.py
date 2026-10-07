"""Find the website of a Monitor event that came back with ``company_domain: null``.

News articles rarely print a startup's website, so most events arrive without a
domain, and dedupe needs one. For each such event the loop makes one Search API
call (``mode="fast"``, about $0.001, reserved in the ledger first) and keeps the
highest-ranked result whose host carries the company's name and is the company's
own site, not a news, directory or social page. (Entity Search was tried first:
for companies it returns LinkedIn/Tracxn profiles, never the website.)

All event and search text is untrusted web data; it is only compared, never acted on.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .domains import is_big_tech, is_hostname, normalize_domain
from .schemas import ceil_cost

Log = Callable[[str], None]
Reserve = Callable[[str, float], Any]

MAX_LOOKUPS_PER_RUN = 10
SEARCH_FAST_PRICE = 0.001  # $1 per 1k requests; 10 results included
MAX_RESULTS = 8

# Hosts that describe a company but are not its website.
NOT_A_COMPANY_SITE = {
    "crunchbase.com", "linkedin.com", "tracxn.com", "pitchbook.com", "cbinsights.com", "dealroom.co",
    "wellfound.com", "angel.co", "zoominfo.com", "owler.com", "apollo.io", "rocketreach.co", "craft.co",
    "f6s.com", "ycombinator.com", "producthunt.com", "wikipedia.org", "github.com", "medium.com",
    "substack.com", "x.com", "twitter.com", "facebook.com", "instagram.com", "youtube.com", "tiktok.com",
    "techcrunch.com", "venturebeat.com", "businesswire.com", "prnewswire.com", "globenewswire.com",
    "bloomberg.com", "reuters.com", "forbes.com", "sifted.eu", "eu-startups.com", "finsmes.com",
    "axios.com", "theinformation.com", "siliconangle.com", "geekwire.com", "fortune.com", "cnbc.com",
}

_SUFFIXES = {"inc", "incorporated", "llc", "ltd", "limited", "gmbh", "ag", "sa", "sas", "bv", "corp",
             "corporation", "co", "company", "plc", "hq", "the"}


def name_key(name: object) -> str:
    """Lower-case alphanumeric words of a company name, without legal suffixes."""
    words = re.findall(r"[a-z0-9]+", str(name or "").lower())
    return " ".join(w for w in words if w not in _SUFFIXES)


def is_listing_site(dom: str) -> bool:
    """A news, directory or social host: it describes a company but is not its website."""
    return dom in NOT_A_COMPANY_SITE or any(dom.endswith("." + h) for h in NOT_A_COMPANY_SITE)


def company_site(url: object) -> str | None:
    """The normalized domain of ``url`` when it can be a company's own website."""
    dom = normalize_domain(url)
    if not dom or not is_hostname(dom) or is_big_tech(dom) or is_listing_site(dom):
        return None
    return dom


def host_matches(event_name: object, domain: str) -> bool:
    """True when the domain's main label carries the company name ("guardrail.tech" for "Guardrail Technologies")."""
    parts = domain.split(".")
    label = parts[-2] if len(parts) >= 2 else parts[0]
    words = name_key(event_name).split()
    if not words or not label:
        return False
    compact = "".join(words)
    return (compact == label
            or (len(compact) >= 4 and compact in label)
            or (len(label) >= 4 and label in compact)
            or (len(words[0]) >= 4 and words[0] in label))


def pick_domain(event_name: str, results: list[Any]) -> str | None:
    """The first result, in Search's rank order, that is a company site named like the company."""
    for r in results:
        url = getattr(r, "url", None) if not isinstance(r, dict) else r.get("url")
        dom = company_site(url)
        if dom and host_matches(event_name, dom):
            return dom
    return None


def resolve_missing_domains(events: list[dict[str, Any]], client: Any, reserve: Reserve, log: Log,
                            limit: int = MAX_LOOKUPS_PER_RUN) -> list[dict[str, Any]]:
    """Fill ``company_domain`` in place for events that have none. Returns ``events``.

    ``reserve`` raises ``BudgetExceeded`` past the cap; it propagates so the caller
    can stop before the Monitor cursors move (the events are then read again next run).
    """
    missing = [ev for ev in events if not normalize_domain(ev.get("company_domain")) and ev.get("company_name")]
    if len(missing) > limit:
        log(f"domain lookup: {len(missing)} events have no domain; looking up the first {limit} only")
    for ev in missing[:limit]:
        name = str(ev["company_name"])[:120]
        reserve(f"search(domain:{name_key(name)[:40]})", ceil_cost(SEARCH_FAST_PRICE))
        context = str(ev.get("headline") or "")[:200]
        resp = client.search(
            objective=f"The official company website (homepage) of the startup {name}. Context: {context}",
            search_queries=[f"{name} official website", f"{name} startup"],
            mode="fast",
            advanced_settings={"max_results": MAX_RESULTS},
        )
        results = list(getattr(resp, "results", None) or [])
        dom = pick_domain(name, results)
        if dom:
            ev["company_domain"] = dom
            ev["domain_source"] = "search"
            log(f"domain lookup: {name!r} -> {dom}")
        else:
            log(f"domain lookup: {name!r} -> no company site named like it in {len(results)} result(s)")
    return events
