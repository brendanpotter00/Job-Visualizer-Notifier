"""CO-01 / CO-14 / CO-15 — the happy path, driven the way it runs for real: the
WATCHER sees the merged cutover on (fake) JVN main, extracts it and execs it.

All three cases inspect ONE run (a module-scoped sandbox): CO-01 the end-to-end
result, CO-14 where the canary secret went, CO-15 what a second start does.
"""

from __future__ import annotations

import plistlib
import time

import pytest

import cutover_sandbox as cs


@pytest.fixture(scope="module")
def happy(module_sandbox):
    sb = module_sandbox()
    if not sb.runs:
        cs.wait_for(lambda: any(e["ev"] == "end" and e["role"] == "OLD" for e in sb.events()),
                    20, "the old prod worker to close a tick before the cutover starts")
        sb.ticks_before = sb.ticks(sb.old)
        sb.t_start = time.time()
        sb.run_watcher(label="the merge trigger fires")
    return sb


def test_co01_happy_path_end_to_end(happy, step):
    sb = happy
    step("the watcher found the merged cutover and ran it to DONE")
    r = sb.runs[0]
    assert r["rc"] == 0, sb.output()
    assert f"main {sb.jvn_main} contains the cutover; running it" in r["stdout"], sb.output()
    st = sb.state()
    assert st.get("phase") == "DONE", sb.output()
    assert (st["ref"], st["ref_source"], st["commit"]) == (cs.FAKE_TAG, "tag", sb.jvn_prod_commit)
    assert "Traceback" not in sb.all_output()
    assert not (sb.state_dir / "watcher.lock").exists(), \
        "the cutover left behind the lock the watcher handed it through exec"

    step("park before unload: the old label was unloaded only while the cutover held the lock")
    calls = [c for c in sb.lifecycle_calls() if c["t"] > sb.t_start]
    kinds = [(c["argv"][0], c.get("workdir")) for c in calls]
    assert [k for k, _ in kinds] == ["unload", "load"], kinds
    unload, load = calls
    assert unload["lock"] == st["old_lock_payload"], unload
    assert unload["workdir"] == str(sb.old), unload
    assert not sb.unload_hit_a_tick(unload), f"the unload hit a wrapper that owned a tick: {unload}"
    assert load["workdir"] == str(sb.new_enricher) and unload["t"] < load["t"]

    step("the plist differs from the original by exactly the two old-prod paths")
    new_plist = sb.plist.read_bytes()
    old_b, new_b = str(sb.old).encode(), str(sb.new_enricher).encode()
    assert sb.plist_orig.count(old_b) == 2 and new_plist.count(new_b) == 2
    assert new_plist == sb.plist_orig.replace(old_b, new_b)
    assert (sb.state_dir / "com.bp.job-enricher.plist.orig").read_bytes() == sb.plist_orig
    d_old, d_new = plistlib.loads(sb.plist_orig), plistlib.loads(new_plist)
    for key in ("StartInterval", "RunAtLoad", "EnvironmentVariables", "StandardOutPath",
                "StandardErrorPath", "Label"):
        assert d_old[key] == d_new[key], key
    assert sb.loaded_program() == str(sb.new_enricher / cs.WRAPPER_REL)

    step("the new prod is a clean JVN clone at the prod commit, marked prod + swapped")
    assert sb.git(sb.new, "rev-parse", "HEAD").strip() == sb.jvn_prod_commit
    assert sb.git(sb.new, "rev-parse", "HEAD:src/enricher").strip() == sb.old_tree
    assert sb.git(sb.new, "remote", "get-url", "origin").strip() == str(sb.jvn_remote)
    assert sb.git(sb.new, "status", "--porcelain", "--untracked-files=no").strip() == ""
    assert (sb.new / ".checkout-role").read_text() == "prod\n"
    assert (sb.new_enricher / ".checkout-role").read_text() == "prod\n"
    assert (sb.new / ".cutover-swapped").is_file() and not (sb.new / ".cutover-owned").exists()
    assert not (sb.new / "CLAUDE.local.md").exists(), "an ancestor CLAUDE.local.md would reach prompts"
    assert ((sb.new_enricher / "data" / "classify-run-t1.log").read_bytes()
            == (sb.old / "data" / "classify-run-t1.log").read_bytes())

    step("the database moved with every tick, and the first new tick closed ok")
    old_ticks = {t["id"]: t for t in sb.ticks(sb.old)}
    new_ticks = {t["id"]: t for t in sb.ticks(sb.new_enricher)}
    copied = st["copied_max_tick_id"]
    assert copied >= max(t["id"] for t in sb.ticks_before)
    assert all(new_ticks[i] == old_ticks[i] for i in old_ticks), "a copied tick differs"
    assert max(old_ticks) == copied, "the old prod DB grew after the copy"
    first = st["first_tick"]
    assert first["id"] > copied and first["status"] == "ok" and new_ticks[first["id"]]["status"] == "ok"
    assert cs.sha256_bytes((sb.old / "data" / "enricher.db").read_bytes()) == st["old_db_sha256"]
    assert st["old_db_snapshot"]["max_tick_id"] == copied  # phase E's content tripwire baseline

    step("the new worker keeps ticking under launchd")
    cs.wait_for(lambda: any(t["id"] > first["id"] and t["status"] == "ok"
                            for t in sb.ticks(sb.new_enricher)),
                20, "a second tick in the new prod")

    step("retirement: markers, bundle, banner pushed, repo archived, one text")
    for root in (sb.old, sb.old_dev):
        assert (root / ".checkout-role").read_text() == "retired\n", root
        assert (root / "CLAUDE.local.md").read_text().startswith("# RETIRED checkout"), root
    assert "feat/unported" in (sb.old_dev / "CLAUDE.local.md").read_text()
    bundle = sb.state_dir / "job-enricher-all-refs.bundle"
    assert bundle.is_file()
    sb.sh([sb.host.git, "-C", str(sb.old_dev), "bundle", "verify", str(bundle)])
    for name in ("README.md", "CLAUDE.md"):
        body = sb.sh([sb.host.git, "--git-dir", str(sb.je_remote), "show", f"main:{name}"]).stdout
        assert body.startswith("> **Moved.**"), name
    assert sb.gh_calls() == [f"repo archive {cs.OLD_REPO_SLUG} --yes"]
    texts = sb.texts()
    assert len(texts) == 1 and "DONE" in texts[0] and str(sb.new_enricher) in texts[0], texts
    assert all(str(v).startswith("ok") for v in st["retire"].values()), st["retire"]


