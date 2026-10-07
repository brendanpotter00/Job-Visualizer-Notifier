"""FindAll leaders, is_person, the brief's founders fallback, and the pedigree Task Group join."""

from types import SimpleNamespace as NS

import pytest
from launch_radar.leaders import (
    MAX_LEADERS,
    BriefLeader,
    Deadline,
    DeadlineReached,
    brief_founders,
    brief_leaders,
    collect_pedigree,
    findall_request,
    is_person,
    name_key,
    pedigree_inputs,
    pedigree_spec,
    poll_findall,
    select_leaders,
)
from launch_radar.schemas import PEDIGREE_SCHEMA
from tests.unit.launch_radar_fakes import FakeParallel, candidate


@pytest.mark.parametrize(
    "name, url, expected",
    [
        ("Sam Rivera", "https://www.linkedin.com/in/example-sam-rivera", True),
        ("Priya Raman", "raindrop.ai/team", True),
        ("Ghost AI", "https://tracxn.com/d/companies/ghost/company/abc", False),
        ("Ghost Labs Inc", "https://www.crunchbase.com/organization/ghost", False),
        ("Ghost AI", "https://www.linkedin.com/company/ghost-ai", False),
        ("Madonna", "https://example.com/madonna", False),  # one word: not a full person name
        ("", "https://example.com", False),
    ],
)
def test_is_person(name, url, expected):
    assert is_person(NS(name=name, url=url)) is expected


def test_select_leaders_keeps_people_and_counts_dropped():
    cands = [
        candidate("Sam Rivera", "https://linkedin.com/in/example-sam-rivera"),
        candidate("Ghost AI", "https://linkedin.com/company/ghost"),
        candidate("Taylor Brooks", "https://x.com/alexis"),
        candidate("Not Matched", "https://x.com/n", matched=False),
    ] + [candidate(f"Person {i} Name", f"https://p.example.com/{i}") for i in range(10)]
    kept, dropped = select_leaders(NS(candidates=cands))
    assert len(kept) == 8
    assert kept[0].name == "Sam Rivera"
    # 13 matched: one company page rejected by is_person; 12 people, capped at 8.
    assert dropped == 1


def test_findall_request_is_preview_people_for_the_exact_domain():
    req = findall_request("Raindrop AI", "raindrop.ai")
    assert req["generator"] == "preview" and req["match_limit"] == 8 and req["entity_type"] == "people"
    desc = req["match_conditions"][0]["description"]
    assert "raindrop.ai" in desc
    assert "one person with a personal profile, not a company page" in desc
    assert "enrich" not in str(req)


def test_pedigree_inputs_and_spec():
    leaders = [candidate("Sam Rivera", "https://linkedin.com/in/example-sam-rivera", description="Co-Founder & CTO"),
               candidate("Taylor Brooks", "https://raindrop.ai/team")]
    inputs = pedigree_inputs(leaders, "Raindrop AI", "raindrop.ai")
    assert [i["metadata"]["row_id"] for i in inputs] == ["0", "1"]
    assert all(i["processor"] == "base" for i in inputs)
    assert inputs[0]["input"] == {"person_name": "Sam Rivera", "current_title": "Co-Founder & CTO",
                                  "linkedin_url": "https://linkedin.com/in/example-sam-rivera", "company_name": "Raindrop AI",
                                  "company_domain": "raindrop.ai"}
    assert inputs[1]["input"]["linkedin_url"] is None
    assert pedigree_spec()["output_schema"]["json_schema"] is PEDIGREE_SCHEMA


def test_collect_pedigree_joins_on_row_id_not_stream_order():
    p = FakeParallel()
    p.pedigree_by_name = {
        "Sam Rivera": ({"current_title": "CTO"}, {"current_title": "high", "education.0": "medium"}),
        "Taylor Brooks": ({"current_title": "COO"}, {"current_title": "low"}),
    }
    gid = p.task_group.create(metadata={"company": "raindrop.ai"}).task_group_id
    leaders = [candidate("Sam Rivera", "u1"), candidate("Taylor Brooks", "u2"), candidate("No Data Person", "u3")]
    p.task_group.add_runs(gid, pedigree_inputs(leaders, "Raindrop AI", "raindrop.ai"), pedigree_spec())
    rows, issues = collect_pedigree(p, gid, 3)
    assert rows[0]["content"]["current_title"] == "CTO"
    assert rows[0]["confidence"] == {"current_title": "high", "education": "medium"}
    assert rows[1]["content"]["current_title"] == "COO"
    assert 2 not in rows
    assert issues == ["pedigree run for leader 3 ended failed"]


def test_collect_pedigree_reports_stream_errors():
    client = NS(task_group=NS(get_runs=lambda gid, **kw: [NS(type="error", error=NS(message="boom"))]))
    rows, issues = collect_pedigree(client, "tgrp_1", 1)
    assert rows == {}
    assert issues == ["pedigree stream error: boom", "pedigree for leader 1 missing from results"]


def test_collect_pedigree_reports_missing_rows_and_bad_json():
    def runs(gid, **kw):
        return [NS(type="task_run.state", run=NS(run_id="r0", status="completed", metadata={"row_id": "0"}),
                   output=NS(content="not json", basis=[]))]

    rows, issues = collect_pedigree(NS(task_group=NS(get_runs=runs)), "tgrp_1", 3, expected={0, 2})
    assert rows == {}
    # row 0 had output that was not JSON; row 2 never appeared; row 1 was not expected (placeholder)
    assert issues == ["pedigree run for leader 1 returned no JSON", "pedigree for leader 3 missing from results"]


