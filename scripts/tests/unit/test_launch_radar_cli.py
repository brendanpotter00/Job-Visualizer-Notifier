"""CLI: argument parsing, config errors name the variable only, heartbeat."""

import json

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
                                  ["run", "--exclude", "localhost"], ["heartbeat", "--status", "maybe"]])
def test_parser_rejects_bad_values(argv):
    with pytest.raises(SystemExit):
        radar.build_parser().parse_args(argv)


def test_subcommands_are_exactly_the_loop_its_one_off_tools_and_the_pr_queue():
    """The add-company PR step is driven by Saved cards (saved-pr/PLAN.md §4.2). There is
    still no command that takes a PR URL on the command line (pr-report reads it from a
    file pr_step.py writes), and none that merges."""
    sub = next(a for a in radar.build_parser()._actions if a.dest == "cmd")
    assert set(sub.choices) == {"monitors-ensure", "run", "backfill", "monitors-cancel", "heartbeat",
                                "import", "refresh", "rescore", "grade-export", "grade-apply",
                                "pr-next", "pr-check", "pr-report", "pr-refresh", "pr-requeue", "pr-status"}
    flags = {o for name in ("pr-next", "pr-check", "pr-report", "pr-refresh", "pr-requeue", "pr-status")
             for a in sub.choices[name]._actions for o in a.option_strings}
    assert flags == {"-h", "--help", "--card-id", "--outcome", "--reason", "--status"}


def test_pr_parsers_accept_the_documented_shapes():
    p = radar.build_parser()
    assert p.parse_args(["pr-next"]).cmd == "pr-next"
    assert p.parse_args(["pr-refresh"]).cmd == "pr-refresh"
    assert p.parse_args(["pr-check", "--card-id", "42"]).card_id == 42
    a = p.parse_args(["pr-report", "--card-id", "7", "--outcome", "failed", "--reason", "env_error"])
    assert (a.card_id, a.outcome, a.reason) == (7, "failed", "env_error")
    a = p.parse_args(["pr-report", "--card-id", "7", "--outcome", "open"])
    assert a.reason is None
    assert p.parse_args(["pr-requeue", "--card-id", "3"]).card_id == 3
    assert p.parse_args(["pr-status"]).status is None
    assert p.parse_args(["pr-status", "--status", "open", "--status", "failed"]).status == ["open", "failed"]


@pytest.mark.parametrize("argv", [
    ["pr-next", "--card-id", "1"],
    ["pr-refresh", "--card-id", "1"],
    ["pr-check"],
    ["pr-check", "--card-id", "0"],
    ["pr-check", "--card-id", "012"],
    ["pr-check", "--card-id", "1;rm -rf /"],
    ["pr-check", "--card-id", "12345678901"],
    ["pr-report", "--card-id", "1"],
    ["pr-report", "--card-id", "1", "--outcome", "cancelled"],  # only pr-check records cancelled
    ["pr-report", "--card-id", "1", "--outcome", "merged"],
    ["pr-report", "--card-id", "1", "--outcome", "failed", "--reason", "abandoned"],
    ["pr-report", "--card-id", "1", "--outcome", "open", "--pr-url",
     "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/1"],
    ["pr-requeue"],
    ["pr-status", "--status", "merged"],
])
def test_pr_parsers_reject_bad_values(argv):
    with pytest.raises(SystemExit):
        radar.build_parser().parse_args(argv)


def test_pr_report_reasons_are_the_backends_minus_abandoned():
    from launch_radar import pr_queue

    assert set(pr_queue.REPORT_REASONS) == {
        "board_not_found", "board_empty", "unsupported_ats", "unsafe_value", "pr_closed", "step_refused",
        "multi_head", "git_error", "gh_error", "timeout", "other", "env_error"}


def test_pr_command_prints_only_json_on_stdout(monkeypatch, tmp_path, capsys):
    """pr-* output is read by the session: the config log line goes to stderr."""
    from launch_radar import pr_queue

    fb = FakeBackend()
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("LAUNCH_RADAR_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("LAUNCH_RADAR_RUN_ID", raising=False)
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    monkeypatch.setattr(radar, "BackendClient",
                        lambda url, key: BackendClient(url, key, transport=fb.transport()))
    monkeypatch.setattr(pr_queue, "preflight", lambda env: None)
    monkeypatch.setattr(radar.signal, "signal", lambda *a: None)
    assert radar.main(["pr-next"]) == 0
    out, err = capsys.readouterr()
    assert [json.loads(line) for line in out.splitlines()] == [
        {"claimed": False, "reason": "empty", "time_left_s": None}]
    assert "[radar]" in err and "internal key not set" in err


def test_pr_commands_need_no_parallel_key(monkeypatch):
    asked: list[bool] = []

    def fake_load_config(*, need_parallel):
        asked.append(need_parallel)
        raise ConfigError("BACKEND_URL")

    monkeypatch.setattr(radar, "load_config", fake_load_config)
    for argv in (["pr-next"], ["pr-refresh"], ["pr-check", "--card-id", "1"], ["pr-status"]):
        assert radar.main(argv) == 1
    assert asked == [False] * 4


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
    assert radar.main(["rescore", "--all"]) == 1
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


def test_run_dry_run_through_main(tmp_path, capsys):
    fb = FakeBackend()
    assert radar.main(["run", "--dry-run"], deps=_deps(tmp_path, fb)) == 0
    assert fb.runs == {}


def test_rescore_parser_needs_exactly_one_selector():
    a = radar.build_parser().parse_args(["rescore", "--all", "--dry-run"])
    assert a.all_cards and a.dry_run and a.domains is None
    a = radar.build_parser().parse_args(["rescore", "--domains", "https://www.Graph.ai, b.io"])
    assert a.domains == frozenset({"graph.ai", "b.io"}) and not a.all_cards and not a.dry_run
    for argv in (["rescore"], ["rescore", "--dry-run"], ["rescore", "--all", "--domains", "a.ai"],
                 ["rescore", "--domains", "localhost"]):
        with pytest.raises(SystemExit):
            radar.build_parser().parse_args(argv)


def test_rescore_loads_config_without_the_parallel_key(monkeypatch):
    asked: list[bool] = []

    def fake_load_config(*, need_parallel):
        asked.append(need_parallel)
        raise ConfigError("BACKEND_URL")  # stop before any backend call

    monkeypatch.setattr(radar, "load_config", fake_load_config)
    assert radar.main(["rescore", "--all"]) == 1
    assert radar.main(["rescore", "--domains", "a.ai", "--dry-run"]) == 1
    assert asked == [False, False]
