"""Brief / team-tally Tasks: requests, the 408 long-poll, failures and the deadline."""

from types import SimpleNamespace as NS

import pytest
from launch_radar.leaders import Deadline, DeadlineReached, RetryLater
from launch_radar.research import (
    TaskFailed,
    brief_request,
    task_output,
    team_request,
    wait_task,
)
from launch_radar.schemas import BRIEF_SCHEMA, TEAM_SCHEMA
from tests.unit.launch_radar_fakes import FakeAPIStatusError, FakeParallel


def test_brief_request_core_with_website_and_board_url():
    req = brief_request("Raindrop AI", "raindrop.ai", "Raindrop raises $35M Series A")
    assert req["processor"] == "core"
    assert req["input"] == {"company_name": "Raindrop AI", "company_domain": "raindrop.ai",
                            "context": "Raindrop raises $35M Series A"}
    schema = req["task_spec"]["output_schema"]["json_schema"]
    assert schema is BRIEF_SCHEMA
    assert "website_url" in schema["required"]
    assert schema["properties"]["ats"]["required"] == ["provider", "board_token", "board_url"]


def test_team_request_pro_excludes_founders_by_role():
    req = team_request("Raindrop AI", "raindrop.ai")
    assert req["processor"] == "pro"
    assert "NOT its founders, co-founders or C-level executives" in req["input"]
    assert req["task_spec"]["output_schema"]["json_schema"] is TEAM_SCHEMA


def test_team_tally_asks_for_schools_and_employers_not_prior_exits():
    # Prior exits are checked on the leaders (the pedigree's founded_before), not the team.
    assert set(TEAM_SCHEMA["properties"]) == set(TEAM_SCHEMA["required"]) == {
        "profiles_found", "team_size_estimate", "schools", "prior_employers", "sample_names"}
    text = (team_request("Raindrop AI", "raindrop.ai")["input"] + str(TEAM_SCHEMA)).lower()
    assert "exit" not in text and "ipo" not in text and "acquired" not in text


def test_wait_task_retries_408_then_returns():
    p = FakeParallel()
    p.brief_content = {"one_liner": "x"}
    p.task_408s = 2
    rid = p.task_run.create(**brief_request("A Co", "a.co", None)).run_id
    res = wait_task(p, rid, Deadline(600))
    assert res.output.content == {"one_liner": "x"}
    assert p.result_windows == [60, 60, 60]


def test_wait_task_failed_run_raises_task_failed():
    p = FakeParallel()
    p.task_failures = {"brief"}
    rid = p.task_run.create(**brief_request("A Co", "a.co", None)).run_id
    # /result says 404; the run itself says failed -> terminal
    with pytest.raises(TaskFailed, match="failed \\(processor error\\)"):
        wait_task(p, rid, Deadline(600))


def test_wait_task_unknown_run_is_terminal():
    p = FakeParallel()
    with pytest.raises(TaskFailed, match="unknown run"):
        wait_task(NS(task_run=NS(result=lambda *a, **k: (_ for _ in ()).throw(FakeAPIStatusError(404)),
                                 retrieve=p.task_run.retrieve)), "trun_missing", Deadline(600))


@pytest.mark.parametrize("code", [429, 500, 502, 503, 401, 402])
def test_wait_task_transient_http_errors_retry_later(code):
    p = FakeParallel()
    p.brief_content = {"one_liner": "x"}
    p.task_result_errors = {"brief": [code]}
    rid = p.task_run.create(**brief_request("A Co", "a.co", None)).run_id
    with pytest.raises(RetryLater, match=f"HTTP {code}"):
        wait_task(p, rid, Deadline(600))
    # the run was not given up on: the next poll returns the paid-for result
    assert wait_task(p, rid, Deadline(600)).output.content == {"one_liner": "x"}


def test_wait_task_404_on_a_still_running_run_retries_later():
    p = FakeParallel()
    p.task_result_errors = {"brief": [404]}
    rid = p.task_run.create(**brief_request("A Co", "a.co", None)).run_id
    with pytest.raises(RetryLater, match="while the run is running"):
        wait_task(p, rid, Deadline(600))


def test_wait_task_respects_deadline():
    now = [0.0]
    p = FakeParallel()
    p.task_408s = 100
    p.on_408 = lambda: now.__setitem__(0, now[0] + 60)
    rid = p.task_run.create(**brief_request("A Co", "a.co", None)).run_id
    with pytest.raises(DeadlineReached):
        wait_task(p, rid, Deadline(150, clock=lambda: now[0]))
    assert p.result_windows[-1] <= 30


def test_wait_task_connection_errors_retry_later_and_bugs_propagate():
    def down(*a, **k):
        raise ConnectionError("network down")

    with pytest.raises(RetryLater, match="ConnectionError"):
        wait_task(NS(task_run=NS(result=down)), "trun_1", Deadline(100))

    def bug(*a, **k):
        raise ValueError("not an HTTP problem")

    with pytest.raises(ValueError):
        wait_task(NS(task_run=NS(result=bug)), "trun_1", Deadline(100))


def test_task_output_parses_json_strings_and_rejects_text():
    good = NS(output=NS(content='{"a": 1}', basis=[1]))
    assert task_output(good) == ({"a": 1}, [1])
    assert task_output(NS(output=NS(content="free text", basis=None))) == (None, [])
    assert task_output(NS(output=None)) == (None, [])


def test_brief_schema_founders_are_required_strict_and_lean():
    founders = BRIEF_SCHEMA["properties"]["founders"]
    assert "founders" in BRIEF_SCHEMA["required"]
    assert set(BRIEF_SCHEMA["required"]) == set(BRIEF_SCHEMA["properties"])  # every field required
    assert BRIEF_SCHEMA["additionalProperties"] is False
    assert founders["type"] == "array" and "founders and current C-level leaders" in founders["description"]
    item = founders["items"]
    assert set(item["properties"]) == {"name", "title", "linkedin_url"}
    assert item["required"] == ["name", "title", "linkedin_url"] and item["additionalProperties"] is False
    assert item["properties"]["name"]["type"] == "string"
    assert item["properties"]["linkedin_url"]["type"] == ["string", "null"]
    assert len(BRIEF_SCHEMA["properties"]) == 12  # the brief already passes Parallel's recommended 10
