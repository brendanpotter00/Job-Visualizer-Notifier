"""CO-04 / CO-05 / CO-06 — what the cutover is allowed to put in prod.

CO-04  no JVN commit carries the old prod's tree  -> REFUSE (exit 20), nothing touched
CO-05  the old prod has a tracked modification     -> REFUSE (exit 20), nothing touched
CO-06  no enricher-prod-* tag, but a commit in history matches -> found by the walk, DONE
"""

from __future__ import annotations

import time

import pytest

import cutover_sandbox as cs


def _assert_refused_untouched(sb: cs.Sandbox, t0: float, why: str) -> None:
    st = sb.state()
    assert st.get("phase") == "FAILED", sb.output()
    assert why in st.get("failed_reason", ""), st.get("failed_reason")
    assert not [c for c in sb.lifecycle_calls() if c["t"] > t0], "launchd was touched"
    assert sb.plist.read_bytes() == sb.plist_orig
    assert (sb.old / ".checkout-role").read_text() == "prod\n"
    assert sb.loaded_program() == str(sb.old / cs.WRAPPER_REL)
    assert not st.get("our_lock_payloads"), "it tried to park before refusing"
    assert not sb.new.exists(), "a new prod was created"
    texts = sb.texts()
    assert len(texts) == 1 and "FAILED" in texts[0], texts


@pytest.mark.fast
def test_co04_no_matching_ref_refuses(make_sandbox, step):
    sb = make_sandbox(jvn_tree_variant=True, interval_s=3600)
    t0 = time.time()
    step("running the cutover against a JVN whose every commit differs from prod")
    cp = sb.run_cutover("--run", label="no matching ref")
    assert cp.returncode == 20, sb.output()
    step("refused, with nothing in the old prod or the plist changed")
    _assert_refused_untouched(sb, t0, f"no JVN ref has src/enricher == the old prod tree {sb.old_tree}")
    sb.assert_old_prod_as_found()


@pytest.mark.fast
def test_co05_dirty_old_prod_refuses(make_sandbox, step):
    sb = make_sandbox(interval_s=3600)
    readme = sb.old / "README.md"
    edited = readme.read_text() + "\nA hand edit in prod.\n"
    readme.write_text(edited)
    t0 = time.time()
    step("running the cutover with a tracked change in the old prod")
    cp = sb.run_cutover("--run", label="dirty old prod")
    assert cp.returncode == 20, sb.output()
    step("refused, and the hand edit is still there, untouched")
    _assert_refused_untouched(sb, t0, "old_prod_clean: 1 tracked change(s)")
    assert readme.read_text() == edited


def test_co06_history_walk_finds_untagged_commit(make_sandbox, step):
    sb = make_sandbox(tag=False)
    step("running the cutover against a JVN with no enricher-prod-* tag")
    cp = sb.run_cutover("--run", label="history walk")
    assert cp.returncode == 0, sb.output()
    st = sb.state()
    assert st["phase"] == "DONE", sb.output()
    step("the ref came from the history walk and the new prod sits on that commit")
    assert (st["ref_source"], st["ref"], st["commit"]) == ("history", sb.jvn_prod_commit,
                                                           sb.jvn_prod_commit)
    assert "(found by history)" in cp.stdout
    assert sb.git(sb.new, "rev-parse", "HEAD").strip() == sb.jvn_prod_commit
    assert sb.state()["first_tick"]["status"] == "ok"
