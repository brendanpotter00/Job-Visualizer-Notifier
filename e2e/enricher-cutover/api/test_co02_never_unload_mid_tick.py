"""CO-02 — the cutover never unloads the worker in the middle of a tick.

A 6-second tick is in flight when the cutover starts. The stub launchd is run
both ways a real unload could behave: ``FAKE_UNLOAD_KILLS=1`` SIGTERMs a running
job (what the real label's 5 s exit timeout does), ``0`` leaves it running. In
both, the unload must come only after that tick's wrapper EXITED and while the
cutover held the tick lock — so the tick closes ``ok`` and nothing is killed.

Proven to bite (PLAN.md §6): unloading before parking turns this red in both modes.
"""

from __future__ import annotations

import time

import pytest

import cutover_sandbox as cs


@pytest.mark.parametrize("unload_kills", ["1", "0"], ids=["unload-kills", "unload-leaves"])
def test_co02_never_unloads_mid_tick(make_sandbox, step, unload_kills):
    sb = make_sandbox(control={"OLD_TICK_S": "6"},
                      extra_env={"FAKE_UNLOAD_KILLS": unload_kills})

    step("waiting for an old-prod tick to be in flight")
    acq = cs.wait_for(lambda: [e for e in sb.events() if e["ev"] == "acquire" and e["role"] == "OLD"],
                      20, "the old worker to start a tick")[0]
    tick_id = acq["tick"]
    t0 = time.time()

    step(f"running the cutover while tick #{tick_id} runs (FAKE_UNLOAD_KILLS={unload_kills})")
    cp = sb.run_cutover("--run", label="mid-tick start")
    assert cp.returncode == 0, sb.output()
    assert sb.state().get("phase") == "DONE", sb.output()

    step(f"tick #{tick_id} finished on its own and closed ok")
    end = [e for e in sb.events() if e["ev"] == "end" and e.get("tick") == tick_id
           and e["role"] == "OLD"]
    assert end and end[0]["status"] == "ok", f"tick #{tick_id} did not close ok: {end}"
    assert not [e for e in sb.events() if e["ev"] == "killed"], "a wrapper was SIGTERMed mid-tick"
    old = {t["id"]: t for t in sb.ticks(sb.old)}
    assert old[tick_id]["status"] == "ok"
    wrapper_pid = int(end[0]["owner"])
    job_end = [j for j in sb.jobs() if j["event"] == "end" and j["pid"] == wrapper_pid]
    assert job_end and job_end[0]["rc"] == 0, f"the in-flight wrapper's exit: {job_end}"

    step("the cutover saw the tick in flight and waited for it")
    assert "lock held (live" in cp.stdout, "the cutover never saw the tick in flight:\n" + sb.output()

    step("the unload came after that wrapper exited, with the lock held by the cutover")
    unloads = [c for c in sb.lifecycle_calls() if c["t"] > t0 and c["argv"][0] == "unload"]
    assert len(unloads) == 1, unloads
    u = unloads[0]
    assert u["t"] > job_end[0]["t"], (
        f"unload at {u['t']:.3f} came before the in-flight wrapper exited at {job_end[0]['t']:.3f}")
    assert u["job_running"] is False, "a job was running at the unload"
    assert u["lock"] == sb.state()["old_lock_payload"], f"lock at unload: {u['lock']!r}"