def test_co14_secrets_never_leak(happy, step):
    sb = happy
    assert sb.state().get("phase") == "DONE", sb.output()

    step(".env.local arrived byte-identical, mode kept")
    src, dst = sb.old / ".env.local", sb.new_enricher / ".env.local"
    assert dst.read_bytes() == src.read_bytes()
    assert (dst.stat().st_mode & 0o7777) == (src.stat().st_mode & 0o7777) == 0o600

    step("the canary appears in no output, log, state file, text or other file")
    canary = cs.CANARY.encode()
    assert cs.CANARY not in sb.all_output(), "the canary reached stdout/stderr"
    leaks = []
    scan = [sb.state_dir, sb.launchd, sb.logs, sb.home / "Library", sb.new, sb.old, sb.old_dev,
            sb.root / "events.jsonl"]
    allowed = {src.resolve(), dst.resolve()}
    for base in scan:
        paths = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
        for p in paths:
            if p.resolve() in allowed or "/.venv/" in str(p):
                continue
            try:
                if canary in p.read_bytes():
                    leaks.append(str(p.relative_to(sb.root)))
            except OSError:
                pass
    assert leaks == [], f"the canary leaked into: {leaks}"
    for repo in (sb.je_remote, sb.new, sb.old_dev):
        log = sb.sh([sb.host.git, "--git-dir", str(repo if repo.name.endswith(".git") else repo / ".git"),
                     "log", "--all", "-p"]).stdout
        assert cs.CANARY not in log, f"the canary was committed in {repo}"
    copied = sb.state().get("untracked_copied", [])
    assert {c["path"] for c in copied} >= {".env.local"} and all(set(c) == {"path", "size"} for c in copied)


def test_co15_rerun_after_done_is_a_noop(happy, step):
    sb = happy
    assert sb.state().get("phase") == "DONE", sb.output()
    state_before = (sb.state_dir / "state.json").read_bytes()
    plist_before = sb.plist.read_bytes()
    n_calls, n_texts = len(sb.lifecycle_calls()), len(sb.texts())

    step("cutover.sh --run after DONE")
    cp = sb.run_cutover("--run", label="rerun after DONE")
    assert cp.returncode == 0, sb.output()
    assert "-> noop_done" in cp.stdout, sb.output()
    assert (sb.state_dir / "state.json").read_bytes() == state_before
    assert sb.plist.read_bytes() == plist_before
    assert len(sb.lifecycle_calls()) == n_calls and len(sb.texts()) == n_texts

    step("cutover.sh --status prints the state")
    cp = sb.run_cutover("--status", label="status")
    assert cp.returncode == 0 and '"phase": "DONE"' in cp.stdout, sb.output()

    step("the watcher's next fire retires it without fetching or running anything")
    t0 = time.time()
    cp = sb.run_watcher(label="watcher after DONE")
    assert cp.returncode == 0, sb.output()
    assert "cutover is DONE; retiring the watcher" in cp.stdout and "running it" not in cp.stdout
    removes = [c for c in sb.calls() if c["t"] > t0 and c["argv"][:1] == ["remove"]]
    assert [c["argv"] for c in removes] == [["remove", cs.WATCHER_LABEL]]
    assert (sb.state_dir / "state.json").read_bytes() == state_before
    assert sb.loaded_program() == str(sb.new_enricher / cs.WRAPPER_REL), "prod must stay loaded"
