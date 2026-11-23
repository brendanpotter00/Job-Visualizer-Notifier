"""CO-03 — a wedged tick: the park budget runs out with the tick still running.

The cutover must change nothing (plist, launchd, roles), leave the tick's lock
alone, exit 10 (deferred), and text Brendan exactly ONCE. Once the tick ends,
the next run redoes the cutover from scratch and finishes.
"""

from __future__ import annotations

import time

import cutover_sandbox as cs


def test_co03_wedged_tick_defers_then_completes(make_sandbox, step):
    sb = make_sandbox(control={"OLD_TICK_S": "600"})

    step("waiting for a tick that will not end on its own")
    acq = cs.wait_for(lambda: [e for e in sb.events() if e["ev"] == "acquire" and e["role"] == "OLD"],
                      20, "the old worker to start a tick")[0]
    t0 = time.time()

    step("running the cutover with a 3 s park budget")
    cp = sb.run_cutover("--run", env_extra={"CUTOVER_PARK_BUDGET_S": "3"}, label="wedged")
    assert cp.returncode == 10, sb.output()
    st = sb.state()
    assert st["phase"] == "PENDING" and st["deferrals"] == 1, st.get("phase")
    assert "park budget exhausted" in st["last_deferral"]["reason"]

    step("nothing changed: plist, launchd, roles, and the tick's own lock")
    assert sb.lifecycle_calls() and not [c for c in sb.lifecycle_calls() if c["t"] > t0], \
        "launchd was touched"
    sb.assert_old_prod_as_found()
    lock = sb.lock_text(sb.old)
    assert lock is not None, "the wedged tick's lock vanished"
    holder = int(lock.split("|")[0])
    assert any(pid == holder and cs.WRAPPER_REL in cmd for pid, _pg, cmd in cs.processes()), \
        f"the lock is not the running wrapper's any more: {lock!r}"
    assert (sb.new / ".cutover-owned").is_file(), "phase A's clone should be left for the redo"

    step("exactly one text, naming the wedge")
    texts = sb.texts()
    assert len(texts) == 1 and "looks wedged" in texts[0], texts
    assert not [e for e in sb.events() if e["ev"] == "end" and e.get("tick") == acq["tick"]]

    step("the tick ends; the next run redoes the cutover and finishes")
    sb.set_control(OLD_TICK_S="1")
    cs.wait_for(lambda: [e for e in sb.events() if e["ev"] == "end" and e.get("tick") == acq["tick"]],
                20, "the unwedged tick to close")
    cp = sb.run_cutover("--run", label="after the wedge")
    assert cp.returncode == 0, sb.output()
    assert sb.state()["phase"] == "DONE", sb.output()
    assert "removing the half-built new prod" in cp.stdout, sb.output()
    texts = sb.texts()
    assert len(texts) == 2 and sum("looks wedged" in t for t in texts) == 1 and "DONE" in texts[1], texts
