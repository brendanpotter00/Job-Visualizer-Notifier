"""DEP-1 — a TEXT GUARD on scripts/deploy.sh.

Merging to JVN `main` deploys NOTHING to the enricher: the live worker runs from
`/Users/bpotter/developer/personal/enricher-prod/src/enricher`
(`.checkout-role='prod'`, launchd label `com.bp.job-enricher`).
`scripts/deploy.sh` is the only supported path there, and
each of the guards asserted below closes a specific way a deploy strands prod:

* the `.checkout-role` check — deploying into the DEV checkout is a silent no-op;
* the EXIT resume trap, armed BEFORE the unload — an exit between unload and the
  trap would strand prod with no worker at all;
* the post-unload `launchctl list` re-verification — `unload` returning 0 is not
  proof the label went away;
* the live-pid lock check — ticks run ~6,700 s and fire every 60 s, so the idle
  window is unhittable by guessing; you must WAIT on the in-flight wrapper;
* the uncommitted-changes abort — otherwise a `git checkout` clobbers prod edits.

Since the monorepo move (PLAN §6) the script also PARKS the worker between ticks
(`scripts/lib/park_worker.py claim`, a wall-clock budget, our pid in the lock)
before it unloads, refuses the no-arg form on a detached HEAD, syncs with
`--frozen`, honours `DEPLOY_PROJECT_DIR`, and releases the lock it claimed in the
EXIT trap. The second half of this file runs the real script in a sandbox (fake
HOME, stub `launchctl` + `uv`, local bare origin) to prove those behaviours.
"""

from __future__ import annotations

from pathlib import Path

_DEPLOY = Path(__file__).resolve().parents[1] / "scripts" / "deploy.sh"


def _text() -> str:
    return _DEPLOY.read_text(encoding="utf-8")


def test_deploy_script_exists():
    assert _DEPLOY.exists()


def test_refuses_outside_the_prod_checkout():
    text = _text()
    assert ".checkout-role" in text
    assert "refusing" in text


def test_arms_the_exit_resume_trap():
    text = _text()
    assert "trap resume EXIT" in text
    # Armed BEFORE the unload, or an exit in between strands prod with no worker.
    # Compare against the COMMAND, not the comment that explains it.
    unload_cmd = 'launchctl unload "$PLIST"'
    assert unload_cmd in text
    assert text.index("trap resume EXIT") < text.index(unload_cmd)


def test_reverifies_the_label_after_unload():
    assert "launchctl list" in _text()


def test_checks_the_lock_pid_is_actually_ALIVE():
    """A stale lock file must not block a deploy forever, and a LIVE tick must
    not be cut off mid-flight — so the check is `kill -0`, not file existence."""
    assert "kill -0" in _text()


def test_aborts_on_uncommitted_tracked_changes():
    assert "uncommitted" in _text()


def test_runs_a_health_check_after_the_swap():
    assert "cli health" in _text()


# ---------------------------------------------------------------------------
# Monorepo-era guards (PLAN §6): the real script in a sandbox.
# ---------------------------------------------------------------------------
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

_SCRIPTS = _DEPLOY.parent

GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1",
}


def _g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=GIT_ENV).stdout.strip()


