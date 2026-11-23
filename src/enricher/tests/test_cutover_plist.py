"""cutover.py — the plist rewrite is the switch point (PLAN §4.4 D2).

Exactly two substitutions (ProgramArguments[0]'s prefix and WorkingDirectory),
everything else byte-identical, or refuse. Also the watcher's plist template.
"""

from __future__ import annotations

import difflib
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

from test_cutover_ref import SCRIPTS, load_cutover

co = load_cutover()

OLD = "/Users/someone/developer/personal/app"
NEW = "/Users/someone/developer/personal/enricher-prod/src/enricher"
PLUTIL = Path("/usr/bin/plutil")


def prod_plist(old: str = OLD, extra_log_root: str | None = None) -> bytes:
    """The live plist's exact shape (com.bp.job-enricher, 2026-11)."""
    log_root = extra_log_root or "/Users/someone/Library/Logs"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.bp.job-enricher</string>
    <key>ProgramArguments</key>
    <array>
        <string>{old}/scripts/enrich_tick_wrapper.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{old}</string>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{log_root}/job-enricher.log</string>
    <key>StandardErrorPath</key>
    <string>{log_root}/job-enricher.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
""".encode()


def test_rewrite_changes_exactly_the_two_paths():
    orig = prod_plist()
    new = co.rewrite_plist_bytes(orig, OLD, NEW)
    a, b = plistlib.loads(orig), plistlib.loads(new)
    assert b["WorkingDirectory"] == NEW
    assert b["ProgramArguments"] == [f"{NEW}/scripts/enrich_tick_wrapper.sh"]
    for key in ("Label", "StartInterval", "RunAtLoad", "StandardOutPath", "StandardErrorPath",
                "EnvironmentVariables"):
        assert a[key] == b[key], key
    changed = [ln for ln in difflib.ndiff(orig.decode().splitlines(), new.decode().splitlines())
               if ln.startswith(("- ", "+ "))]
    assert len(changed) == 4  # two lines out, two lines in
    assert orig.count(OLD.encode()) == 2 and new.count(OLD.encode()) == 0


def test_rewrite_is_reversible():
    orig = prod_plist()
    assert co.rewrite_plist_bytes(co.rewrite_plist_bytes(orig, OLD, NEW), NEW, OLD) == orig


def test_trailing_slashes_are_tolerated():
    assert co.rewrite_plist_bytes(prod_plist(), OLD + "/", NEW + "/") == \
        co.rewrite_plist_bytes(prod_plist(), OLD, NEW)


@pytest.mark.parametrize(
    "orig, why",
    [
        # a third occurrence (logs under the old prod) is not a prod plist we know
        (prod_plist(extra_log_root=OLD + "/logs"), "exactly 2"),
        # a sibling path sharing the prefix (".../app2") must not be silently skipped
        (prod_plist(extra_log_root=OLD + "2/logs"), "exactly 2"),
        # the plist points somewhere else entirely
        (prod_plist(old="/somewhere/else"), "exactly 2"),
        (b"bplist00\x00\x01", "binary"),
        (b"<plist><dict><key>", "does not parse"),
    ],
)
def test_rewrite_refuses_instead_of_guessing(orig, why):
    with pytest.raises(co.PlistRewriteError, match=why):
        co.rewrite_plist_bytes(orig, OLD, NEW)


def test_rewrite_refuses_when_workdir_is_not_the_old_root():
    # two occurrences, but WorkingDirectory is a SUBDIR of the old root
    orig = prod_plist().replace(f"<string>{OLD}</string>".encode(),
                                f"<string>{OLD}/scripts</string>".encode())
    with pytest.raises(co.PlistRewriteError, match="WorkingDirectory"):
        co.rewrite_plist_bytes(orig, OLD, NEW)


def test_rewrite_refuses_a_program_key():
    orig = prod_plist().replace(b"<key>Label</key>",
                                f"<key>Program</key><string>/bin/sh</string><key>Label</key>".encode())
    with pytest.raises(co.PlistRewriteError, match="Program"):
        co.rewrite_plist_bytes(orig, OLD, NEW)


@pytest.mark.parametrize("bad", ["relative/path", "/a&b", "/a<b", '/a"b'])
def test_rewrite_refuses_xml_unsafe_or_relative_paths(bad):
    with pytest.raises(co.PlistRewriteError, match="unsupported path"):
        co.rewrite_plist_bytes(prod_plist(), OLD, bad)


@pytest.mark.skipif(not PLUTIL.exists(), reason="plutil is macOS-only")
def test_rewritten_plist_lints(tmp_path):
    cfg = co.Config.from_env({"HOME": str(tmp_path)})
    ok, out = co.plutil_lint(cfg, co.rewrite_plist_bytes(prod_plist(), OLD, NEW))
    assert ok, out
    ok, _ = co.plutil_lint(cfg, b"<plist><dict><key>x</key></dict>")
    assert not ok


def test_plist_where(tmp_path):
    cfg = co.Config.from_env({"HOME": str(tmp_path), "CUTOVER_OLD_PROD": OLD,
                              "CUTOVER_NEW_PROD": NEW.removesuffix("/src/enricher")})
    assert co.plist_where(cfg, co.parse_plist(prod_plist())) == "old"
    assert co.plist_where(cfg, co.parse_plist(co.rewrite_plist_bytes(prod_plist(), OLD, NEW))) == "new"
    assert co.plist_where(cfg, co.parse_plist(prod_plist(old="/elsewhere"))) == "other"
    assert co.plist_where(cfg, None) == "missing"


def test_same_path_tolerates_symlinked_roots(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    assert co.same_path(tmp_path / "link", real)
    assert co.same_path(str(real) + "/", real)
    assert not co.same_path(tmp_path / "other", real)


# ---------------------------------------------------------------- watcher plist template
TEMPLATE = SCRIPTS / "cutover" / "com.bp.jvn-enricher-cutover.plist.template"


def render(state: str, home: str) -> bytes:
    return TEMPLATE.read_text().replace("__STATE_DIR__", state).replace("__HOME__", home).encode()


def test_watcher_template_renders_to_the_planned_agent():
    home = "/Users/someone"
    state = f"{home}/Library/Application Support/jvn-enricher-cutover"
    d = plistlib.loads(render(state, home))
    assert d["Label"] == co.WATCHER_LABEL
    assert d["ProgramArguments"] == ["/bin/bash", f"{state}/watcher.sh"]
    assert d["StartInterval"] == 300 and d["RunAtLoad"] is True
    assert d["StandardOutPath"] == f"{home}/Library/Logs/jvn-enricher-cutover.log"
    assert d["StandardErrorPath"] == f"{home}/Library/Logs/jvn-enricher-cutover.err"
    assert d["EnvironmentVariables"]["PATH"] == "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    assert b"__" not in render(state, home)


@pytest.mark.skipif(not PLUTIL.exists(), reason="plutil is macOS-only")
def test_watcher_template_lints():
    cp = subprocess.run([str(PLUTIL), "-lint", "-"], input=render("/x/y z", "/x"),
                        capture_output=True)
    assert cp.returncode == 0, cp.stdout


def test_install_watcher_dry_run_writes_nothing_and_runs_no_launchctl(tmp_path):
    if not PLUTIL.exists():
        pytest.skip("plutil is macOS-only")
    home = tmp_path / "home"
    home.mkdir()
    calls = tmp_path / "launchctl.calls"
    stub = tmp_path / "launchctl"
    stub.write_text(f"#!/bin/sh\necho \"$*\" >> {calls}\n")
    stub.chmod(0o755)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LAUNCHCTL": str(stub)}
    cp = subprocess.run(["/bin/sh", str(SCRIPTS / "cutover" / "install_watcher.sh"), "--dry-run"],
                        capture_output=True, text=True, env=env)
    assert cp.returncode == 0, cp.stderr
    assert "DRY RUN" in cp.stdout and "<string>com.bp.jvn-enricher-cutover</string>" in cp.stdout
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before
    assert not calls.exists()


def test_install_watcher_refuses_a_foreign_new_prod_dir(tmp_path):
    if not PLUTIL.exists():
        pytest.skip("plutil is macOS-only")
    home = tmp_path / "home"
    (home / "developer" / "personal" / "enricher-prod").mkdir(parents=True)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LAUNCHCTL": "/bin/false"}
    cp = subprocess.run(["/bin/sh", str(SCRIPTS / "cutover" / "install_watcher.sh"), "--dry-run"],
                        capture_output=True, text=True, env=env)
    assert cp.returncode == 1 and "Move it aside" in cp.stderr


def test_install_watcher_refuses_a_terminal_state_without_rearm(tmp_path):
    if not PLUTIL.exists():
        pytest.skip("plutil is macOS-only")
    home = tmp_path / "home"
    state = home / "Library" / "Application Support" / "jvn-enricher-cutover"
    state.mkdir(parents=True)
    (state / "state.json").write_text('{\n  "phase": "ROLLED_BACK"\n}\n')
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LAUNCHCTL": "/bin/false"}
    cp = subprocess.run(["/bin/sh", str(SCRIPTS / "cutover" / "install_watcher.sh"), "--dry-run"],
                        capture_output=True, text=True, env=env)
    assert cp.returncode == 1 and "--rearm" in cp.stderr
    assert (state / "state.json").exists()


def test_shell_scripts_parse():
    for name, shell in (("cutover/cutover.sh", "/bin/sh"), ("cutover/install_watcher.sh", "/bin/sh"),
                        ("cutover/watcher.sh", "/bin/bash"), ("deploy.sh", "/bin/sh")):
        cp = subprocess.run([shell, "-n", str(SCRIPTS / name)], capture_output=True, text=True)
        assert cp.returncode == 0, f"{name}: {cp.stderr}"


def test_watcher_is_bash_32_safe():
    """macOS ships bash 3.2: no associative arrays, no ${x,,}, no mapfile/readarray,
    no `wait -n`, no &>> ."""
    text = (SCRIPTS / "cutover" / "watcher.sh").read_text()
    for bad in ("declare -A", ",,}", "^^}", "mapfile", "readarray", "wait -n", "&>>", "|&"):
        assert bad not in text, bad
    assert shutil.which("bash")
