"""cutover.py phase E — what it judges, and what must not roll a good cutover back.

* A first tick whose wrapper died (reboot, power loss, SIGKILL) stays ``running``
  forever; phase E skips it for the next tick instead of waiting into the hard cap.
* The "old prod DB changed" tripwire compares content, not bytes.
* Venv equivalence compares the interpreters that run, not pyvenv.cfg.
* The watcher's lock, handed over through ``exec``, is dropped on exit.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

from test_cutover_plist import prod_plist
from test_cutover_ref import load_cutover

co = load_cutover()

PRE_BOOT = "2001-09-09T01:46:40+00:00"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _make_db(path: Path, ticks: list[tuple[int, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE ticks (id INTEGER PRIMARY KEY, started_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'running', claimed INTEGER NOT NULL DEFAULT 0,
          classified INTEGER NOT NULL DEFAULT 0, sent INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
        INSERT INTO meta VALUES ('classify:engine', 'ollama', '2026-11-01T00:00:00Z');
        PRAGMA user_version = 3;
    """)
    for tick_id, status, started in ticks:
        n = 2 if status == "ok" else 0
        conn.execute("INSERT INTO ticks VALUES (?, ?, ?, ?, ?, ?)",
                     (tick_id, started, status, n, n, n))
    conn.commit()
    conn.close()


def _add_tick(db: Path, tick_id: int, status: str, started: str | None = None) -> None:
    conn = sqlite3.connect(db)
    n = 2 if status == "ok" else 0
    conn.execute("INSERT INTO ticks VALUES (?, ?, ?, ?, ?, ?)",
                 (tick_id, started or _now(), status, n, n, n))
    conn.commit()
    conn.close()


def _snapshot(db: Path) -> dict:
    conn, _ = co.connect_ro(db)
    try:
        return co.db_snapshot(conn)
    finally:
        conn.close()


@pytest.fixture
def verify(tmp_path):
    """A swapped machine: old prod DB with ticks 1-5, the new prod's copy of it,
    the plist pointing at the new prod, the state phase D leaves behind."""
    home = tmp_path / "home"
    cfg = co.Config.from_env({
        "HOME": str(home), "CUTOVER_POLL_S": "0.05",
        "CUTOVER_FIRST_TICK_START_S": "1", "CUTOVER_FIRST_TICK_CLOSE_S": "2",
        "CUTOVER_FIRST_TICK_HARD_CAP_S": "4", "CUTOVER_PROGRESS_WINDOW_S": "1",
    })
    old_db = cfg.old_prod / "data" / "enricher.db"
    new_db = cfg.new_enricher / "data" / "enricher.db"
    closed = [(i, "ok", _now()) for i in range(1, 6)]
    _make_db(old_db, closed)
    _make_db(new_db, closed)
    cfg.enricher_plist.parent.mkdir(parents=True, exist_ok=True)
    cfg.enricher_plist.write_bytes(prod_plist(old=str(cfg.new_enricher)))
    st = co.State(cfg.state_dir / "state.json", {
        "phase": "SWAPPED", "copied_max_tick_id": 5,
        "old_db_sha256": co.sha256_file(old_db), "old_db_snapshot": _snapshot(old_db),
    })
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return cfg, st, old_db, new_db


# ------------------------------------------------------------------ orphaned first ticks
def test_a_later_tick_means_the_first_one_was_orphaned(verify):
    cfg, st, _, new_db = verify
    _add_tick(new_db, 6, "running")  # its wrapper died; nothing will ever close it
    _add_tick(new_db, 7, "ok")
    co.phase_e(cfg, st, None)
    assert st.phase == "VERIFIED"
    assert st.data["first_tick"]["id"] == 7 and st.data["orphaned_first_ticks"] == [6]
    assert any("first tick #6 orphaned (tick #7 started after it)" in h["event"]
               for h in st.data["history"])


def test_a_tick_started_before_this_boot_is_orphaned_and_the_next_one_is_judged(verify):
    cfg, st, _, new_db = verify
    _add_tick(new_db, 6, "running", started=PRE_BOOT)  # a reboot mid-tick
    threading.Timer(0.4, _add_tick, (new_db, 7, "ok")).start()  # the first tick after login
    co.phase_e(cfg, st, None)
    assert st.phase == "VERIFIED" and st.data["first_tick"]["id"] == 7
    assert st.data["orphaned_first_ticks"] == [6]
    assert any("(it started before the current boot)" in h["event"] for h in st.data["history"])


