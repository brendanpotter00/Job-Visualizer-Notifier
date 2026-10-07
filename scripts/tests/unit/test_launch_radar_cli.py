"""CLI: argument parsing, config errors name the variable only, heartbeat, set-pr guard."""

import json
from types import SimpleNamespace as NS

import pytest

from launch_radar import radar
from launch_radar.backend_client import BackendClient
from launch_radar.config import ConfigError, load_config
from launch_radar.pipeline import Deps
from launch_radar.state import StateStore

from tests.unit.launch_radar_fakes import FakeBackend, FakeParallel


def _deps(tmp_path, fb):
    return Deps(backend=BackendClient("http://backend.test", "k", transport=fb.transport()),
                make_client=FakeParallel, store=StateStore(tmp_path), log=lambda m: None)


def test_parser_defaults_and_exclude_normalization():
    a = radar.build_parser().parse_args(["run", "--exclude", "https://www.Foo.ai/x, bar.io"])
    assert a.max_companies == 3 and a.budget == 1.0 and a.deadline_s == 540.0 and not a.dry_run
    assert a.exclude == frozenset({"foo.ai", "bar.io"})


@pytest.mark.parametrize("argv", [["run", "--budget", "0"], ["run", "--budget", "6"], ["run", "--max-companies", "-1"],
                                  ["run", "--exclude", "localhost"], ["pr-candidates", "--limit", "9"],
                                  ["heartbeat", "--status", "maybe"]])
def test_parser_rejects_bad_values(argv):
    with pytest.raises(SystemExit):
        radar.build_parser().parse_args(argv)


def test_config_errors_name_the_variable_only():
    with pytest.raises(ConfigError) as e:
        load_config({}, need_parallel=False)
    assert e.value.name == "BACKEND_URL"
    with pytest.raises(ConfigError) as e:
        load_config({"BACKEND_URL": "https://api.example.com"}, need_parallel=False)
    assert e.value.name == "INTERNAL_API_KEY"
    with pytest.raises(ConfigError) as e:
        load_config({"BACKEND_URL": "https://api.example.com", "INTERNAL_API_KEY": "s3cret"}, need_parallel=True)
    assert e.value.name == "PARALLEL_API_KEY" and "s3cret" not in e.value.message()


def test_config_loopback_needs_no_internal_key(tmp_path):
    cfg = load_config({"BACKEND_URL": "http://127.0.0.1:8000/", "LAUNCH_RADAR_STATE_DIR": str(tmp_path)},
                      need_parallel=False)
    assert cfg.backend_url == "http://127.0.0.1:8000" and cfg.internal_api_key is None and cfg.state_dir == tmp_path
    assert load_config({"BACKEND_URL": "http://localhost:8000"}, need_parallel=False).internal_api_key is None


def test_config_refuses_cleartext_backend_off_loopback():
    with pytest.raises(ConfigError) as e:
        load_config({"BACKEND_URL": "http://api.example.com", "INTERNAL_API_KEY": "s3cret"}, need_parallel=False)
    assert e.value.name == "BACKEND_URL" and e.value.message() == "BACKEND_URL must be https unless loopback"
    assert "s3cret" not in e.value.message()
    assert load_config({"BACKEND_URL": "https://api.example.com", "INTERNAL_API_KEY": "k"},
                       need_parallel=False).backend_url == "https://api.example.com"
    assert load_config({"BACKEND_URL": "http://[::1]:8000"}, need_parallel=False).internal_api_key is None


def test_main_reports_missing_config_by_name(monkeypatch, capsys):
    for k in ("BACKEND_URL", "INTERNAL_API_KEY", "PARALLEL_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert radar.main(["pr-candidates"]) == 1
    assert "config: BACKEND_URL is not set" in capsys.readouterr().err


def test_main_billed_command_requires_parallel_key(monkeypatch, capsys):
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:8000")
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    assert radar.main(["monitors-ensure"]) == 1
    assert "PARALLEL_API_KEY is not set" in capsys.readouterr().err


def test_heartbeat_needs_no_backend(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("BACKEND_URL", raising=False)
    monkeypatch.setenv("LAUNCH_RADAR_STATE_DIR", str(tmp_path))
    assert radar.main(["heartbeat", "--status", "ok", "--note", "posted 1"]) == 0
    assert (tmp_path / "heartbeat.log").read_text().strip().endswith("status=ok posted 1")


def test_set_pr_validates_the_url_before_calling_the_backend(tmp_path, capsys):
    fb = FakeBackend()
    assert radar.main(["set-pr", "--card-id", "1", "--pr-url", "https://evil.example.com/pull/1"],
                      deps=_deps(tmp_path, fb)) == 1
    assert fb.requests == []


def test_pr_candidates_and_set_pr_roundtrip(tmp_path, capsys):
    fb = FakeBackend()
    fb.cards["ghost.ai"] = {"id": 4, "status": "new", "tracked_company_id": None, "pr_url": None,
                            "payload": {"company": "Ghost AI", "pr_ready": True,
                                        "ats": {"provider": "ashby", "board_token": "ghost", "job_count": 1}}}
    assert radar.main(["pr-candidates"], deps=_deps(tmp_path, fb)) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cards"][0]["id"] == 4 and out["cards"][0]["board_token"] == "ghost"
    url = "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/412"
    assert radar.main(["set-pr", "--card-id", "4", "--pr-url", url], deps=_deps(tmp_path, fb)) == 0
    assert fb.cards["ghost.ai"]["pr_url"] == url
    # a second PR for the same card is refused (409) and reported as an error
    assert radar.main(["set-pr", "--card-id", "4", "--pr-url", url], deps=_deps(tmp_path, fb)) == 1


def test_run_dry_run_through_main(tmp_path, capsys):
    fb = FakeBackend()
    assert radar.main(["run", "--dry-run"], deps=_deps(tmp_path, fb)) == 0
    assert fb.runs == {}
