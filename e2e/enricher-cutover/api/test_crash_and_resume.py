"""CO-09 — the cutover is SIGKILLed mid-flight and the next run resumes.

(a) killed after the copy, BEFORE the plist write (the stub plutil kills its
    caller on phase D's lint): the rerun redoes A-C from scratch, deleting only
    the half-built new prod (it carries ``.cutover-owned``).
(b) killed AFTER the plist write, before ``launchctl load`` (the stub launchctl
    kills its caller instead of loading the new plist): the rerun continues the
    swap and the verification and does NOT copy the database again.
"""

from __future__ import annotations

import cutover_sandbox as cs


def test_co09_crash_before_switch_redoes_a_to_c(make_sandbox, step):
    sb = make_sandbox()
    sb.env.update(CUTOVER_PLUTIL_BIN=str(sb.bin / "plutil_crash"), FAKE_PLUTIL_KILL_ON_CALL="2")

    step("running the cutover; it is SIGKILLed at phase D's plist lint")
    cp = sb.run_cutover("--run", label="killed before the switch")
    assert cp.returncode == -9, sb.output()
    st = sb.state()
    assert st["phase"] == "SWAPPING", st["phase"]
    assert sb.plist.read_bytes() == sb.plist_orig, "the switch happened before the kill"
    assert (sb.new / ".cutover-owned").is_file()
    assert (sb.old / ".checkout-role").read_text() == "retiring\n", "phase D had started"
    sentinel = sb.new / "CRASH-SENTINEL"
    sentinel.write_text("this half-built prod must be deleted, not reused\n")
    old_dev_head = sb.git(sb.old_dev, "rev-parse", "HEAD").strip()

    step("rerunning: it redoes A-C (deleting only the owned dir) and finishes")
    cp = sb.run_cutover("--run", label="resume after the kill")
    assert cp.returncode == 0, sb.output()
    assert sb.state()["phase"] == "DONE", sb.output()
    assert "-> redo" in cp.stdout and "removing the half-built new prod" in cp.stdout, sb.output()
    assert not sentinel.exists(), "the half-built new prod was reused"
    assert (sb.new / ".cutover-swapped").is_file()
    assert sb.git(sb.old, "rev-parse", "HEAD").strip() == sb.old_head
    assert sb.git(sb.old_dev, "rev-parse", "HEAD").strip() == old_dev_head
    assert "took back our own earlier lock" in cp.stdout, "the dead run's lock was not reclaimed"
    texts = sb.texts()
    assert len(texts) == 1 and "DONE" in texts[0], texts


def test_co09_crash_after_switch_continues_without_recopy(make_sandbox, step):
    sb = make_sandbox()
    sb.env["FAKE_KILL_CALLER_ON_LOAD"] = str(sb.new_enricher)

    step("running the cutover; it is SIGKILLed between the plist write and the load")
    cp = sb.run_cutover("--run", label="killed after the switch")
    assert cp.returncode == -9, sb.output()
    st = sb.state()
    assert st["phase"] == "SWAPPING", st["phase"]
    assert str(sb.new_enricher).encode() in sb.plist.read_bytes(), "the plist was not switched"
    assert cs.ENRICHER_LABEL not in sb.launchd_state(), "something is loaded"
    db = sb.new_enricher / "data" / "enricher.db"
    inode, copies = db.stat().st_ino, sb.history("phase -> COPIED")
    assert copies == 1

    step("rerunning: it continues the swap + verification and never re-copies")
    cp = sb.run_cutover("--run", label="resume after the switch")
    assert cp.returncode == 0, sb.output()
    st = sb.state()
    assert st["phase"] == "DONE", sb.output()
    assert "-> continue_swap" in cp.stdout and "C: copy state" not in cp.stdout, sb.output()
    assert db.stat().st_ino == inode, "the new prod DB was replaced (re-copied)"
    assert sb.history("phase -> COPIED") == 1
    assert st["first_tick"]["status"] == "ok"
    assert sb.loaded_program() == str(sb.new_enricher / cs.WRAPPER_REL)