def test_no_tick_after_an_orphan_still_fails_on_the_start_deadline(verify):
    cfg, st, _, new_db = verify
    _add_tick(new_db, 6, "running", started=PRE_BOOT)
    with pytest.raises(co.VerifyFailure, match=r"within 1s of orphaned tick #6"):
        co.phase_e(cfg, st, None)


def test_a_resume_skips_ticks_it_already_found_orphaned(verify):
    cfg, st, _, new_db = verify
    _add_tick(new_db, 6, "running")
    _add_tick(new_db, 7, "ok")
    st.data["orphaned_first_ticks"] = [6]
    co.phase_e(cfg, st, None)
    assert st.data["first_tick"]["id"] == 7 and st.data["orphaned_first_ticks"] == [6]


def test_ticks_that_keep_dying_unclosed_roll_back(verify):
    cfg, st, _, new_db = verify
    for i in range(6, 6 + co.MAX_ORPHANED_FIRST_TICKS):
        _add_tick(new_db, i, "running")
    _add_tick(new_db, 6 + co.MAX_ORPHANED_FIRST_TICKS, "ok")
    with pytest.raises(co.VerifyFailure, match=r"3 ticks in a row were left running"):
        co.phase_e(cfg, st, None)


def test_a_tick_still_running_in_this_boot_is_not_orphaned(tmp_path):
    db = tmp_path / "e.db"
    _make_db(db, [(6, "running", _now())])
    tick = co.read_tick(db, 6)
    assert co.orphaned_because(db, tick, boot=time.time() - 3600) is None
    assert co.orphaned_because(db, tick, boot=None) is None  # sysctl unreadable: no guess


@pytest.mark.parametrize("text, want", [
    ("2026-11-23T10:00:00Z", 1795428000.0),
    ("2026-11-23T10:00:00+00:00", 1795428000.0),
    ("2026-11-23T10:00:00.250000+00:00", 1795428000.25),
    ("2026-11-23T10:00:00", 1795428000.0),  # bare: UTC
    ("", None), (None, None), ("yesterday", None),
])
def test_iso_epoch(text, want):
    assert co.iso_epoch(text) == want


# ------------------------------------------------------------------ the old-prod tripwire
def test_a_header_rewrite_in_the_old_db_is_not_a_change(verify):
    """`cli init` (any init_schema) re-sets user_version to the same value: the
    file's bytes change, its rows do not. That must not roll back."""
    cfg, st, old_db, new_db = verify
    conn = sqlite3.connect(old_db)
    conn.isolation_level = None
    conn.execute("PRAGMA user_version = 3")
    conn.close()
    assert co.sha256_file(old_db) != st.data["old_db_sha256"], "the premise: bytes changed"
    _add_tick(new_db, 6, "ok")
    co.phase_e(cfg, st, None)
    assert st.phase == "VERIFIED"


def test_a_new_row_in_the_old_db_is_a_change(verify):
    cfg, st, old_db, new_db = verify
    _add_tick(old_db, 6, "running")  # something still ticks there
    _add_tick(new_db, 6, "ok")
    with pytest.raises(co.VerifyFailure, match=r"old prod DB changed after the swap .*ticks"):
        co.phase_e(cfg, st, None)


def test_a_state_without_a_snapshot_falls_back_to_the_bytes(verify):
    cfg, st, old_db, _ = verify
    del st.data["old_db_snapshot"]
    assert co.old_db_unchanged(cfg, st) is None
    st.data["old_db_sha256"] = hashlib.sha256(b"something else").hexdigest()
    assert co.old_db_unchanged(cfg, st) == "its bytes changed"


# ------------------------------------------------------------------ venv equivalence
def test_running_python_asks_the_interpreter_not_pyvenv_cfg(tmp_path):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    # What a uv venv looks like after `uv python upgrade`: the cfg is frozen at the
    # patch it was made with, bin/python follows uv's minor-version link.
    (venv / "pyvenv.cfg").write_text("home = /x\nversion_info = 3.12.13\n")
    os.symlink(sys.executable, venv / "bin" / "python")
    want = f"CPython {'.'.join(map(str, sys.version_info[:3]))}"
    assert co.running_python(venv) == want
    assert co.running_python(tmp_path / "missing") is None


# ------------------------------------------------------------------ the watcher's lock
def test_release_if_ours_only_drops_our_own_lock(tmp_path):
    lock = tmp_path / "watcher.lock"
    lock.mkdir()
    (lock / "pid").write_text("1\n")
    assert co.release_if_ours(lock) is False and lock.is_dir()
    (lock / "pid").write_text(f"{os.getpid()}\n")
    assert co.release_if_ours(lock) is True and not lock.exists()
    assert co.release_if_ours(lock) is False  # absent: no error
