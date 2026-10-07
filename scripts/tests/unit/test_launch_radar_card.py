"""Card payload (CONTRACT §4): exact keys, float->int casts, untrusted-text handling."""

from launch_radar.card import build_event, build_funding, build_leader, build_payload, build_team_stats, to_int

from tests.unit.launch_radar_fakes import basis, candidate

PAYLOAD_KEYS = {
    "company", "domain", "website", "one_liner", "what_they_do", "blurb", "event", "scores", "leaders",
    "leaders_dropped", "team_stats", "funding", "notable_facts", "careers_url", "ats", "pr_ready", "sources",
    "parallel_run_ids", "cost_usd", "timings_s", "issues", "generated_at",
}
LEADER_KEYS = {"name", "title", "linkedin_url", "profile_url", "summary", "schools", "prior_companies",
               "founded_before", "years_experience", "industry_experience", "signals"}
ROUND_KEYS = {"stage", "amount_usd", "announced_at", "lead_investors", "other_investors"}
ATS = {"provider": "ashby", "board_token": "Raindrop", "board_url": "https://jobs.ashbyhq.com/Raindrop",
       "verified": True, "job_count": 9, "checked_url": "https://api.ashbyhq.com/posting-api/job-board/Raindrop"}

BRIEF = {
    "one_liner": "Monitoring for AI agents",
    "website_url": "https://www.raindrop.ai",
    "what_they_do": "Raindrop  watches\nagents in production.",
    "latest_round": {"stage": "Series A", "amount_usd": "$35M", "announced_at": "2026-09-17",
                     "lead_investors": ["CRV"], "other_investors": ["Lightspeed Venture Partners", "Y Combinator"]},
    "prior_rounds": [{"stage": "Seed", "amount_usd": "$15M", "announced_at": "2025-01",
                      "investors": "Lightspeed, Figma Ventures , "}],
    "total_raised_usd": "$50M",
    "latest_announcement": {"headline": "Raindrop raises $35M", "url": "https://techcrunch.com/raindrop",
                            "announced_at": "2026-09-17", "kind": "funding"},
    "notable_facts": [f"fact {i}" for i in range(9)],
    "blurb": "A team from Apple and Northwind.",
    "careers_url": "https://raindrop.ai/careers",
    "ats": {"provider": "ashby", "board_token": "Raindrop", "board_url": None},
}
PEDIGREE = {
    "content": {
        "current_title": "Co-Founder & CTO",
        "linkedin_url": "https://linkedin.com/in/example-sam-rivera",
        "education": [{"school": "Worcester Polytechnic Institute", "degree": "BS", "field": "Robotics", "grad_year": None}],
        "prior_roles": [{"company": "Apple", "title": "Designer", "years": None},
                        {"company": "Google", "title": "Intern", "years": None}],
        "founded_before": [{"company": "Ledgerline", "outcome": "acquired", "acquirer": "Northwind", "exit_year": "2025"}],
        "years_experience": 8.0,
        "industry_experience_summary": "Design and AI.",
        "notable_signals": ["a", "b", "c", "d", "e"],
    },
    "confidence": {"education": "high", "prior_roles": "high", "founded_before": "medium"},
    "basis": [basis("education", "high", ("https://wpi.edu/ben",))],
}
TEAM = {"profiles_found": 6.0, "team_size_estimate": "approximately 10-20",
        "schools": [{"name": "University of California, Davis", "count": 1.0}],
        "prior_employers": [{"name": "Amazon", "count": 2.0}, {"name": "bad", "count": "n/a"}],
        "ex_founders_with_exit": 0.0, "sample_names": ["X Y"]}


def _payload(**over):
    kw = dict(
        company="Raindrop AI", domain="raindrop.ai", monitor_event=None, brief=BRIEF,
        brief_basis=[basis("one_liner", "high", ("https://raindrop.ai", "https://raindrop.ai"))],
        leaders=[(candidate("Sam Rivera", "linkedin.com/in/example-sam-rivera"), PEDIGREE)], leaders_dropped=0,
        team=TEAM, ats=ATS, run_ids={"findall_id": "findall_1", "brief_run_id": "trun_1",
                                     "team_run_id": "trun_2", "pedigree_group_id": "tgrp_1"},
        cost_usd=0.2950000001, timings={"findall_s": 154.04}, issues=[], generated_at="2026-10-07T01:36:00Z",
    )
    kw.update(over)
    return build_payload(**kw)


