"""CO-12 / CO-13 / CO-16.

CO-12  every retirement step that talks to the outside fails (``gh`` exits 1, the
       job-enricher remote rejects the banner push, ``send.sh`` fails) -> still
       ``DONE`` (exit 0): retirement is best effort and never rolls back, and each
       failure is named in the log and the state.
CO-13  an ORPHANED tick lock (dead pid, no wrapper running — what a SIGKILLed
       wrapper leaves; the worker itself waits 3 h on it) -> the cutover reclaims
       it and proceeds.
CO-16  the copy is not faithful: a rogue writer (started by a git stub at phase
       C's untracked scan) keeps writing the old prod's DB while it is backed up,
       so the copy's row counts lag the source's -> unpark (lock released, the
       worker reloaded exactly as found) and refuse, exit 20.
"""

from __future__ import annotations

import os
import subprocess
import time

import cutover_sandbox as cs


def test_co12_retirement_failures_still_done(make_sandbox, step):
    sb = make_sandbox()
    hook = sb.je_remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'e2e: this remote rejects every push' >&2\nexit 1\n")
    hook.chmod(0o755)
    readme_before = sb.sh([sb.host.git, "--git-dir", str(sb.je_remote), "show", "main:README.md"]).stdout
    sb.env.update(FAKE_GH_EXIT="1", FAKE_SEND_EXIT="1")

    step("running the cutover with gh, the banner push and send.sh all failing")
    cp = sb.run_cutover("--run", label="retirement failures")
    assert cp.returncode == 0, sb.output()
    st = sb.state()
    assert st["phase"] == "DONE", sb.output()

    step("each failure is recorded and named in the log; the rest of F still ran")
    r = st["retire"]
    assert r["banner"].startswith("error: push rejected"), r
    assert r["archive"].startswith("error: gh repo archive"), r
    for ok_step in ("markers_old_prod", "markers_old_dev", "bundle"):
        assert r[ok_step].startswith("ok"), r
    assert st["notified"]["DONE"]["sent"] is False
    log = sb.cutover_log()
    for needle in ("F: banner: error: push rejected", "F: archive: error: gh repo archive",
                   "text 'DONE': send.sh failed (1)"):
        assert needle in log, needle
    assert sb.gh_calls() == [f"repo archive {cs.OLD_REPO_SLUG} --yes"]
    assert len(sb.texts()) == 1, "send.sh was not even tried"
    after = sb.sh([sb.host.git, "--git-dir", str(sb.je_remote), "show", "main:README.md"]).stdout
    assert after == readme_before, "the rejected push changed the remote"
    assert (sb.old / ".checkout-role").read_text() == "retired\n"
    assert sb.loaded_program() == str(sb.new_enricher / cs.WRAPPER_REL)


def test_co13_orphan_lock_is_reclaimed(make_sandbox, step):
    sb = make_sandbox()
    step("leaving an orphaned lock: a dead pid, written after boot")
    cs.wait_for(lambda: [e for e in sb.events() if e["ev"] == "end" and e["role"] == "OLD"],
                20, "an old-prod tick to finish")
    sb.set_control(OLD_START="0")  # hold the fires off while the orphan is planted
    wrapper = str(sb.old / cs.WRAPPER_REL)
    cs.wait_for(lambda: sb.lock_text(sb.old) is None
                and not [c for _p, _g, c in cs.processes() if wrapper in c],
                20, "the old worker to be idle")
    dead = subprocess.Popen(["/usr/bin/true"])
    dead.wait()
    try:
        os.kill(dead.pid, 0)
        raise AssertionError(f"pid {dead.pid} was reused already; rerun")
    except ProcessLookupError:
        pass
    lock = sb.old / "data" / ".tick.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    os.write(fd, f"{dead.pid}|2026-11-23T00:00:00Z".encode())
    os.close(fd)
    orphan = lock.read_text()
    sb.set_control(OLD_START="1")
    cs.wait_for(lambda: [e for e in sb.events() if e["ev"] == "skip" and e["role"] == "OLD"
                         and "holder is gone" in e.get("reason", "")],
                20, "the old worker to start skipping on the orphan (it waits 3 h)")

    step("running the cutover: it must reclaim the orphan and proceed")
    cp = sb.run_cutover("--run", label="orphan lock")
    assert cp.returncode == 0, sb.output()
    st = sb.state()
    assert st["phase"] == "DONE", sb.output()
    assert f"reclaimed an orphaned lock (pid={dead.pid} dead, no wrapper running)" in cp.stdout, \
        sb.output()
    assert "(reclaimed orphan lock)" in cp.stdout
    unload = [c for c in sb.lifecycle_calls() if c["argv"][0] == "unload"][0]
    assert unload["lock"] == st["old_lock_payload"] != orphan


def test_co16_unfaithful_copy_unparks_and_refuses(make_sandbox, step):
    sb = make_sandbox()
    sb.env.update(CUTOVER_GIT_BIN=str(sb.bin / "git_rogue"), FAKE_ROGUE_S="8")
    t0 = time.time()

    step("running the cutover while a rogue process writes the old prod's DB")
    cp = sb.run_cutover("--run", label="copy differs")
    assert cp.returncode == 20, sb.output()
    st = sb.state()
    assert st["phase"] == "FAILED", sb.output()
    assert "copied data/enricher.db differs: row counts differ in: enrichments" in st["failed_reason"], \
        st["failed_reason"]
    assert (sb.launchd / "rogue-started").read_text() == "writing\n", "the rogue never wrote"

    step("unparked exactly as found: lock released, worker reloaded, plist + roles untouched")
    verbs = [(c["argv"][0], c.get("workdir")) for c in sb.lifecycle_calls() if c["t"] > t0]
    assert verbs == [("unload", str(sb.old)), ("load", str(sb.old))], verbs
    assert st.get("unloaded_by_us") is False
    sb.assert_old_prod_as_found()
    for p in (sb.new / ".checkout-role", sb.new_enricher / ".checkout-role"):
        assert p.read_text() == "failed-cutover\n", p
    texts = sb.texts()
    assert len(texts) == 1 and "FAILED" in texts[0] and "row counts differ" in texts[0], texts

    step("the old worker ticks again")
    cs.wait_for(lambda: any(e["ev"] == "end" and e["role"] == "OLD" and e["t"] > t0
                            for e in sb.events()),
                30, "an old-prod tick after the unpark")
