"""Domain lookup for Monitor events that arrive without a website (launch_radar.resolve)."""

from types import SimpleNamespace as NS

import pytest
from launch_radar.backend_client import BudgetExceeded
from launch_radar.resolve import (
    company_site,
    host_matches,
    pick_domain,
    resolve_missing_domains,
)


@pytest.mark.parametrize("name,dom,ok", [
    ("finmid", "finmid.com", True),
    ("OneByZero", "onebyzero.io", True),
    ("Guardrail Technologies", "guardrail.tech", True),
    ("SignSplit Inc.", "signsplit.com", True),
    ("Navra", "usenavra.com", True),
    ("finmid", "tech.eu", False),
    ("Melius", "meliuz.com.br", False),
    ("AI", "ai-robotics.com", False),     # too short to match loosely
    ("", "anything.com", False),
])
def test_host_matches(name, dom, ok):
    assert host_matches(name, dom) is ok


@pytest.mark.parametrize("url,dom", [
    ("https://www.melius.com/", "melius.com"),
    ("https://www.crunchbase.com/organization/melius", None),
    ("https://uk.linkedin.com/company/melius", None),
    ("https://www.prnewswire.com/news-releases/signsplit-302897779.html", None),
    ("https://openai.com", None),
    ("not a url", None),
    (None, None),
])
def test_company_site(url, dom):
    assert company_site(url) == dom


def test_pick_domain_keeps_rank_order_and_skips_news_and_profiles():
    results = [NS(url="https://tech.eu/2026/10/06/finmid-raises"), NS(url="https://linkedin.com/company/finmid"),
               NS(url="http://www.finmid.com/"), NS(url="https://finmid.example.org")]
    assert pick_domain("finmid", results) == "finmid.com"
    assert pick_domain("finmid", results[:2]) is None


class _Client:
    def __init__(self, results):
        self.calls = []
        self.results = results

    def search(self, objective, search_queries, mode, advanced_settings):
        self.calls.append((objective, search_queries, mode, advanced_settings))
        name = search_queries[0].removesuffix(" official website")
        return NS(results=self.results.get(name, []))


def test_resolve_fills_only_missing_domains_and_reserves_first():
    order = []
    events = [{"company_name": "Melius", "company_domain": None, "headline": "Melius raises $20M"},
              {"company_name": "Kept", "company_domain": "kept.io"},
              {"company_name": None, "company_domain": None}]
    client = _Client({"Melius": [NS(url="https://www.melius.com/")]})
    reserve = lambda step, est: order.append(("reserve", step, est))
    resolve_missing_domains(events, client, reserve, lambda m: None)
    assert events[0]["company_domain"] == "melius.com" and events[0]["domain_source"] == "search"
    assert events[1]["company_domain"] == "kept.io" and "domain_source" not in events[1]
    assert len(client.calls) == 1 and client.calls[0][2] == "fast"
    assert order == [("reserve", "search(domain:melius)", 0.001)]


def test_resolve_caps_lookups_per_run_and_says_so():
    events = [{"company_name": f"Co{i}", "company_domain": None} for i in range(4)]
    client, logs = _Client({}), []
    resolve_missing_domains(events, client, lambda s, e: None, logs.append, limit=2)
    assert len(client.calls) == 2
    assert any("looking up the first 2 only" in m for m in logs)


def test_budget_refusal_propagates_before_any_search():
    def refuse(step, est):
        raise BudgetExceeded("cap", 0.0, 5.0, 5.0)
    client = _Client({})
    with pytest.raises(BudgetExceeded):
        resolve_missing_domains([{"company_name": "Melius", "company_domain": None}], client, refuse, lambda m: None)
    assert client.calls == []