def test_payload_has_exactly_the_contract_keys():
    p = _payload()
    assert set(p) == PAYLOAD_KEYS
    assert set(p["leaders"][0]) == LEADER_KEYS
    assert set(p["scores"]) == {"talent", "vc", "talent_reasons", "vc_reasons"}
    assert set(p["funding"]) == {"latest_round", "prior_rounds", "total_raised_usd"}
    assert set(p["funding"]["latest_round"]) == ROUND_KEYS
    assert set(p["parallel_run_ids"]) == {"findall_id", "brief_run_id", "team_run_id", "pedigree_group_id"}
    assert set(p["team_stats"]) == {"profiles_found", "team_size_estimate", "schools", "prior_employers",
                                    "ex_founders_with_exit", "sample_names"}
    assert p["pr_ready"] is True
    assert p["website"] == "https://www.raindrop.ai"
    assert p["what_they_do"] == "Raindrop watches agents in production."
    assert len(p["notable_facts"]) == 6
    assert p["cost_usd"] == 0.295
    assert p["timings_s"] == {"findall_s": 154.0}


def test_float_counts_are_cast_to_int():
    p = _payload()
    ts = p["team_stats"]
    assert ts["profiles_found"] == 6 and isinstance(ts["profiles_found"], int)
    assert ts["ex_founders_with_exit"] == 0 and isinstance(ts["ex_founders_with_exit"], int)
    assert ts["schools"] == [{"name": "University of California, Davis", "count": 1}]
    assert ts["prior_employers"] == [{"name": "Amazon", "count": 2}]  # the non-numeric row is dropped
    assert isinstance(ts["prior_employers"][0]["count"], int)
    years = p["leaders"][0]["years_experience"]
    assert years == 8 and isinstance(years, int)


def test_to_int_variants():
    assert to_int(6.0) == 6 and to_int(6.6) == 7 and to_int("12") == 12 and to_int("10+ years") == 10
    assert to_int(None) is None and to_int("unknown") is None and to_int(True) is None
    assert to_int(float("nan")) is None


def test_leader_fields_and_summary():
    leader, score_in = build_leader(candidate("Sam Rivera", "linkedin.com/in/example-sam-rivera"), PEDIGREE)
    assert leader["title"] == "Co-Founder & CTO"
    assert leader["profile_url"] == "https://linkedin.com/in/example-sam-rivera"
    assert leader["schools"] == ["Worcester Polytechnic Institute BS Robotics"]
    assert leader["prior_companies"] == ["Apple (Designer)", "Google (Intern)"]
    assert leader["founded_before"] == ["Ledgerline (acquired, acq. by Northwind, 2025)"]
    assert leader["summary"] == "Worcester Polytechnic Institute. Ex-Apple, Google. Founded Ledgerline (acquired)"
    assert leader["signals"] == ["a", "b", "c", "d"]
    assert score_in["founded_raw"][0]["outcome"] == "acquired"


def test_summary_lists_each_employer_once():
    # Real case (Melius, 2026-10-07): a promotion is two roles at one company; the
    # summary read "Ex-Ramp, Venue, Ramp" before employers were de-duplicated.
    content = {**PEDIGREE["content"], "prior_roles": [
        {"company": "Ramp", "title": "Director, Engineering", "years": None},
        {"company": "Venue", "title": "Co-Founder, CTO", "years": None},
        {"company": "ramp", "title": "Senior Software Engineer", "years": None},
        {"company": "Facebook", "title": "Software Engineer", "years": None},
    ]}
    leader, _ = build_leader(candidate("Casey Lee", "linkedin.com/in/example-casey-lee"), {**PEDIGREE, "content": content})
    assert "Ex-Ramp, Venue, Facebook." in leader["summary"]
    assert len(leader["prior_companies"]) == 4  # the detailed list still shows every role


