"""Local resumable state: queue, per-company files, heartbeat."""

import json

import pytest

from launch_radar.state import StateStore, iso, parse_iso


def test_queue_append_dedupes_and_remove(tmp_path):
    s = StateStore(tmp_path)
    assert s.load_queue() == []
    s.append_queue([{"domain": "a.ai"}, {"domain": "b.ai"}])
    s.append_queue([{"domain": "a.ai", "x": 1}, {"domain": "c.ai"}])
    assert [q["domain"] for q in s.load_queue()] == ["a.ai", "b.ai", "c.ai"]
    s.remove_from_queue("b.ai")
    assert [q["domain"] for q in s.load_queue()] == ["a.ai", "c.ai"]
    assert not list(tmp_path.glob(".queue.json.*.tmp"))


def test_company_state_roundtrip(tmp_path):
    s = StateStore(tmp_path)
    assert s.load_company("raindrop.ai") is None and not s.has_company("raindrop.ai")
    s.save_company("raindrop.ai", {"ids": {"findall_id": "findall_1"}, "reserved": {"findall.create": 0.1}})
    assert s.has_company("raindrop.ai")
    assert s.load_company("raindrop.ai")["ids"]["findall_id"] == "findall_1"
    s.delete_company("raindrop.ai")
    assert s.load_company("raindrop.ai") is None


def test_refuses_path_like_domains(tmp_path):
    s = StateStore(tmp_path)
    with pytest.raises(ValueError):
        s.save_company("../evil", {})


def test_heartbeat_appends_one_line(tmp_path):
    s = StateStore(tmp_path / "state")
    s.heartbeat("ok", "posted 2\ncards")
    s.heartbeat("error", None)
    lines = (tmp_path / "state" / "heartbeat.log").read_text().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("status=ok posted 2 cards")
    assert lines[1].endswith("status=error")


def test_corrupt_queue_raises(tmp_path):
    (tmp_path / "queue.json").write_text(json.dumps({"not": "a list"}))
    with pytest.raises(ValueError):
        StateStore(tmp_path).load_queue()


def test_iso_roundtrip():
    dt = parse_iso("2026-10-07T07:00:00Z")
    assert iso(dt) == "2026-10-07T07:00:00Z"
