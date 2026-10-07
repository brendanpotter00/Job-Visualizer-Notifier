"""The three narrow event_stream Monitors (CONTRACT §6.3 steps 2-3, §6.4).

Monitor ids and read cursors live in the backend (``launch_radar_monitors``).
Event text is web content and is treated as data: it is parsed into a fixed
set of string fields and never acted on.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from typing import Any, Callable

from .backend_client import BackendClient
from .parallel_client import status_code_of
from .schemas import (
    MONITOR_FREQUENCY,
    MONITOR_OUTPUT_SCHEMA,
    MONITOR_PRICE,
    MONITOR_PROCESSOR,
    MONITOR_QUERIES,
    ceil_cost,
)
from .state import iso, parse_iso

Log = Callable[[str], None]
EVENT_FIELDS = ("company_name", "company_domain", "event_type", "round", "amount_usd", "investors",
                "announced_at", "source_url", "headline")
MAX_EVENT_PAGES = 50
MAX_ACCRUE_DAYS_PER_ROW = 100  # keeps one reservation under the backend's $1 est_usd limit
APP_TAG = "launch-radar"


class MonitorCancelError(RuntimeError):
    pass


def create_request(slot: str) -> dict[str, Any]:
    return {
        "type": "event_stream",
        "frequency": MONITOR_FREQUENCY,
        "processor": MONITOR_PROCESSOR,
        "settings": {
            "query": MONITOR_QUERIES[slot],
            "include_backfill": True,
            "output_schema": {"type": "json", "json_schema": MONITOR_OUTPUT_SCHEMA},
        },
        "metadata": {"app": APP_TAG, "slot": slot},
    }


def active(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("status") == "active"]


def ensure(client: Any, backend: BackendClient, run_uuid: str, now: datetime, log: Log) -> list[str]:
    """Create a Monitor for every slot without an active row. Returns the slots created."""
    have = {r["slot"] for r in active(backend.list_monitors())}
    created: list[str] = []
    for slot in MONITOR_QUERIES:
        if slot in have:
            continue
        # The first execution runs at creation, so it is paid for up front.
        backend.reserve(run_uuid, "monitor.create", ceil_cost(MONITOR_PRICE[MONITOR_PROCESSOR]))
        m = client.monitor.create(**create_request(slot))
        log(f"monitor {slot}: created {m.monitor_id}")
        row = {"monitor_id": m.monitor_id, "query": MONITOR_QUERIES[slot], "processor": MONITOR_PROCESSOR,
               "frequency": MONITOR_FREQUENCY, "status": "active", "charged_through": iso(now)}
        try:
            backend.put_monitor(slot, row)
        except Exception as put_err:
            # An id the backend does not know about would bill daily with no
            # ledger row and no way to cancel it from here: cancel it now, and
            # confirm, because a failed cancel leaves an orphan that bills daily.
            log(f"monitor {slot}: backend PUT failed ({type(put_err).__name__}: {put_err}); "
                f"cancelling {m.monitor_id}")
            try:
                client.monitor.cancel(m.monitor_id)
                status = client.monitor.retrieve(m.monitor_id).status
            except Exception as cancel_err:
                log(f"ORPHAN monitor {m.monitor_id} for slot {slot} may still be active and billing "
                    f"(cancel failed: {type(cancel_err).__name__}: {cancel_err}); run monitors-cancel")
                raise MonitorCancelError(f"monitor {m.monitor_id} ({slot}) orphaned: backend PUT failed "
                                         f"and the cancel failed") from put_err
            if status != "cancelled":
                log(f"ORPHAN monitor {m.monitor_id} for slot {slot} is still {status} after cancel; "
                    f"run monitors-cancel")
                raise MonitorCancelError(f"monitor {m.monitor_id} ({slot}) still {status} after cancel") from put_err
            log(f"monitor {slot}: cancelled {m.monitor_id}, confirmed")
            raise
        created.append(slot)
    return created


def accrue(
    backend: BackendClient, run_uuid: str, monitors: list[dict[str, Any]], now: datetime, log: Log
) -> tuple[bool, dict[str, Any] | None]:
    """Record scheduled executions since ``charged_through`` as accrued spend.

    Returns ``(over_cap, last_reserve_response)``.
    """
    over_cap = False
    last: dict[str, Any] | None = None
    for m in active(monitors):
        charged = parse_iso(m["charged_through"])
        days = math.floor((now - charged).total_seconds() / 86400)
        while days >= 1:
            chunk = min(days, MAX_ACCRUE_DAYS_PER_ROW)
            last = backend.reserve(run_uuid, "monitor.accrued", ceil_cost(chunk * MONITOR_PRICE[MONITOR_PROCESSOR]),
                                   accrued=True)
            charged += timedelta(days=chunk)
            backend.patch_monitor(m["slot"], charged_through=iso(charged))
            over_cap = over_cap or bool(last.get("over_cap"))
            log(f"monitor {m['slot']}: accrued {chunk} day(s)")
            days -= chunk
    return over_cap, last


def parse_content(content: Any) -> dict[str, Any]:
    """POC ``_parse_content``: JSON object, JSON string, or free text."""
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else {"text": content}
        except json.JSONDecodeError:
            return {"text": content}
    return content if isinstance(content, dict) else {}


def _str_or_none(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def event_to_candidate(ev: Any, slot: str) -> dict[str, Any]:
    output = getattr(ev, "output", None)
    content = parse_content(getattr(output, "content", None))
    cand: dict[str, Any] = {k: _str_or_none(content.get(k)) for k in EVENT_FIELDS}
    cand.update({"event_id": getattr(ev, "event_id", None), "event_date": _str_or_none(getattr(ev, "event_date", None)),
                 "slot": slot})
    return cand


def read_events(client: Any, monitor: dict[str, Any], log: Log) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Events newer than ``last_event_id`` (newest first), the newest event id seen, and
    whether the read stopped at ``MAX_EVENT_PAGES`` before reaching ``last_event_id``
    (older events are then never read; the caller records it).

    Pages until a page holds ``last_event_id`` or the list ends. Only
    ``event_stream`` rows become candidates; ``error`` rows are logged.
    """
    last_seen = monitor.get("last_event_id")
    newest: str | None = None
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    truncated = False
    for page_no in range(MAX_EVENT_PAGES):
        kw: dict[str, Any] = {"limit": 100}
        if cursor:
            kw["cursor"] = cursor
        page = client.monitor.events(monitor["monitor_id"], **kw)
        reached = False
        for ev in page.events or []:
            etype = getattr(ev, "event_type", None)
            eid = getattr(ev, "event_id", None)
            if eid and last_seen and eid == last_seen:
                reached = True
                break
            if eid and newest is None:
                newest = eid
            if etype == "event_stream":
                out.append(event_to_candidate(ev, monitor["slot"]))
            elif etype == "error":
                log(f"monitor {monitor['slot']}: execution error: {str(getattr(ev, 'error_message', ''))[:200]}")
        cursor = getattr(page, "next_cursor", None)
        if reached or not cursor or not page.events:
            break
        if page_no == MAX_EVENT_PAGES - 1:
            truncated = True
    if truncated:
        log(f"WARNING monitor {monitor['slot']}: stopped after {MAX_EVENT_PAGES} pages ({len(out)} event(s) read) "
            f"without reaching the last seen event; older events are skipped")
    return out, newest, truncated


