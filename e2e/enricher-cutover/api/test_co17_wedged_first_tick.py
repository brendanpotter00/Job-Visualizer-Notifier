"""CO-17 — the new prod's FIRST tick runs on and on (beyond the plan's CO list).

It keeps writing progress rows, so phase E EXTENDS its close deadline while it
progresses — until the hard cap. Then the rollback cannot park the new prod at
idle (the tick never ends), so it takes the force path in the sleep-socket-hang
runbook order: SIGTERM the tick's python stage (not the wrapper), which lets the
wrapper still close the tick and release the lock; THEN park, copy the DB back
(no lost work) and restore the old prod.
"""

from __future__ import annotations

import cutover_sandbox as cs


def test_co17_wedged_first_tick_hits_the_hard_cap_and_rolls_back(make_sandbox, step):
    sb = make_sandbox(control={"NEW_TICK_S": "600"})
    step("running the cutover; the new prod's first tick never finishes on its own")
    cp = sb.run_cutover("--run", label="wedged first tick", env_extra={
        "CUTOVER_FIRST_TICK_CLOSE_S": "3", "CUTOVER_PROGRESS_WINDOW_S": "2",
        "CUTOVER_FIRST_TICK_HARD_CAP_S": "8", "CUTOVER_ROLLBACK_PARK_BUDGET_S": "2"})
    assert cp.returncode == 30, sb.output()
    st = sb.state()
    assert st["phase"] == "ROLLED_BACK", sb.output()

    step("phase E extended the deadline while the tick progressed, then hit the hard cap")
    assert "still progressing (last DB write" in cp.stdout, sb.output()
    assert "still running after the 8s hard cap" in st["rollback_reason"], st["rollback_reason"]

    step("the rollback TERMed the python stage only, and the wrapper closed the tick itself")
    first = st["first_tick_id"]
    assert "rollback: new prod tick wedged; TERM python stage pid(s) [" in cp.stdout
    assert "TERM python stage pid(s) []" not in cp.stdout, "no python stage was found to TERM"
    assert "still wedged; unloading and TERMing the wrapper" not in cp.stdout, \
        "it escalated past the python stage"
    ends = [e for e in sb.events() if e["ev"] == "end" and e.get("tick") == first]
    assert ends and ends[0]["role"] == "NEW", f"the wedged tick #{first} was not closed: {ends}"
    assert not [e for e in sb.events() if e["ev"] == "killed"], "the wrapper itself was killed"

    step("no lost work: the closed tick is in the old prod's DB; everything else restored")
    old = {t["id"]: t for t in sb.ticks(sb.old)}
    assert first in old and old[first]["status"] == "ok", old.get(first)
    assert st["rollback_db_copied"] is True
    assert sb.plist.read_bytes() == sb.plist_orig
    assert sb.loaded_program() == str(sb.old / cs.WRAPPER_REL)
    assert (sb.old / ".checkout-role").read_text() == "prod\n"
    texts = sb.texts()
    assert len(texts) == 1 and "ROLLED BACK" in texts[0], texts