@pytest.fixture
def sandbox(tmp_path):
    """A prod checkout of a tiny repo (with the REAL deploy.sh + park_worker.py),
    a local bare origin with a second commit to deploy, stub launchctl + uv."""
    seed = tmp_path / "seed"
    (seed / "scripts" / "lib").mkdir(parents=True)
    shutil.copy2(_DEPLOY, seed / "scripts" / "deploy.sh")
    shutil.copy2(_SCRIPTS / "lib" / "park_worker.py", seed / "scripts" / "lib" / "park_worker.py")
    (seed / "scripts" / "enrich_tick_wrapper.sh").write_text("#!/bin/sh\nexit 0\n")
    (seed / ".gitignore").write_text(".checkout-role\ndata/\n")
    (seed / "VERSION").write_text("1\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True, env=GIT_ENV)
    _g(seed, "add", "-A")
    _g(seed, "commit", "-qm", "v1")
    v1 = _g(seed, "rev-parse", "HEAD")
    (seed / "VERSION").write_text("2\n")
    _g(seed, "commit", "-qam", "v2")
    v2 = _g(seed, "rev-parse", "HEAD")
    _g(seed, "tag", "enricher-prod-v2", v2)
    # A pre-consolidation-style ref: no scripts/lib/ (like enricher-prod-eeff1c9).
    _g(seed, "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", v1)
    _g(seed, "rm", "-rq", "scripts/lib")
    _g(seed, "commit", "-qm", "no lib")
    _g(seed, "tag", "enricher-prod-nolib")
    _g(seed, "checkout", "-q", "main")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(origin)], check=True, env=GIT_ENV)
    prod = tmp_path / "prod"
    subprocess.run(["git", "clone", "-q", str(origin), str(prod)], check=True, env=GIT_ENV)
    _g(prod, "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", v1)
    (prod / ".checkout-role").write_text("prod\n")
    (prod / "data").mkdir()

    home = tmp_path / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    loaded = tmp_path / "loaded"
    loaded.write_text("1")
    (bin_dir / "launchctl").write_text(f"""#!/bin/sh
echo "launchctl $*" >> "{log}"
case "$1" in
  list) echo "PID	Status	Label"; [ -f "{loaded}" ] && echo "-	0	com.bp.job-enricher"; exit 0 ;;
  unload) rm -f "{loaded}"; exit 0 ;;
  load) echo 1 > "{loaded}"; exit 0 ;;
esac
""")
    (bin_dir / "uv").write_text(f"""#!/bin/sh
echo "uv $*" >> "{log}"
case "$*" in *"cli health"*) echo '{{"ok": true}}' ;; esac
exit 0
""")
    for f in ("launchctl", "uv"):
        (bin_dir / f).chmod(0o755)
    env = {
        "HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
        "UV_BIN": str(bin_dir / "uv"), "DEPLOY_PYTHON": sys.executable,
        "DEPLOY_PARK_BUDGET_S": "30", **{k: v for k, v in GIT_ENV.items() if k.startswith("GIT_")},
    }
    return {"prod": prod, "env": env, "log": log, "loaded": loaded, "v1": v1, "v2": v2, "tmp": tmp_path}


def _deploy(sb, *args, script=None, env_extra=None):
    script = script or (sb["prod"] / "scripts" / "deploy.sh")
    return subprocess.run(["/bin/sh", str(script), *args], cwd=str(sb["prod"]), capture_output=True,
                          text=True, env={**sb["env"], **(env_extra or {})}, timeout=120)


def _calls(sb):
    return sb["log"].read_text().splitlines() if sb["log"].exists() else []


def test_behaviour_deploys_a_ref_parking_first_and_releasing_after(sandbox):
    cp = _deploy(sandbox, "enricher-prod-v2")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert _g(sandbox["prod"], "rev-parse", "HEAD") == sandbox["v2"]
    calls = _calls(sandbox)
    assert "uv sync --frozen" in calls
    assert any("cli health" in c for c in calls)
    unload = calls.index(next(c for c in calls if c.startswith("launchctl unload")))
    load = calls.index(next(c for c in calls if c.startswith("launchctl load")))
    assert unload < load
    assert "claimed" in cp.stdout  # park_worker held the lock before the unload
    assert not (sandbox["prod"] / "data" / ".tick.lock").exists()  # released on exit
    assert sandbox["loaded"].exists()


def test_behaviour_a_ref_without_lib_still_releases_the_lock(sandbox):
    """Rolling back to a pre-consolidation tag deletes scripts/lib/park_worker.py
    from under the running script. The EXIT trap must still drop the lock: one
    naming deploy's dead pid makes every worker fire skip for 3 h."""
    cp = _deploy(sandbox, "enricher-prod-nolib")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert not (sandbox["prod"] / "scripts" / "lib" / "park_worker.py").exists()
    assert "released our tick lock" in cp.stdout, cp.stdout + cp.stderr
    assert "WARN" not in cp.stderr, cp.stderr
    assert not (sandbox["prod"] / "data" / ".tick.lock").exists()
    assert sandbox["loaded"].exists()