def _is_gone(exc: BaseException) -> bool:
    return status_code_of(exc) == 404


def cancel_all(client: Any, backend: BackendClient, log: Log) -> list[str]:
    """Cancel every active Monitor (the backend's rows and any tagged orphan) and confirm.

    Tries every monitor even when one fails, patches the rows that were confirmed, and
    then raises one ``MonitorCancelError`` naming every monitor that may still be active.
    A 404 from Parallel means the monitor no longer exists: its row is marked cancelled.
    """
    rows = active(backend.list_monitors())
    ids = {r["monitor_id"]: r["slot"] for r in rows}
    cursor: str | None = None
    while True:
        kw: dict[str, Any] = {"limit": 100}
        if cursor:
            kw["cursor"] = cursor
        page = client.monitor.list(**kw)
        for m in page.monitors or []:
            meta = getattr(m, "metadata", None) or {}
            if meta.get("app") == APP_TAG and getattr(m, "status", None) == "active":
                ids.setdefault(m.monitor_id, "")
        cursor = getattr(page, "next_cursor", None)
        if not cursor:
            break
    cancelled: list[str] = []
    failed: list[str] = []
    for mid, slot in ids.items():
        label = slot or "(orphan)"
        try:
            try:
                client.monitor.cancel(mid)
                status = client.monitor.retrieve(mid).status
            except Exception as e:
                if not _is_gone(e):
                    raise
                status = "cancelled"
                log(f"monitor {label}: {mid} not found on Parallel (HTTP 404); treating it as gone")
            if status != "cancelled":
                raise MonitorCancelError(f"still {status} after cancel")
            if slot:
                backend.patch_monitor(slot, status="cancelled")
        except Exception as e:
            log(f"monitor {label}: cancel of {mid} FAILED: {type(e).__name__}: {e}")
            failed.append(f"{mid} ({label})")
            continue
        log(f"monitor {label}: cancelled {mid}, confirmed")
        cancelled.append(mid)
    if failed:
        raise MonitorCancelError(f"{len(failed)} monitor(s) may still be active: {', '.join(failed)}"
                                 f" (cancelled {len(cancelled)})")
    return cancelled
