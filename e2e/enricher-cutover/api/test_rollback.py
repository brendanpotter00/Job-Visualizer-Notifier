"""CO-07 / CO-08 — a failed first tick in the new prod rolls everything back.

CO-07  the first tick closes ``error`` -> rollback WITH a DB copy-back: the new
       prod's ticks land in the old prod's DB (no lost work), the original plist
       bytes are restored, the old worker runs again, exit 30, one text, and the
       watcher retires itself on its next fire.
       Proven to bite (PLAN.md §6): skipping the copy-back turns this red.
CO-08  the first tick never starts -> rollback WITHOUT a copy-back (the new DB is
       byte-for-byte the copy, so the old prod's DB is left as it was).
"""

from __future__ import annotations

import time

import cutover_sandbox as cs


def _assert_rolled_back(sb: cs.Sandbox, *, copied: bool) -> dict:
    st = sb.state()
    assert st.get("phase") == "ROLLED_BACK", sb.output()
    assert bool(st.get("rollback_db_copied")) is copied, (
        f"rollback_db_copied={st.get('rollback_db_copied')!r}, expected {copied}: "
        + ("the new prod's work was NOT copied back (lost)" if copied else "it copied back anyway"))
    assert sb.plist.read_bytes() == sb.plist_orig, "the original plist bytes were not restored"
    assert sb.loaded_program() == str(sb.old / cs.WRAPPER_REL), sb.loaded_program()
    assert (sb.old / ".checkout-role").read_text() == "prod\n"
    for p in (sb.new / ".checkout-role", sb.new_enricher / ".checkout-role"):
        assert p.read_text() == "failed-cutover\n", p
    ours = set(st.get("our_lock_payloads", []))
    for ck in (sb.old, sb.new_enricher):
        assert sb.lock_text(ck) not in ours or sb.lock_text(ck) is None, f"our lock left in {ck}"
    texts = sb.texts()
    assert len(texts) == 1 and "ROLLED BACK" in texts[0], texts
    assert ("copied back: yes" if copied else "copied back: no") in texts[0], texts
    return st


def test_co07_first_tick_error_rolls_back_with_copy_back(make_sandbox, step):
    sb = make_sandbox(control={"NEW_STATUS": "error"})
    step("running the cutover; the new prod's first tick will close error")
    cp = sb.run_cutover("--run", label="first tick error")
    assert cp.returncode == 30, sb.output()

    step("rolled back: plist bytes, launchd, roles, locks, one text")
    st = _assert_rolled_back(sb, copied=True)
    assert "closed status='error'" in st["rollback_reason"], st["rollback_reason"]

    step("no lost work: the new prod's ticks are in the old prod's DB now")
    first = st["first_tick_id"]
    old = {t["id"]: t for t in sb.ticks(sb.old)}
    assert first in old and old[first]["status"] == "error", f"tick #{first} not copied back: {old}"
    stale = sorted(sb.old.glob("data/enricher.db.pre-rollback-*"))
    assert stale, "the stale old DB was not kept"
    assert "rollback: copied the new prod DB back" in cp.stdout

    step("the old worker runs again on the copied-back DB")
    cs.wait_for(lambda: any(t["id"] > first and t["status"] == "ok" for t in sb.ticks(sb.old)),
                20, "a new tick in the old prod after the rollback")

    step("the watcher's next fire sees ROLLED_BACK and retires itself")
    t0 = time.time()
    cw = sb.run_watcher(label="watcher after rollback")
    assert cw.returncode == 0 and "cutover is ROLLED_BACK; retiring the watcher" in cw.stdout, sb.output()
    assert "running it" not in cw.stdout
    assert [c["argv"] for c in sb.calls() if c["t"] > t0 and c["argv"][:1] == ["remove"]] == \
        [["remove", cs.WATCHER_LABEL]]


def test_co08_first_tick_never_starts_rolls_back_without_copy(make_sandbox, step):
    sb = make_sandbox(control={"NEW_START": "0"})
    step("running the cutover; the new prod never starts a tick")
    cp = sb.run_cutover("--run", env_extra={"CUTOVER_FIRST_TICK_START_S": "4"},
                        label="first tick never starts")
    assert cp.returncode == 30, sb.output()

    step("rolled back without touching the old prod's DB")
    st = _assert_rolled_back(sb, copied=False)
    assert "no tick started in the new prod" in st["rollback_reason"], st["rollback_reason"]
    assert "no copy-back needed" in cp.stdout, sb.output()
    assert not list(sb.old.glob("data/enricher.db.pre-rollback-*"))
    new_db = (sb.new_enricher / "data" / "enricher.db").read_bytes()
    assert cs.sha256_bytes(new_db) == st["copy_sha256"], "something wrote the new prod DB"
    assert max(t["id"] for t in sb.ticks(sb.new_enricher)) == st["copied_max_tick_id"]
