"""WT-01..WT-06 — the merge trigger (``watcher.sh``) and its installer.

The watcher runs as ``/bin/bash <state>/watcher.sh`` (macOS bash 3.2, what its
plist runs), from the COPY ``install_watcher.sh`` puts in the state dir.

WT-01  main without cutover.py -> "not merged yet", no cutover, no text
WT-02  remote unreachable (a refused transport; a vanished remote) -> exit 0,
       "retry next interval", no state change
WT-03  merged -> it runs the cutover FROM MERGED MAIN (a marked variant proves
       which copy ran) and hands its lock to it
WT-04  a second watcher while the first runs -> exits at once
WT-05  terminal state -> plist moved to retired/, ``launchctl remove``, no cutover
WT-06  install_watcher.sh: --dry-run writes nothing; install copies + loads and
       the RunAtLoad fire runs; refuses after DONE
WT-07  offline, a cutover killed right after the plist switch (no worker loaded)
       still resumes from the last fetched main, and drops the watcher's lock
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import time

import pytest

import cutover_sandbox as cs


def _render_watcher_plist(sb: cs.Sandbox) -> bytes:
    tpl = (sb.scripts_src / "src" / "enricher" / "scripts" / "cutover"
           / f"{cs.WATCHER_LABEL}.plist.template").read_text()
    return tpl.replace("__STATE_DIR__", str(sb.state_dir)).replace("__HOME__", str(sb.home)).encode()


@pytest.mark.fast
def test_wt01_not_merged_is_a_noop(make_sandbox, step):
    sb = make_sandbox(jvn="unmerged", interval_s=3600)
    t0 = time.time()
    step("one watcher fire against a main without the cutover")
    cp = sb.run_watcher(label="not merged")
    assert cp.returncode == 0, sb.output()
    assert "not merged yet (main has no src/enricher/scripts/cutover/cutover.py)" in cp.stdout
    assert (sb.state_dir / "jvn.git" / "HEAD").is_file(), "the mirror was not built"
    assert not (sb.state_dir / "run").exists() and not (sb.state_dir / "state.json").exists()
    assert not (sb.state_dir / "watcher.lock").exists(), "the lock was not released"
    assert not [c for c in sb.calls() if c["t"] > t0] and sb.texts() == []
    assert not sb.new.exists()


@pytest.mark.fast
def test_wt02_unreachable_remote_retries_next_interval(make_sandbox, step):
    sb = make_sandbox(jvn="unmerged", interval_s=3600)
    step("no mirror yet, and the remote's transport is refused (what DNS failure looks like)")
    cp = sb.run_watcher(env_extra={"JVN_REMOTE_URL": "https://jvn-e2e.invalid/jvn.git"},
                        label="refused transport")
    assert cp.returncode == 0, sb.output()
    assert "clone of https://jvn-e2e.invalid/jvn.git failed; retry next interval" in cp.stdout
    assert not (sb.state_dir / "jvn.git").exists()

    step("the mirror exists, then the remote vanishes")
    cp = sb.run_watcher(label="builds the mirror")
    assert cp.returncode == 0 and "not merged yet" in cp.stdout, sb.output()
    mirror = sb.state_dir / "jvn.git"
    head = sb.git(mirror, "rev-parse", "main").strip()
    shutil.move(str(sb.jvn_remote), str(sb.root / "jvn-remote-gone.git"))
    cp = sb.run_watcher(label="remote gone")
    assert cp.returncode == 0, sb.output()
    assert "fetch failed, retry next interval" in cp.stdout, sb.output()
    assert sb.git(mirror, "rev-parse", "main").strip() == head
    for p in ("state.json", "run", "watcher.lock"):
        assert not (sb.state_dir / p).exists(), p
    assert sb.texts() == []


@pytest.mark.fast
def test_wt03_runs_the_cutover_from_merged_main(make_sandbox, step):
    sb = make_sandbox(marked_cutover=True, interval_s=3600)
    marker = sb.root / "marker.txt"
    step("one watcher fire; main's cutover.sh is a marked variant")
    cp = sb.run_watcher(env_extra={"FAKE_MARKER": str(marker)}, label="merged")
    assert cp.returncode == 0, sb.output()
    assert f"main {sb.jvn_main} contains the cutover; running it" in cp.stdout
    got = dict(ln.split("=", 1) for ln in marker.read_text().splitlines())
    run_dir = sb.state_dir / "run" / sb.jvn_main / "src" / "enricher" / "scripts"
    assert got["path"] == str(run_dir / "cutover" / "cutover.sh"), got
    assert got["args"] == "--run"
    step("the whole scripts dir came from main; the installed copy is the real watcher")
    assert (run_dir / "lib" / "park_worker.py").is_file()
    installed = (sb.state_dir / "watcher.sh").read_bytes()
    assert installed == (sb.scripts_src / "src/enricher/scripts/cutover/watcher.sh").read_bytes()
    assert b"WT-03" not in installed
    step("the watcher's lock passed to the cutover through exec (same pid)")
    assert (sb.state_dir / "watcher.lock" / "pid").read_text().strip() == got["pid"]
    assert not (sb.state_dir / "state.json").exists(), "the real cutover ran instead"


def test_wt04_second_watcher_exits_while_first_runs(make_sandbox, step):
    sb = make_sandbox(marked_cutover=True, interval_s=3600)
    marker, release = sb.root / "marker.txt", sb.root / "release"
    env = {"FAKE_MARKER": str(marker), "FAKE_MARKER_RELEASE": str(release)}
    step("watcher 1 runs (its cutover holds the lock until released)")
    first = sb.run_watcher(env_extra=env, background=True)
    try:
        cs.wait_for(marker.exists, 30, "watcher 1 to reach its cutover")
        holder = dict(ln.split("=", 1) for ln in marker.read_text().splitlines())["pid"]
        step("watcher 2 fires meanwhile")
        t0 = time.time()
        cp = sb.run_watcher(env_extra=env, timeout=30, label="second watcher")
        assert cp.returncode == 0, sb.output()
        assert f"another watcher/cutover is running (pid {holder}); exiting" in cp.stdout, sb.output()
        assert time.time() - t0 < 5, "watcher 2 did not exit at once"
        assert first.poll() is None, "watcher 1 stopped early"
    finally:
        release.write_text("go\n")
        out, err = first.communicate(timeout=30)
    assert first.returncode == 0, out + err


@pytest.mark.fast
@pytest.mark.parametrize("phase", ["DONE", "FAILED", "ROLLED_BACK"])
def test_wt05_terminal_state_retires_the_watcher(make_sandbox, step, phase):
    sb = make_sandbox(interval_s=3600)  # main HAS the cutover: it still must not run
    sb.state_dir.mkdir(parents=True, exist_ok=True)
    state = sb.state_dir / "state.json"
    state.write_text(json.dumps({"phase": phase, "history": []}, indent=2, sort_keys=True) + "\n")
    before = state.read_bytes()
    sb.watcher_plist.write_bytes(_render_watcher_plist(sb))
    assert sb.launchctl("__seed", str(sb.watcher_plist)).returncode == 0
    t0 = time.time()

    step(f"one watcher fire with the cutover {phase}")
    cp = sb.run_watcher(label=f"terminal {phase}")
    assert cp.returncode == 0, sb.output()
    assert f"cutover is {phase}; retiring the watcher" in cp.stdout
    assert not sb.watcher_plist.exists()
    assert (sb.state_dir / "retired" / sb.watcher_plist.name).read_bytes() == _render_watcher_plist(sb)
    removes = [c for c in sb.calls() if c["t"] > t0 and c["argv"][:1] == ["remove"]]
    assert [c["argv"] for c in removes] == [["remove", cs.WATCHER_LABEL]] and removes[0]["loaded"]
    assert cs.WATCHER_LABEL not in sb.launchd_state()
    assert not (sb.state_dir / "jvn.git").exists() and not (sb.state_dir / "run").exists()
    assert state.read_bytes() == before and not sb.new.exists()


def test_wt06_install_watcher(make_sandbox, step):
    sb = make_sandbox(jvn="unmerged", interval_s=3600)
    install = sb.scripts_src / "src" / "enricher" / "scripts" / "cutover" / "install_watcher.sh"
    watched = {"home": sb.home}
    before = {k: cs.tree_manifest(v) for k, v in watched.items()}
    t0 = time.time()

    step("--dry-run writes nothing and calls no launchctl")
    cp = sb.sh(["/bin/sh", str(install), "--dry-run"], check=False)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "DRY RUN" in cp.stdout and "would run:" in cp.stdout
    assert {k: cs.tree_manifest(v) for k, v in watched.items()} == before
    assert not [c for c in sb.calls() if c["t"] > t0]

    step("install: the watcher is a copy in the state dir, the plist lints and loads")
    cp = sb.sh(["/bin/sh", str(install)], check=False)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    copy = sb.state_dir / "watcher.sh"
    assert copy.read_bytes() == (install.parent / "watcher.sh").read_bytes()
    assert copy.stat().st_mode & 0o777 == 0o755
    d = plistlib.loads(sb.watcher_plist.read_bytes())
    assert d["Label"] == cs.WATCHER_LABEL and d["ProgramArguments"] == ["/bin/bash", str(copy)]
    assert d["RunAtLoad"] is True and d["StartInterval"] == 300
    assert d["StandardOutPath"] == str(sb.home / "Library" / "Logs" / "jvn-enricher-cutover.log")
    assert sb.loaded_program(cs.WATCHER_LABEL) == "/bin/bash"

    step("its RunAtLoad fire ran the installed watcher: not merged yet")
    log = sb.home / "Library" / "Logs" / "jvn-enricher-cutover.log"
    cs.wait_for(lambda: log.exists() and "not merged yet" in log.read_text(), 30,
                "the watcher's first fire to log 'not merged yet'")

    step("refuses to arm again after DONE")
    (sb.state_dir / "state.json").write_text(
        json.dumps({"phase": "DONE"}, indent=2, sort_keys=True) + "\n")
    cp = sb.sh(["/bin/sh", str(install)], check=False)
    assert cp.returncode == 1 and "already DONE" in cp.stderr, cp.stdout + cp.stderr
    assert os.path.exists(sb.watcher_plist)


def test_wt07_offline_resumes_a_mid_flight_cutover(make_sandbox, step):
    sb = make_sandbox()
    sb.env["FAKE_KILL_CALLER_ON_LOAD"] = str(sb.new_enricher)
    step("a cutover is SIGKILLed between the plist switch and the load: no worker runs")
    cp = sb.run_cutover("--run", label="killed after the switch")
    assert cp.returncode == -9, sb.output()
    assert sb.state()["phase"] == "SWAPPING", sb.output()
    assert cs.ENRICHER_LABEL not in sb.launchd_state(), "something is loaded"
    del sb.env["FAKE_KILL_CALLER_ON_LOAD"]

    step("the watcher fires while JVN is unreachable (the remote is gone)")
    shutil.move(str(sb.jvn_remote), str(sb.root / "jvn-remote-gone.git"))
    cp = sb.run_watcher(label="offline resume")
    assert cp.returncode == 0, sb.output()
    assert ("fetch failed; the cutover is mid-flight (SWAPPING), resuming it from the last "
            "fetched main") in cp.stdout, sb.output()
    assert "-> continue_swap" in cp.stdout, sb.output()
    st = sb.state()
    assert st["phase"] == "DONE", sb.output()
    assert st["first_tick"]["status"] == "ok"
    assert sb.loaded_program() == str(sb.new_enricher / cs.WRAPPER_REL)

    step("the cutover dropped the lock the watcher handed it through exec")
    assert not (sb.state_dir / "watcher.lock").exists()
