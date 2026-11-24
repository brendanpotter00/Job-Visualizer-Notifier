"""CO-18 / CO-19 — the new prod's FIRST tick dies unclosed (beyond the plan's CO list).

A tick whose wrapper is SIGKILLed (or lost to a reboot / power loss) stays
``running`` in the DB forever: nothing reaps it, and the live DB carries several
such rows. Phase E must judge the NEXT tick instead of waiting on that one into
the hard cap and rolling a healthy cutover back.

CO-18  a power loss mid first tick kills the cutover AND the tick; after the
       "reboot" (the dead tick's lock and row now predate the boot) the resumed
       cutover finds the tick orphaned by the boot rule, waits for the next one,
       judges it ok -> DONE.
CO-19  the wrapper alone is SIGKILLed while the cutover waits; 3 h later (aged
       here) the worker reclaims the dead holder's lock and runs the next tick;
       the later-tick rule hands phase E over to it -> DONE.
"""

from __future__ import annotations

import os
import signal
import sqlite3

import cutover_sandbox as cs

PRE_BOOT_EPOCH = 1_000_000_000  # 2001-09-09: before any boot of this machine
PRE_BOOT_ISO = "2001-09-09T01:46:40Z"


def _first_new_tick(sb: cs.Sandbox) -> int:
    return cs.wait_for(lambda: next((e["tick"] for e in sb.events()
                                     if e["ev"] == "acquire" and e["role"] == "NEW"), None),
                       60, "the new prod's first tick to start")


def _sigkill_running_job(sb: cs.Sandbox, tick: int) -> None:
    """SIGKILL the running enricher job's whole process group (wrapper + uv +
    python), the way a power loss stops it: no EXIT trap, no tick-end."""
    job = cs.wait_for(lambda: (sb.launchd_state().get(cs.ENRICHER_LABEL) or {}).get("job_pid"),
                      30, "launchd's running job pid")
    os.killpg(int(job), signal.SIGKILL)
    cs.wait_for(lambda: any(j.get("event") == "end" and j.get("pid") == job for j in sb.jobs()),
                30, "the killed job to be reaped")
    rows = {t["id"]: t for t in sb.ticks(sb.new_enricher)}
    assert rows[tick]["status"] == "running", rows.get(tick)


def _set_lock_mtime(sb: cs.Sandbox, epoch: float) -> None:
    lock = sb.new_enricher / "data" / ".tick.lock"
    assert lock.exists(), "the killed tick left no lock behind"
    os.utime(lock, (epoch, epoch))


def test_co18_reboot_mid_first_tick_resumes_and_judges_the_next_tick(make_sandbox, step):
    sb = make_sandbox(control={"NEW_TICK_S": "600"})
    step("the cutover swaps; the new prod's first tick runs long")
    bg = sb.start_cutover("--run", label="killed by the power loss")
    try:
        first = _first_new_tick(sb)
        step(f"power loss mid tick #{first}: the cutover and the tick die (SIGKILL)")
        sb.set_control(NEW_START="0")  # the machine is off: no tick until "login"
        bg["proc"].kill()
        _sigkill_running_job(sb, first)
    finally:
        cp = sb.finish_cutover(bg, timeout=30)
    assert cp.returncode == -9, sb.output()
    assert sb.state()["phase"] == "SWAPPED", sb.output()

    step("the reboot: the dead tick's lock and its row now predate the current boot")
    _set_lock_mtime(sb, PRE_BOOT_EPOCH)
    conn = sqlite3.connect(sb.new_enricher / "data" / "enricher.db")
    conn.execute("UPDATE ticks SET started_at = ? WHERE id = ?", (PRE_BOOT_ISO, first))
    conn.commit()
    conn.close()

    step("after login the cutover resumes and finds the tick orphaned (boot rule)")
    bg = sb.start_cutover("--run", label="resume after the reboot")
    try:
        cs.wait_for(lambda: sb.history(f"first tick #{first} orphaned (it started before "
                                       "the current boot)"), 60, "phase E to skip the dead tick")
        step("the worker ticks again (login): its first tick closes ok")
        sb.set_control(NEW_START="1", NEW_TICK_S="1")
    finally:
        cp = sb.finish_cutover(bg, timeout=120)
    assert cp.returncode == 0, sb.output()
    st = sb.state()
    assert st["phase"] == "DONE", sb.output()
    assert "-> continue_swap" in cp.stdout and "C: copy state" not in cp.stdout, sb.output()
    assert f"E: tick #{first} can never close" in cp.stdout, sb.output()
    assert st["orphaned_first_ticks"] == [first]
    assert st["first_tick"]["id"] > first and st["first_tick"]["status"] == "ok", st["first_tick"]

    step("the new worker owns prod; one text, DONE")
    assert sb.loaded_program() == str(sb.new_enricher / cs.WRAPPER_REL)
    assert (sb.old / ".checkout-role").read_text() == "retired\n"
    texts = sb.texts()
    assert len(texts) == 1 and "DONE" in texts[0], texts


def test_co19_first_tick_sigkilled_while_the_cutover_waits(make_sandbox, step):
    sb = make_sandbox(control={"NEW_TICK_S": "600"})
    step("the cutover swaps and waits on the new prod's first tick")
    bg = sb.start_cutover("--run", label="first tick SIGKILLed")
    try:
        first = _first_new_tick(sb)
        step(f"tick #{first}'s wrapper is SIGKILLed; the cutover keeps waiting")
        _sigkill_running_job(sb, first)
        sb.set_control(NEW_TICK_S="1")
        step("3 h later (aged here) the worker reclaims the dead holder's lock and ticks")
        _set_lock_mtime(sb, os.path.getmtime(sb.new_enricher / "data" / ".tick.lock") - 4 * 3600)
        cp = sb.finish_cutover(bg, timeout=120)
    finally:
        if bg["proc"].poll() is None:
            bg["proc"].kill()
    assert cp.returncode == 0, sb.output()
    st = sb.state()
    assert st["phase"] == "DONE", sb.output()
    assert st["orphaned_first_ticks"] == [first]
    assert sb.history(f"first tick #{first} orphaned (tick #{first + 1} started after it)") == 1
    assert st["first_tick"]["id"] == first + 1 and st["first_tick"]["status"] == "ok"
    assert "rollback" not in cp.stdout.lower(), sb.output()
    texts = sb.texts()
    assert len(texts) == 1 and "DONE" in texts[0], texts