def test_pedigree_inputs_keep_the_index_of_a_placeholder():
    inputs = pedigree_inputs([candidate("Sam Rivera", "u1"), None, candidate("Taylor Brooks", "u3")],
                             "Raindrop AI", "raindrop.ai")
    assert [(i["input"]["person_name"], i["metadata"]["row_id"]) for i in inputs] == [
        ("Sam Rivera", "0"), ("Taylor Brooks", "2")]


def test_poll_findall_waits_then_returns():
    p = FakeParallel()
    p.findall_active_polls = 2
    fid = p.beta.findall.create(**findall_request("X Co", "x.co")).findall_id
    sleeps = []
    run = poll_findall(p, fid, Deadline(100), sleeps.append)
    assert not run.status.is_active
    assert sleeps == [10.0, 10.0]


def test_poll_findall_stops_at_the_deadline():
    p = FakeParallel()
    p.findall_active_polls = -1
    fid = p.beta.findall.create(**findall_request("X Co", "x.co")).findall_id
    now = [0.0]
    deadline = Deadline(25, clock=lambda: now[0])

    def sleep(s):
        now[0] += s

    with pytest.raises(DeadlineReached):
        poll_findall(p, fid, deadline, sleep)
    assert now[0] >= 25


# ---- the brief's founders (the fallback when FindAll confirms no person) -------------------


def test_brief_founders_cleans_dedupes_and_keeps_only_linkedin_urls():
    brief = {"founders": [
        {"name": "  Sam   Rivera ", "title": " Co-Founder &\nCEO ", "linkedin_url": "https://www.linkedin.com/in/sam"},
        {"name": "sam rivera.", "title": "CTO", "linkedin_url": None},  # same person: dropped
        {"name": "Priya Raman", "title": None, "linkedin_url": "javascript:alert(1)"},
        {"name": "Ana Ito", "title": 7, "linkedin_url": "https://x.com/ana"},  # not LinkedIn
        {"name": "Bo Li", "title": "COO", "linkedin_url": "linkedin.com/in/boli"},  # no scheme
        {"name": "Cy Ng", "title": "CFO", "linkedin_url": "https://linkedin.com.evil.io/in/cy"},
        {"name": "Di Wu", "title": "CPO", "linkedin_url": "http://linkedin.com/in/di-wu"},
        {"name": "", "title": "CEO", "linkedin_url": None},  # no name
        {"name": "   ", "title": "CEO", "linkedin_url": None},
        {"name": None, "title": "CEO", "linkedin_url": None},
        "Not An Object",
    ]}
    assert brief_founders(brief) == [
        {"name": "Sam Rivera", "title": "Co-Founder & CEO", "linkedin_url": "https://www.linkedin.com/in/sam"},
        {"name": "Priya Raman", "title": None, "linkedin_url": None},
        {"name": "Ana Ito", "title": None, "linkedin_url": None},
        {"name": "Bo Li", "title": "COO", "linkedin_url": None},
        {"name": "Cy Ng", "title": "CFO", "linkedin_url": None},
        {"name": "Di Wu", "title": "CPO", "linkedin_url": "http://linkedin.com/in/di-wu"},
    ]


@pytest.mark.parametrize("brief", [None, {}, {"founders": None}, {"founders": "Sam Rivera"}, {"founders": []}, "x"])
def test_brief_founders_empty_when_missing_or_malformed(brief):
    assert brief_founders(brief) == []


def test_brief_founders_capped_at_the_leader_limit():
    founders = [{"name": f"Person {i} Name", "title": "VP", "linkedin_url": None} for i in range(12)]
    out = brief_founders({"founders": founders})
    assert len(out) == MAX_LEADERS == 8
    assert [f["name"] for f in out] == [f"Person {i} Name" for i in range(8)]


def test_name_key_folds_case_punctuation_and_spacing():
    assert name_key("  Sam  RIVERA.") == name_key("sam rivera") == "sam rivera"
    assert name_key("O'Brien, Jo") == name_key("o brien jo")


def test_brief_leaders_feed_the_pedigree_like_findall_people():
    leaders = brief_leaders([
        {"name": "Sam Rivera", "title": "Co-Founder & CEO", "linkedin_url": "https://www.linkedin.com/in/sam"},
        {"name": "Priya Raman", "title": None, "linkedin_url": None},
    ])
    assert all(isinstance(ld, BriefLeader) for ld in leaders)
    assert [ld.candidate_id for ld in leaders] == ["brief:sam rivera", "brief:priya raman"]
    assert leaders[0].basis == [] and leaders[1].url is None
    inputs = pedigree_inputs(leaders, "Raindrop AI", "raindrop.ai")
    assert [(i["input"]["person_name"], i["input"]["current_title"], i["input"]["linkedin_url"], i["metadata"])
            for i in inputs] == [
        ("Sam Rivera", "Co-Founder & CEO", "https://www.linkedin.com/in/sam", {"row_id": "0"}),
        ("Priya Raman", None, None, {"row_id": "1"}),
    ]
