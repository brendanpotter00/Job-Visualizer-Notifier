"""cutover.py — `cli health` must be identical in the old and new prod after
dropping the keys that differ between any two reads (PLAN §4.4 C4)."""

from __future__ import annotations

import copy
import json

import pytest

from test_cutover_ref import load_cutover

co = load_cutover()

#: the shape `cli health` prints at enricher-prod-eeff1c9 (health.collect_health)
HEALTH = {
    "inbox": {"sent": 120345, "enriched": 12, "cleaned": 3, "failed": 2},
    "unsent": 12,
    "needs_human": 40,
    "failed_rows": 2,
    "last_heartbeat_at": "2026-11-23T12:52:10.000000+00:00",
    "last_heartbeat_age_s": 6070.2,
    "stage_timings": [
        {"stage": "classify", "runs": 2215, "avg_ms": 3600000.5, "items": 88000, "retries": 4},
    ],
    "classify_engine": "ollama",
    "classify_model": "haiku",
    "judge_engine": "ollama",
    "judge_model": "sonnet",
    "opencode_model": "qwen3:32b",
    "latest_tick": {"id": 2220, "uuid": "u", "started_at": "2026-11-23T12:52:08+00:00",
                    "ended_at": None, "status": "running", "claimed": 40, "sent": 0},
}


def test_volatile_keys_are_dropped_recursively():
    n = co.normalize_health(HEALTH)
    assert "last_heartbeat_at" not in n and "last_heartbeat_age_s" not in n
    assert "started_at" not in n["latest_tick"] and "ended_at" not in n["latest_tick"]
    assert n["latest_tick"]["id"] == 2220 and n["inbox"] == HEALTH["inbox"]
    assert co.normalize_health({"now": 1, "x": [{"y_at": 1, "z": 2}]}) == {"x": [{"z": 2}]}


def test_two_reads_of_the_same_data_are_equal():
    later = copy.deepcopy(HEALTH)
    later["last_heartbeat_age_s"] = 6131.9
    later["latest_tick"]["started_at"] = "2026-11-23T12:52:08.624181+00:00"
    assert co.health_diff(HEALTH, later) == []


@pytest.mark.parametrize(
    "path, value",
    [
        (("unsent",), 13),
        (("classify_engine",), "claude-code"),
        (("latest_tick", "id"), 2221),
        (("inbox", "sent"), 120344),
        (("stage_timings",), []),
    ],
)
def test_a_real_difference_is_reported_by_key(path, value):
    other = copy.deepcopy(HEALTH)
    target = other
    for k in path[:-1]:
        target = target[k]
    target[path[-1]] = value
    assert co.health_diff(HEALTH, other) == [path[0]]


def test_parse_health_takes_the_last_json_object_line():
    out = "Resolved 34 packages\nnoise {not json\n" + json.dumps(HEALTH) + "\n"
    assert co.parse_health(out) == HEALTH
    assert co.parse_health(json.dumps({"a": 1}) + "\n" + json.dumps({"b": 2})) == {"b": 2}


@pytest.mark.parametrize("out", ["", "warning: something\n", "[1, 2]\n", "{broken\n"])
def test_parse_health_refuses_output_without_an_object(out):
    with pytest.raises(ValueError):
        co.parse_health(out)
