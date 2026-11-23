"""cutover.py — carrying the old prod's untracked state over (PLAN §4.4 C3).

Regenerable files are skipped, databases go through the SQLite backup API,
everything else is copied with mode + mtime and checked by sha256. Contents
(above all `.env.local`) are never logged.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from test_cutover_ref import GIT_ENV, load_cutover

co = load_cutover()

CANARY = "CANARY-not-a-real-key-9c1e"

#: the prod tag's src/enricher/.gitignore, verbatim
GITIGNORE = """.venv/
data/*.db
data/*.db-*
data/.tick.lock
data/chunks/
.env.local
.checkout-role
__pycache__/
*.pyc
.pytest_cache/
.coverage
golden/scorecards/predictions*.json
golden/scorecards/scorecard*.json
dashboard/node_modules/
dashboard/dist/
dashboard/coverage/
dashboard/.vite/
node_modules/
"""


@pytest.mark.parametrize(
    "rel, cls",
    [
        (".env.local", "copy"),
        ("data/classify-run-t44.log", "copy"),
        ("golden/scorecards/predictions-2026.json", "copy"),
        (".coverage", "copy"),
        ("notes.txt", "copy"),
        (".venv/bin/python", "regenerate"),
        (".venv/lib/python3.12/site-packages/x.py", "regenerate"),
        ("src/job_enricher/__pycache__/cli.cpython-312.pyc", "regenerate"),
        ("tests/x.pyc", "regenerate"),
        (".pytest_cache/v/cache/nodeids", "regenerate"),
        ("data/chunks/classify-t1-01.json", "regenerate"),
        ("data/chunks/classify-run-t46.log", "regenerate"),
        ("data/.tick.lock", "regenerate"),
        ("data/.tick.lock.steal.123", "regenerate"),
        ("data/.backfill.lock", "regenerate"),
        ("data/.subcategory-push.lock", "regenerate"),
        ("dashboard/node_modules/react/index.js", "regenerate"),
        ("dashboard/dist/index.html", "regenerate"),
        (".checkout-role", "regenerate"),
        ("data/enricher.db", "db"),
        ("data/sub/other.db", "db"),
        ("data/enricher.db-wal", "db-sidecar"),
        ("data/enricher.db-shm", "db-sidecar"),
        ("data/enricher.db-journal", "db-sidecar"),
        # a rollback's own leftovers belong to the OLD prod: never carried over
        ("data/enricher.db.pre-rollback-20260101T000000Z", "regenerate"),
        ("data/enricher.db.pre-rollback-20260101T000000Z-wal", "regenerate"),
        ("data/enricher.db.pre-rollback-20260101T000000Z-shm", "regenerate"),
        ("data/enricher.db.pre-rollback-20260101T000000Z-journal", "regenerate"),
        ("data/enricher.db.rollback-tmp", "regenerate"),
        ("data/enricher.db.rollback-tmp-journal", "regenerate"),
    ],
)
def test_classify_untracked(rel, cls):
    assert co.classify_untracked(rel) == cls


@pytest.fixture
def old_prod(tmp_path) -> Path:
    root = tmp_path / "app"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True, env=GIT_ENV)
    (root / ".gitignore").write_text(GITIGNORE)
    (root / "README.md").write_text("tracked\n")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=GIT_ENV)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True, env=GIT_ENV)
    files = {
        ".env.local": f"JVN_BASE_URL=http://127.0.0.1:9\nINTERNAL_API_KEY={CANARY}\n",
        ".checkout-role": "prod\n",
        ".venv/bin/python": "#!/bin/sh\n",
        "data/chunks/classify-t1-01.json": "[]",
        "data/.tick.lock": "123|x",
        "data/classify-run-t44.log": "old log\n",
        "data/enricher.db.pre-rollback-20260101T000000Z": "the stale DB a rollback kept\n",
        "golden/scorecards/predictions-1.json": "{}",
        "src/job_enricher/__pycache__/a.cpython-312.pyc": "x",
        "notes.txt": "untracked, not ignored\n",
    }
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    os.chmod(root / ".env.local", 0o600)
    os.utime(root / "data" / "classify-run-t44.log", (1_700_000_000, 1_700_000_000))
    conn = sqlite3.connect(root / "data" / "enricher.db")
    conn.execute("CREATE TABLE ticks (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    return root


@pytest.fixture
def cfg(tmp_path):
    return co.Config.from_env({"HOME": str(tmp_path / "home")})


def test_list_untracked_sees_ignored_and_untracked_files(cfg, old_prod):
    rels = set(co.list_untracked(cfg, old_prod))
    assert {".env.local", ".checkout-role", "data/enricher.db", "data/classify-run-t44.log",
            "notes.txt", ".venv/bin/python", "data/chunks/classify-t1-01.json"} <= rels
    assert "README.md" not in rels and ".gitignore" not in rels


def test_copy_carries_exactly_the_copy_class_with_mode_and_mtime(cfg, old_prod, tmp_path):
    dst = tmp_path / "new" / "src" / "enricher"
    dst.mkdir(parents=True)
    copied = co.copy_untracked(old_prod, dst, co.list_untracked(cfg, old_prod))
    names = sorted(c["path"] for c in copied)
    assert names == [".env.local", "data/classify-run-t44.log",
                     "golden/scorecards/predictions-1.json", "notes.txt"]
    assert (dst / ".env.local").read_bytes() == (old_prod / ".env.local").read_bytes()
    assert (dst / ".env.local").stat().st_mode & 0o777 == 0o600
    assert (dst / "data" / "classify-run-t44.log").stat().st_mtime == 1_700_000_000
    for skipped in (".checkout-role", ".venv/bin/python", "data/.tick.lock", "data/enricher.db",
                    "data/chunks/classify-t1-01.json",
                    "data/enricher.db.pre-rollback-20260101T000000Z"):
        assert not (dst / skipped).exists(), skipped
    for c in copied:
        assert c["sha256"] == co.sha256_file(dst / c["path"])


def test_copy_can_leave_env_local_behind_for_a_rehearsal(cfg, old_prod, tmp_path):
    dst = tmp_path / "scratch"
    dst.mkdir()
    copied = co.copy_untracked(old_prod, dst, co.list_untracked(cfg, old_prod), skip={".env.local"})
    assert ".env.local" not in {c["path"] for c in copied}
    assert not (dst / ".env.local").exists()


def test_copy_refuses_to_overwrite(cfg, old_prod, tmp_path):
    dst = tmp_path / "new"
    (dst / "data").mkdir(parents=True)
    (dst / "notes.txt").write_text("already here")
    with pytest.raises(RuntimeError, match="already exists"):
        co.copy_untracked(old_prod, dst, ["notes.txt"])


def test_copy_preserves_symlinks(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "link").symlink_to("target-that-need-not-exist")
    copied = co.copy_untracked(src, dst, ["link"])
    assert os.readlink(dst / "link") == "target-that-need-not-exist" and copied[0]["symlink"]


def test_a_relative_symlink_out_of_the_old_prod_is_refused(tmp_path):
    """The new prod is two levels deeper than app/: ../x would land elsewhere."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / ".env.local").symlink_to("../secrets/.env.local")
    with pytest.raises(RuntimeError, match="outside the old prod"):
        co.copy_untracked(src, dst, [".env.local"])
    assert not os.path.lexists(dst / ".env.local")
    (src / "abs").symlink_to(tmp_path / "secrets" / ".env.local")  # absolute: same file
    assert co.copy_untracked(src, dst, ["abs"])[0]["symlink"]


def test_inventory_and_copy_never_expose_contents(cfg, old_prod, tmp_path, capsys):
    items = co.inventory(cfg, old_prod)
    co.copy_untracked(old_prod, tmp_path, co.list_untracked(cfg, old_prod))
    out = capsys.readouterr()
    assert CANARY not in repr(items) + out.out + out.err
    env = next(i for i in items if i["path"] == ".env.local")
    assert env == {"path": ".env.local", "class": "copy", "size": len(
        (old_prod / ".env.local").read_bytes())}
    summary = co.summarize_inventory(items)
    assert summary["db"]["files"] == 1 and summary["copy"]["files"] == 4


def test_online_backup_copies_a_consistent_db_and_snapshots_match(tmp_path):
    src = tmp_path / "src.db"
    conn = sqlite3.connect(src)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        "CREATE TABLE ticks (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT);"
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);"
        "INSERT INTO ticks (status) VALUES ('ok'), ('ok'), ('running');"
        "INSERT INTO meta VALUES ('classify:engine', 'ollama', '2026-01-01');"
        "PRAGMA user_version = 3;")
    conn.commit()  # leave the connection OPEN: the WAL holds the rows
    dst = tmp_path / "copy" / "enricher.db"
    co.online_backup(src, dst)
    conn.close()
    ok, why = co.integrity_ok(dst)
    assert ok, why
    a_conn, _ = co.connect_ro(src)
    b_conn, _ = co.connect_ro(dst)
    a, b = co.db_snapshot(a_conn), co.db_snapshot(b_conn)
    a_conn.close()
    b_conn.close()
    assert co.compare_snapshots(a, b) == []
    assert b["user_version"] == 3 and b["max_tick_id"] == 3 and b["counts"]["ticks"] == 3
    assert b["meta"] == [["classify:engine", "ollama", "2026-01-01"]]


def test_quiescent_read_leaves_no_sqlite_sidecars(tmp_path):
    """--preflight is read-only: a plain mode=ro reader of an idle WAL database
    CREATES its -wal/-shm files (found by e2e CO-11), the quiescent read does not."""
    db = tmp_path / "enricher.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("CREATE TABLE ticks (id INTEGER PRIMARY KEY); INSERT INTO ticks VALUES (7);")
    conn.commit()
    conn.close()  # last connection: checkpointed, -wal/-shm removed
    sidecars = [Path(f"{db}-wal"), Path(f"{db}-shm")]
    assert not any(p.exists() for p in sidecars)

    q, mode = co.connect_ro(db, quiescent_immutable=True)
    assert q.execute("SELECT id FROM ticks").fetchone()[0] == 7
    q.close()
    assert mode.startswith("immutable") and not any(p.exists() for p in sidecars)

    plain, mode = co.connect_ro(db)
    plain.close()
    assert mode == "ro" and any(p.exists() for p in sidecars), "the reason for the flag is gone"

    # A live connection (a -wal exists) is read through the WAL, as before.
    w = sqlite3.connect(db)
    w.execute("INSERT INTO ticks VALUES (8)")
    w.commit()
    q, mode = co.connect_ro(db, quiescent_immutable=True)
    assert mode == "ro" and q.execute("SELECT max(id) FROM ticks").fetchone()[0] == 8
    q.close()
    w.close()


def test_compare_snapshots_names_what_differs():
    a = {"user_version": 3, "counts": {"ticks": 3, "meta": 1}, "max_tick_id": 3, "meta": [["k", "v", "t"]]}
    b = {"user_version": 4, "counts": {"ticks": 2, "meta": 1}, "max_tick_id": 2, "meta": [["k", "w", "t"]]}
    diffs = co.compare_snapshots(a, b)
    assert any("user_version" in d for d in diffs)
    assert any("ticks" in d for d in diffs)
    assert any("max(ticks.id)" in d for d in diffs)
    assert any("meta" in d for d in diffs)
