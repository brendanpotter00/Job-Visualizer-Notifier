"""Local resumable state under ``LAUNCH_RADAR_STATE_DIR``.

- ``queue.json``: candidates that passed dedupe and still need research.
- ``companies/<domain>.json``: per-company progress (created Parallel ids,
  reserved amounts, start times). A saved id is never created again and a saved
  reservation is never reserved again, so a run cut off by the deadline resumes
  without paying twice.
- ``backfill.json``: the one-off ``backfill`` sweep (its FindAll id, reservations and
  progress), so a re-run resumes polling instead of paying for a second FindAll run.
- ``refresh/<domain>.json``: a ``refresh`` in progress (the card it started from, the new
  brief / pedigree ids and reservations); ``refresh_done.json``: the cards already
  refreshed, which a later ``refresh`` skips, so a re-run never pays for one twice.
- ``heartbeat.log``: one line per skill run (the wrapper checks its mtime).

Writes are atomic (temp file + rename) so a killed process never leaves a
half-written file behind.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domains import is_hostname


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True, default=str)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class StateStore:
    def __init__(self, state_dir: Path) -> None:
        self.dir = state_dir
        self.queue_path = state_dir / "queue.json"
        self.companies_dir = state_dir / "companies"
        self.backfill_path = state_dir / "backfill.json"
        self.refresh_dir = state_dir / "refresh"
        self.refresh_done_path = state_dir / "refresh_done.json"
        self.heartbeat_path = state_dir / "heartbeat.log"
        self._lock = threading.Lock()

    # ---- queue --------------------------------------------------------------------
    def load_queue(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.queue_path.read_text())
        except FileNotFoundError:
            return []
        if not isinstance(data, list):
            raise ValueError(f"{self.queue_path} is not a JSON list")
        return data

    def save_queue(self, items: list[dict[str, Any]]) -> None:
        with self._lock:
            _atomic_write(self.queue_path, items)

    def append_queue(self, items: list[dict[str, Any]]) -> None:
        with self._lock:
            current = self.load_queue()
            known = {q["domain"] for q in current}
            current += [i for i in items if i["domain"] not in known]
            _atomic_write(self.queue_path, current)

    def remove_from_queue(self, domain: str) -> None:
        with self._lock:
            _atomic_write(self.queue_path, [q for q in self.load_queue() if q["domain"] != domain])

    # ---- per-company progress -----------------------------------------------------
    def _company_path(self, domain: str) -> Path:
        if not is_hostname(domain):
            raise ValueError(f"refusing to use {domain!r} as a state file name")
        return self.companies_dir / f"{domain}.json"

    def has_company(self, domain: str) -> bool:
        return self._company_path(domain).exists()

    def load_company(self, domain: str) -> dict[str, Any] | None:
        try:
            data = json.loads(self._company_path(domain).read_text())
        except FileNotFoundError:
            return None
        if not isinstance(data, dict):
            raise ValueError(f"state file for {domain} is not a JSON object")
        return data

    def save_company(self, domain: str, data: dict[str, Any]) -> None:
        _atomic_write(self._company_path(domain), data)

    def delete_company(self, domain: str) -> None:
        self._company_path(domain).unlink(missing_ok=True)

    # ---- backfill ------------------------------------------------------------------
    def load_backfill(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.backfill_path.read_text())
        except FileNotFoundError:
            return None
        if not isinstance(data, dict):
            raise ValueError(f"{self.backfill_path} is not a JSON object")
        return data

    def save_backfill(self, data: dict[str, Any]) -> None:
        _atomic_write(self.backfill_path, data)

    # ---- refresh -------------------------------------------------------------------
    def _refresh_path(self, domain: str) -> Path:
        if not is_hostname(domain):
            raise ValueError(f"refusing to use {domain!r} as a state file name")
        return self.refresh_dir / f"{domain}.json"

    def refresh_domains(self) -> list[str]:
        """Domains with a refresh in progress, sorted."""
        if not self.refresh_dir.is_dir():
            return []
        return sorted(p.stem for p in self.refresh_dir.glob("*.json") if is_hostname(p.stem))

    def load_refresh(self, domain: str) -> dict[str, Any] | None:
        try:
            data = json.loads(self._refresh_path(domain).read_text())
        except FileNotFoundError:
            return None
        if not isinstance(data, dict):
            raise ValueError(f"refresh state for {domain} is not a JSON object")
        return data

    def save_refresh(self, domain: str, data: dict[str, Any]) -> None:
        _atomic_write(self._refresh_path(domain), data)

    def delete_refresh(self, domain: str) -> None:
        self._refresh_path(domain).unlink(missing_ok=True)

    def load_refresh_done(self) -> dict[str, Any]:
        try:
            data = json.loads(self.refresh_done_path.read_text())
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"{self.refresh_done_path} is not a JSON object")
        return data

    def mark_refresh_done(self, domain: str, record: dict[str, Any]) -> None:
        with self._lock:  # refresh workers finish concurrently
            done = self.load_refresh_done()
            done[domain] = record
            _atomic_write(self.refresh_done_path, done)

    # ---- heartbeat -------------------------------------------------------------------
    def heartbeat(self, status: str, note: str | None) -> str:
        clean = " ".join((note or "").split())[:300]
        line = f"{iso(utc_now())} status={status}" + (f" {clean}" if clean else "")
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.heartbeat_path.open("a") as f:
            f.write(line + "\n")
        return line
