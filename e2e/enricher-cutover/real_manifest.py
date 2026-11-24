"""Fingerprint the REAL machine paths the enricher-cutover section must never touch.

run.sh writes one before pytest and one after; any difference fails the run as an
ISOLATION BREACH (PLAN.md §5). Read-only: stat + sha256 + read-only git queries.

* ``~/Library/LaunchAgents/com.bp.*`` — sha256 (the only agents the cutover or
  the watcher could write; other software rewrites its own plists at will — a
  Creative Cloud agent did, mid-run, which is why this is not the whole dir);
* the real cutover state dir — sha256 of every file EXCEPT the installed watcher's own
  working dirs (``jvn.git``, ``run/``, ``watcher.lock``, and their ``.tmp-<pid>`` forms):
  it fires every 5 min on its own schedule, and a case that leaked out of its sandbox
  would write ``state.json``, which IS hashed;
* the watcher's real log files — exists? only, since every fire appends a line to them;
* ``~/developer/personal/{app,job-enricher,enricher-prod}`` — git HEAD, tracked
  changes, ``.checkout-role`` / ``CLAUDE.local.md``, and a stat manifest of every
  file EXCEPT what the live worker itself writes (``data/``, ``.venv/``,
  ``__pycache__/``, ``node_modules/``, ``.pytest_cache/``).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
PERSONAL = HOME / "developer" / "personal"
LIVE_WRITES = {"data", ".venv", "__pycache__", "node_modules", ".pytest_cache"}
#: First path components of the state dir that the installed watcher rewrites on its own
#: 5-minute schedule: the bare JVN mirror, the scripts it extracts from merged main, and
#: its single-flight lock. Matched as prefixes, so the ``.tmp-<pid>`` forms count too.
WATCHER_WRITES = ("jvn.git", "run", "watcher.lock")


def sha(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError as exc:
        return f"unreadable:{exc.errno}"


def files_sha(root: Path, pattern: str = "*", exclude: tuple[str, ...] = ()) -> dict[str, str]:
    if not root.exists():
        return {"<absent>": ""}
    out = {}
    for p in sorted(root.rglob(pattern)):
        rel = p.relative_to(root)
        if exclude and rel.parts[0].startswith(exclude):
            continue
        if p.is_file() or p.is_symlink():
            out[str(rel)] = "link" if p.is_symlink() else sha(p)
    return out


def checkout(root: Path) -> dict[str, object]:
    if not root.exists():
        return {"exists": False}
    git = lambda *a: subprocess.run(  # noqa: E731
        ["git", "-C", str(root), *a], capture_output=True, text=True, timeout=120,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}).stdout
    stats = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in LIVE_WRITES]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                st = p.lstat()
            except OSError:
                continue
            stats[str(p.relative_to(root))] = [st.st_size, st.st_mtime_ns]
    return {
        "exists": True,
        "head": git("rev-parse", "HEAD").strip(),
        "tracked_changes": git("status", "--porcelain", "--untracked-files=no"),
        "role": (root / ".checkout-role").read_text() if (root / ".checkout-role").exists() else None,
        "claude_local": sha(root / "CLAUDE.local.md") if (root / "CLAUDE.local.md").exists() else None,
        "files": stats,
    }


def snapshot() -> dict[str, object]:
    return {
        "launchagents": files_sha(HOME / "Library" / "LaunchAgents", "com.bp.*"),
        "state_dir": files_sha(HOME / "Library" / "Application Support" / "jvn-enricher-cutover",
                               exclude=WATCHER_WRITES),
        "watcher_logs": {n: (HOME / "Library" / "Logs" / n).exists()
                         for n in ("jvn-enricher-cutover.log", "jvn-enricher-cutover.err")},
        "app": checkout(PERSONAL / "app"),
        "job-enricher": checkout(PERSONAL / "job-enricher"),
        "enricher-prod": checkout(PERSONAL / "enricher-prod"),
    }


def verdict(before: Path, after: Path, junit: Path) -> int:
    """Compare two snapshots and record the result as a test case in the run's
    JUnit file, so summary.md counts it: a breach makes the verdict RED."""
    import difflib
    import xml.etree.ElementTree as ET

    a, b = before.read_text(), after.read_text()
    diff = list(difflib.unified_diff(a.splitlines(), b.splitlines(), "before", "after",
                                     lineterm="", n=1))
    if junit.exists():
        tree = ET.parse(junit)
        root = tree.getroot()
        suite = root if root.tag == "testsuite" else root.find("testsuite")
    else:
        root = suite = ET.Element("testsuite", name="enricher-cutover")
        tree = ET.ElementTree(root)
    case = ET.SubElement(suite, "testcase", classname="enricher-cutover.isolation",
                         name="real_machine_paths_unchanged", time="0")
    if diff:
        fail = ET.SubElement(case, "failure", message=(
            "ISOLATION BREACH: the real com.bp.* LaunchAgents, cutover state dir or "
            "~/developer/personal/{app,job-enricher,enricher-prod} changed during the run"))
        fail.text = "\n".join(diff[:80])
    tree.write(junit, encoding="utf-8", xml_declaration=True)
    print("\n".join(diff[:40]))
    return 1 if diff else 0


def main() -> int:
    if sys.argv[1:2] == ["verdict"]:
        return verdict(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    json.dump(snapshot(), sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