def test_leader_without_pedigree_has_no_data_and_null_talent():
    p = _payload(leaders=[(candidate("Sam Rivera", "https://x.com/ben"), None)])
    ld = p["leaders"][0]
    assert ld["summary"] is None and ld["schools"] == [] and ld["years_experience"] is None
    assert ld["linkedin_url"] is None
    assert p["scores"]["talent"] is None
    assert p["scores"]["vc"] == 55


def test_scores_from_rubric():
    p = _payload()
    # Ben: top employers Apple + Google (high, 10) + prior exit (medium 15*0.8 = 12) -> 22.
    assert p["scores"]["talent"] == 22
    assert "Sam Rivera: prior exit (Ledgerline, acquired by Northwind)" in p["scores"]["talent_reasons"]


def test_sources_deduped_and_unsafe_urls_dropped():
    bad = basis("x", "high", ("javascript:alert(1)", "https://ok.example.com"))
    p = _payload(brief_basis=[basis("one_liner", "high", ("https://raindrop.ai",)), bad,
                              basis("blurb", "high", ("https://raindrop.ai",))])
    urls = [s["url"] for s in p["sources"]]
    assert urls[:2] == ["https://raindrop.ai", "https://ok.example.com"]
    assert "https://wpi.edu/ben" in urls
    assert len(urls) == len(set(urls))
    assert p["sources"][0] == {"url": "https://raindrop.ai", "title": None, "field": "one_liner"}


def test_untrusted_urls_in_brief_are_not_linked():
    brief = dict(BRIEF, website_url="javascript:alert(1)", careers_url="data:text/html,x")
    p = _payload(brief=brief)
    assert p["website"] == "https://raindrop.ai"
    assert p["careers_url"] is None


def test_event_from_monitor_then_brief_then_none():
    mon = {"company_name": "Raindrop AI", "event_type": "funding", "round": "Series A", "amount_usd": "$35M",
           "investors": "CRV", "announced_at": "2026-09-17", "source_url": "https://news.example.com/r",
           "headline": "Raindrop raises $35M"}
    e = build_event("Raindrop AI", mon, BRIEF)
    assert e["origin"] == "monitor" and e["type"] == "funding" and e["round"] == "Series A"
    e2 = build_event("Raindrop AI", None, BRIEF)
    assert e2["origin"] == "task brief" and e2["amount_usd"] == "$35M" and e2["source_url"] == "https://techcrunch.com/raindrop"
    assert build_event("Raindrop AI", None, None) is None
    weird = build_event("X", dict(mon, event_type="acquisition", headline=None), None)
    assert weird["type"] == "other" and weird["headline"] == "X"


def test_funding_prior_rounds_split_investors():
    f = build_funding(BRIEF)
    assert f["prior_rounds"] == [{"stage": "Seed", "amount_usd": "$15M", "announced_at": "2025-01",
                                  "lead_investors": [], "other_investors": ["Lightspeed", "Figma Ventures"]}]
    assert f["total_raised_usd"] == "$50M"
    assert build_funding(None) == {"latest_round": None, "prior_rounds": [], "total_raised_usd": None}


def test_team_stats_none_when_task_failed():
    assert build_team_stats(None) is None
    p = _payload(team=None, brief=None, leaders=[], ats=dict(ATS, verified=False, job_count=None))
    assert p["team_stats"] is None and p["one_liner"] is None and p["event"] is None
    assert p["scores"] == {"talent": None, "vc": None, "talent_reasons": [], "vc_reasons": []}
    assert p["pr_ready"] is False


def test_team_stats_keep_unknown_counts_as_none_not_zero():
    ts = build_team_stats({"profiles_found": "several", "team_size_estimate": "10-20", "schools": [],
                           "prior_employers": [], "sample_names": []})
    assert ts["profiles_found"] is None and ts["ex_founders_with_exit"] is None
    ts = build_team_stats({"profiles_found": 6.0, "ex_founders_with_exit": 0.0, "team_size_estimate": "x",
                           "schools": [], "prior_employers": [], "sample_names": []})
    assert ts["profiles_found"] == 6 and ts["ex_founders_with_exit"] == 0