def test_behaviour_the_trap_leaves_a_lock_that_is_not_ours(sandbox):
    """The release compares the recorded pid with $$ — never a blind rm."""
    other = sandbox["tmp"] / "other-scripts" / "scripts"
    shutil.copytree(sandbox["prod"] / "scripts", other)
    deploy = other / "deploy.sh"
    # Swap the lock's holder for someone else's pid right after the checkout.
    lock = sandbox["prod"] / "data" / ".tick.lock"
    text = deploy.read_text().replace(
        '# 5. Resync deps',
        f'printf "1|someone-else" > "{lock}"\n# 5. Resync deps', 1)
    deploy.write_text(text)
    cp = _deploy(sandbox, "enricher-prod-v2", script=deploy,
                 env_extra={"DEPLOY_PROJECT_DIR": str(sandbox["prod"])})
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "not ours (holder='1')" in cp.stdout, cp.stdout
    assert lock.read_text() == "1|someone-else"


def test_behaviour_a_branch_name_deploys_origins_copy_detached(sandbox):
    cp = _deploy(sandbox, "main")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert _g(sandbox["prod"], "rev-parse", "HEAD") == sandbox["v2"]
    assert subprocess.run(["git", "-C", str(sandbox["prod"]), "symbolic-ref", "-q", "HEAD"],
                          capture_output=True).returncode != 0


def test_behaviour_no_arg_on_a_detached_head_is_refused_before_touching_launchd(sandbox):
    cp = _deploy(sandbox)
    assert cp.returncode == 1 and "pass a ref" in cp.stderr
    assert not any(c.startswith("launchctl") for c in _calls(sandbox))
    assert _g(sandbox["prod"], "rev-parse", "HEAD") == sandbox["v1"]


def test_behaviour_a_running_tick_is_waited_for_never_cut(sandbox):
    holder = subprocess.Popen(["sleep", "60"])
    try:
        lock = sandbox["prod"] / "data" / ".tick.lock"
        lock.write_text(f"{holder.pid}|2026-01-01T00:00:00Z")
        cp = _deploy(sandbox, "enricher-prod-v2", env_extra={"DEPLOY_PARK_BUDGET_S": "1"})
        assert cp.returncode == 1 and "still running" in cp.stderr
        calls = _calls(sandbox)
        assert not any(c.startswith(("launchctl unload", "launchctl load")) for c in calls)
        assert lock.read_text() == f"{holder.pid}|2026-01-01T00:00:00Z"  # untouched
        assert _g(sandbox["prod"], "rev-parse", "HEAD") == sandbox["v1"]
    finally:
        holder.kill()
        holder.wait()


def test_behaviour_an_abort_after_parking_still_releases_and_reloads(sandbox):
    (sandbox["prod"] / "VERSION").write_text("hand edit\n")  # a tracked change in prod
    cp = _deploy(sandbox, "enricher-prod-v2")
    assert cp.returncode == 1 and "uncommitted" in cp.stderr
    assert not (sandbox["prod"] / "data" / ".tick.lock").exists()
    assert sandbox["loaded"].exists()  # the worker came back
    assert _g(sandbox["prod"], "rev-parse", "HEAD") == sandbox["v1"]


def test_behaviour_deploy_project_dir_lets_mains_script_deploy_an_older_prod(sandbox):
    """The first deploy of main runs main's scripts/ from a temp dir against a prod
    whose own deploy.sh is older. Without the override the script would target
    its own parent dir (no .checkout-role there) and refuse."""
    other = sandbox["tmp"] / "main-scripts" / "scripts"
    shutil.copytree(sandbox["prod"] / "scripts", other)
    assert _deploy(sandbox, "enricher-prod-v2", script=other / "deploy.sh").returncode == 1
    cp = _deploy(sandbox, "enricher-prod-v2", script=other / "deploy.sh",
                 env_extra={"DEPLOY_PROJECT_DIR": str(sandbox["prod"])})
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert _g(sandbox["prod"], "rev-parse", "HEAD") == sandbox["v2"]


def test_behaviour_refuses_a_checkout_not_marked_prod(sandbox):
    (sandbox["prod"] / ".checkout-role").write_text("dev\n")
    cp = _deploy(sandbox, "enricher-prod-v2")
    assert cp.returncode == 1 and "refusing" in cp.stderr
    assert not _calls(sandbox)
