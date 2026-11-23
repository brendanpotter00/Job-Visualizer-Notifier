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
