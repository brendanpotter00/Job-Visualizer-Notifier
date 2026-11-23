"""CO-10 / CO-11 — the checks that run before anything is touched.

CO-10  the interpreter named by the old prod's ``.venv/pyvenv.cfg`` is gone ->
       REFUSE in phase A (exit 20), before the worker is parked.
CO-11  ``--preflight`` (what the orchestrator runs on the real machine before
       the merge) is strictly read-only: every file under the fake HOME, both
       remotes and the sandbox TMPDIR hashes the same before and after, the state
       dir is never created, launchd only sees ``list``/``print``; exit 0 with a
       full report.
"""

from __future__ import annotations

import json
import time

import pytest

import cutover_sandbox as cs


@pytest.mark.fast
def test_co10_missing_interpreter_refuses_before_parking(make_sandbox, step):
    sb = make_sandbox(interval_s=3600)  # no fires: nothing may rebuild the old venv meanwhile
    cfg = sb.old / ".venv" / "pyvenv.cfg"
    lines = cfg.read_text().splitlines()
    cfg.write_text("\n".join("home = /nonexistent/e2e-python/bin" if ln.startswith("home")
                             else ln for ln in lines) + "\n")
    t0 = time.time()

    step("running the cutover with the old prod's base interpreter missing")
    cp = sb.run_cutover("--run", label="interpreter missing")
    assert cp.returncode == 20, sb.output()
    st = sb.state()
    assert st["phase"] == "FAILED", sb.output()
    assert "interpreter: interpreter /nonexistent/e2e-python/bin/python3" in st["failed_reason"], \
        st["failed_reason"]

    step("refused in phase A: never parked, launchd untouched, no new prod")
    assert not st.get("our_lock_payloads") and sb.lock_text(sb.old) is None
    assert not [c for c in sb.lifecycle_calls() if c["t"] > t0], "launchd was touched"
    assert sb.plist.read_bytes() == sb.plist_orig and not sb.new.exists()
    assert sb.loaded_program() == str(sb.old / cs.WRAPPER_REL)
    assert "PARKED" not in json.dumps(st.get("history", []))


@pytest.mark.fast
def test_co11_preflight_is_read_only(make_sandbox, step):
    sb = make_sandbox(interval_s=3600)  # the worker is loaded but idle: nothing else writes
    watched = {"home": sb.home, "je-remote": sb.je_remote, "jvn-remote": sb.jvn_remote,
               "tmp": sb.tmp}
    before = {k: cs.tree_manifest(v) for k, v in watched.items()}
    assert not sb.state_dir.exists()
    t0 = time.time()

    step("--preflight (human report)")
    cp = sb.run_cutover("--preflight", label="preflight")
    assert cp.returncode == 0, sb.output()
    assert "preflight: PASS" in cp.stdout, sb.output()
    assert "[FAIL]" not in cp.stdout and "[warn]" not in cp.stdout, sb.output()

    step("--preflight --json")
    cp = sb.run_cutover("--preflight", "--json", label="preflight --json")
    assert cp.returncode == 0, sb.output()
    rep = json.loads(cp.stdout)
    checks = {c["name"]: c for c in rep["checks"]}
    assert rep["ok"] is True
    for name in ("old_prod_exists", "old_prod_role", "old_prod_clean", "old_prod_tree",
                 "db_readable", "free_space", "interpreter", "uv", "plist", "launchd",
                 "new_prod_path", "ref", "jvn_reachable", "tag_on_remote",
                 "job_enricher_reachable", "gh_auth", "send_sh"):
        assert checks[name]["ok"], (name, checks[name])
    assert rep["ref"]["ref"] == cs.FAKE_TAG and rep["ref"]["commit"] == sb.jvn_prod_commit
    assert "contains" in checks["merged"]["detail"]
    assert {i["path"] for i in rep["untracked_copy"]} >= {".env.local", "data/classify-run-t1.log",
                                                         "data/enricher.db"}
    assert cs.CANARY not in cp.stdout + cp.stderr

    step("nothing was written anywhere, and launchd only answered questions")
    after = {k: cs.tree_manifest(v) for k, v in watched.items()}
    for k in watched:
        changed = sorted(set(before[k].items()) ^ set(after[k].items()))
        assert not changed, f"--preflight changed {k}: {changed[:10]}"
    assert not sb.state_dir.exists(), "--preflight created the state dir"
    verbs = {c["argv"][0] for c in sb.calls() if c["t"] > t0}
    assert verbs <= {"list", "print"}, verbs
    assert sb.gh_calls() == ["auth status", "auth status"] and sb.texts() == []
