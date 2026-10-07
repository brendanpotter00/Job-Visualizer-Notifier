"""Launch Radar persistence: cards, runs, the spend ledger and the Monitors.

The SQL behind both Launch Radar surfaces:

* the admin dashboard (``routers/admin.py``, ``require_admin``): ``list_cards``,
  ``card_counts``, ``run_stats``, ``set_status`` and ``delete_card``;
* the loop (``routers/internal_launch_radar.py``, X-Internal-Key): runs, the
  ledger (``reserve_spend``), Monitors, ``seen``, ``insert_card``, the PR step.

Every function that writes OWNS ITS COMMIT, and rolls back before raising one of
the domain errors below, so a route only has to roll back on a raw
``psycopg2.Error``. Money is ``NUMERIC`` in the database and ``Decimal`` here;
it becomes ``float`` only at the response boundary (``usd``).

Card lifecycle: new -> archived (archive) -> new (restore) or deleted (delete,
only from archived). A delete is a TOMBSTONE: the payload, PR link and tracked
company are cleared but the row and its domain stay, so the UNIQUE on
``domain`` keeps the loop from ever posting that company again. Nothing here
ever runs ``DELETE FROM launch_radar_cards``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Any, Literal, TypedDict, cast

from psycopg2.extensions import connection as Connection
from psycopg2.extras import Json

from ..config import settings

logger = logging.getLogger(__name__)

# ``pg_advisory_xact_lock`` key that serializes every reservation, so two
# concurrent runs can never both pass the cap on the same stale SUM. An
# arbitrary fixed constant; nothing else in this database takes it.
LEDGER_LOCK_KEY = 7_316_202_610_070_001

_CENT_4 = Decimal("0.0001")

CardStatus = Literal["new", "archived"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LaunchRadarError(Exception):
    """Base for the domain errors a route maps to a status code."""


class NotFound(LaunchRadarError):
    """404: the run / card / monitor does not exist (or the card is deleted)."""


class Conflict(LaunchRadarError):
    """409: the row exists but is in the wrong state for this operation."""


class DomainSeen(Conflict):
    """409: a card for this normalized domain was already posted (ever)."""

    def __init__(self) -> None:
        super().__init__("domain already posted")


class InvalidDomain(LaunchRadarError):
    """422: the payload's domain is not in normalized form."""


class BudgetExceeded(LaunchRadarError):
    """402: the reservation would pass the run's budget or the global cap."""

    def __init__(
        self,
        reason: Literal["run_budget", "cap"],
        run_spend: Decimal,
        total_spend: Decimal,
        cap: Decimal,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.run_spend = run_spend
        self.total_spend = total_spend
        self.cap = cap

    def detail(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "run_spend_usd": usd(self.run_spend),
            "total_spend_usd": usd(self.total_spend),
            "cap_usd": usd(self.cap),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://")
_NULLISH = frozenset({"", "na", "n/a", "none", "null", "unknown"})


def normalize_domain(value: object) -> str | None:
    """Normalize a website / domain string to a bare lower-case host.

    Ported verbatim from the POC (``scripts/launch_radar_poc/poc.py``); the loop
    carries the same algorithm in ``scripts/launch_radar/domains.py`` and both
    test suites pin the same vectors (CONTRACT §3).
    """
    if not value or not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in _NULLISH:
        return None
    v = _SCHEME_RE.sub("", v)
    v = v.split("/")[0].split("?")[0].split("#")[0]
    v = v.split("@")[-1].split(":")[0]
    if v.startswith("www."):
        v = v[4:]
    v = v.rstrip(".")
    return v if "." in v else None


def usd(value: Decimal | float | int | None) -> float:
    """A money value for a response: rounded to 4 places, as float."""
    if value is None:
        return 0.0
    return float(Decimal(value).quantize(_CENT_4, rounding=ROUND_HALF_UP))


def _money(value: float) -> Decimal:
    """A request amount as NUMERIC(10,4). Rounds UP so a positive estimate can
    never round to $0 (the ledger's CHECK) or under-reserve."""
    return Decimal(str(value)).quantize(_CENT_4, rounding=ROUND_UP)


def cap_usd() -> Decimal:
    return Decimal(str(settings.launch_radar_spend_cap_usd))


# ---------------------------------------------------------------------------
# Row shapes
# ---------------------------------------------------------------------------


class CardRow(TypedDict):
    id: int
    domain: str
    company_name: str
    status: str
    tracked_company_id: str | None
    pr_url: str | None
    payload: dict[str, Any] | None
    run_id: int | None
    posted_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    deleted_at: datetime | None
    updated_by: str | None


class LastRunRow(TypedDict):
    started_at: datetime
    ended_at: datetime | None
    status: str
    host: str | None


class RunStats(TypedDict):
    last_run: LastRunRow | None
    spend_usd: float
    cap_usd: float


class MonitorRow(TypedDict):
    slot: str
    monitor_id: str
    query: str
    processor: str
    frequency: str
    status: str
    last_event_id: str | None
    charged_through: datetime


class RunStarted(TypedDict):
    run_id: int
    run_uuid: str
    budget_usd: float
    run_spend_usd: float
    total_spend_usd: float
    cap_usd: float
    remaining_usd: float
    monitors: list[MonitorRow]


class Reserved(TypedDict):
    reserved_usd: float
    run_spend_usd: float
    total_spend_usd: float
    cap_usd: float
    over_cap: bool


class RunFinished(TypedDict):
    run_id: int
    status: str
    run_spend_usd: float
    total_spend_usd: float


class SeenCard(TypedDict):
    card_id: int
    status: str


class Seen(TypedDict):
    domains: dict[str, SeenCard]
    names: dict[str, str]


class CardCreated(TypedDict):
    id: int
    tracked_company_id: str | None


class PrCandidate(TypedDict):
    id: int
    domain: str
    company: str
    ats_provider: str
    board_token: str | None
    job_count: int | None
    posted_at: datetime


_CARD_COLUMNS = (
    "id, domain, company_name, status, tracked_company_id, pr_url, payload, "
    "run_id, posted_at, updated_at, archived_at, deleted_at, updated_by"
)

_MONITOR_COLUMNS = (
    "slot, monitor_id, query, processor, frequency, status, last_event_id, "
    "charged_through"
)


# ---------------------------------------------------------------------------
# Admin: cards
# ---------------------------------------------------------------------------


def list_cards(
    conn: Connection, status: CardStatus, limit: int, offset: int
) -> tuple[list[CardRow], int]:
    """One page of cards with ``status`` plus the total with that status.

    ``new`` is ordered newest-posted first; ``archived`` most-recently-archived
    first. Only a single non-deleted status is ever selected, so a tombstone can
    never reach the admin client.
    """
    order = (
        "posted_at DESC, id DESC" if status == "new" else "archived_at DESC, id DESC"
    )
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_CARD_COLUMNS} FROM launch_radar_cards "
            f"WHERE status = %s ORDER BY {order} LIMIT %s OFFSET %s",
            (status, limit, offset),
        )
        rows = [cast(CardRow, dict(r)) for r in cur.fetchall()]
        cur.execute(
            "SELECT count(*) AS n FROM launch_radar_cards WHERE status = %s",
            (status,),
        )
        total_row = cur.fetchone()
    return rows, int(total_row["n"]) if total_row else 0


def card_counts(conn: Connection) -> dict[str, int]:
    """Counts for BOTH tabs, whatever the requested filter."""
    counts = {"new": 0, "archived": 0}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, count(*) AS n FROM launch_radar_cards "
            "WHERE status IN ('new', 'archived') GROUP BY status"
        )
        for r in cur.fetchall():
            counts[r["status"]] = int(r["n"])
    return counts


def run_stats(conn: Connection) -> RunStats:
    """The header line: the newest run, total spend and the cap."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT started_at, ended_at, status, host FROM launch_radar_runs "
            "ORDER BY started_at DESC, id DESC LIMIT 1"
        )
        last = cur.fetchone()
        cur.execute("SELECT COALESCE(SUM(amount_usd), 0) AS total FROM launch_radar_spend")
        total_row = cur.fetchone()
    return {
        "last_run": cast(LastRunRow, dict(last)) if last else None,
        "spend_usd": usd(total_row["total"] if total_row else 0),
        "cap_usd": usd(cap_usd()),
    }


def _raise_for_missed_transition(conn: Connection, cur: Any, card_id: int) -> None:
    """After a guarded UPDATE matched no row: 404 if the card is missing or a
    tombstone, otherwise 409 (it exists but is in the wrong state)."""
    cur.execute("SELECT status FROM launch_radar_cards WHERE id = %s", (card_id,))
    row = cur.fetchone()
    conn.rollback()
    if row is None or row["status"] == "deleted":
        raise NotFound("card not found")
    raise Conflict(f"card is {row['status']}")


def set_status(
    conn: Connection, card_id: int, status: CardStatus, admin_email: str
) -> CardRow:
    """Archive a ``new`` card, or restore (``status='new'``) an ``archived`` one."""
    if status == "archived":
        sql = (
            "UPDATE launch_radar_cards SET status = 'archived', archived_at = now(), "
            "updated_at = now(), updated_by = %s "
            f"WHERE id = %s AND status = 'new' RETURNING {_CARD_COLUMNS}"
        )
    else:
        sql = (
            "UPDATE launch_radar_cards SET status = 'new', archived_at = NULL, "
            "updated_at = now(), updated_by = %s "
            f"WHERE id = %s AND status = 'archived' RETURNING {_CARD_COLUMNS}"
        )
    with conn.cursor() as cur:
        cur.execute(sql, (admin_email, card_id))
        row = cur.fetchone()
        if row is None:
            _raise_for_missed_transition(conn, cur, card_id)
    conn.commit()
    return cast(CardRow, dict(row))


def delete_card(conn: Connection, card_id: int, admin_email: str) -> None:
    """Tombstone an ``archived`` card. A ``new`` card must be archived first."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE launch_radar_cards SET status = 'deleted', payload = NULL, "
            "pr_url = NULL, tracked_company_id = NULL, archived_at = NULL, "
            "deleted_at = now(), updated_at = now(), updated_by = %s "
            "WHERE id = %s AND status = 'archived' RETURNING id",
            (admin_email, card_id),
        )
        if cur.fetchone() is None:
            _raise_for_missed_transition(conn, cur, card_id)
    conn.commit()


# ---------------------------------------------------------------------------
# Loop: runs and the ledger
# ---------------------------------------------------------------------------


def _spend_totals(cur: Any, run_id: int) -> tuple[Decimal, Decimal]:
    cur.execute(
        "SELECT COALESCE(SUM(amount_usd) FILTER (WHERE run_id = %s), 0) AS run_spend, "
        "COALESCE(SUM(amount_usd), 0) AS total FROM launch_radar_spend",
        (run_id,),
    )
    row = cur.fetchone()
    return Decimal(row["run_spend"]), Decimal(row["total"])


def _active_monitors(cur: Any) -> list[MonitorRow]:
    cur.execute(
        f"SELECT {_MONITOR_COLUMNS} FROM launch_radar_monitors "
        "WHERE status = 'active' ORDER BY slot"
    )
    return [cast(MonitorRow, dict(r)) for r in cur.fetchall()]


STALE_RUN_AFTER = "1 hour"


def start_run(
    conn: Connection, run_uuid: str, host: str | None, budget_usd: float
) -> RunStarted:
    """Open a run. Idempotent on ``run_uuid``: a retry returns the existing row
    (with its original budget) instead of opening a second run.

    A killed loop (SIGKILL, power loss) never calls finish, so its row would say
    ``running`` forever. One invocation lives well under ten minutes, so any
    other run still ``running`` after ``STALE_RUN_AFTER`` is closed as ``error``
    here, before the new one opens."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE launch_radar_runs SET status = 'error', ended_at = now(), "
            "notes = concat_ws('; ', notes, 'abandoned: never finished') "
            "WHERE status = 'running' AND run_uuid <> %s "
            "AND started_at < now() - %s::interval",
            (run_uuid, STALE_RUN_AFTER),
        )
        cur.execute(
            "INSERT INTO launch_radar_runs (run_uuid, host, budget_usd) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT ON CONSTRAINT uq_launch_radar_runs_run_uuid DO NOTHING "
            "RETURNING id, run_uuid, budget_usd",
            (run_uuid, host, _money(budget_usd)),
        )
        run = cur.fetchone()
        if run is None:
            cur.execute(
                "SELECT id, run_uuid, budget_usd FROM launch_radar_runs WHERE run_uuid = %s",
                (run_uuid,),
            )
            run = cur.fetchone()
        run_spend, total = _spend_totals(cur, run["id"])
        monitors = _active_monitors(cur)
    conn.commit()
    cap = cap_usd()
    return {
        "run_id": run["id"],
        "run_uuid": run["run_uuid"],
        "budget_usd": usd(run["budget_usd"]),
        "run_spend_usd": usd(run_spend),
        "total_spend_usd": usd(total),
        "cap_usd": usd(cap),
        "remaining_usd": usd(cap - total),
        "monitors": monitors,
    }


def reserve_spend(
    conn: Connection,
    run_uuid: str,
    step: str,
    est_usd: float,
    domain: str | None,
    accrued: bool,
) -> Reserved:
    """Reserve ``est_usd`` against the run budget and the global cap, in ONE
    transaction serialized by an advisory lock.

    A non-accrued reservation that would pass either limit is refused
    (``BudgetExceeded``: run budget first, then the cap) and nothing is written.
    An accrued one (money already spent, e.g. scheduled Monitor executions) is
    ALWAYS recorded; ``over_cap`` tells the loop to stop the Monitors.
    """
    est = _money(est_usd)
    cap = cap_usd()
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (LEDGER_LOCK_KEY,))
        cur.execute(
            "SELECT id, status, budget_usd FROM launch_radar_runs "
            "WHERE run_uuid = %s FOR UPDATE",
            (run_uuid,),
        )
        run = cur.fetchone()
        if run is None:
            conn.rollback()
            raise NotFound("run not found")
        if run["status"] != "running":
            conn.rollback()
            raise Conflict(f"run is {run['status']}")
        run_spend, total = _spend_totals(cur, run["id"])
        if not accrued:
            if run_spend + est > Decimal(run["budget_usd"]):
                conn.rollback()
                raise BudgetExceeded("run_budget", run_spend, total, cap)
            if total + est > cap:
                conn.rollback()
                raise BudgetExceeded("cap", run_spend, total, cap)
        cur.execute(
            "INSERT INTO launch_radar_spend (run_id, step, domain, amount_usd, accrued) "
            "VALUES (%s, %s, %s, %s, %s)",
            (run["id"], step, domain, est, accrued),
        )
    conn.commit()
    return {
        "reserved_usd": usd(est),
        "run_spend_usd": usd(run_spend + est),
        "total_spend_usd": usd(total + est),
        "cap_usd": usd(cap),
        "over_cap": total + est > cap,
    }


def finish_run(
    conn: Connection,
    run_uuid: str,
    status: Literal["ok", "stopped", "error"],
    events_read: int,
    cards_posted: int,
    notes: str | None,
) -> RunFinished:
    """Close a ``running`` run. 404 unknown, 409 already finished."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, cards_posted FROM launch_radar_runs "
            "WHERE run_uuid = %s FOR UPDATE",
            (run_uuid,),
        )
        run = cur.fetchone()
        if run is None:
            conn.rollback()
            raise NotFound("run not found")
        if run["status"] != "running":
            conn.rollback()
            raise Conflict(f"run already finished ({run['status']})")
        counted = int(run["cards_posted"])
        if counted != cards_posted:
            # The backend counts every accepted POST /cards for this run (in the
            # same transaction as the insert), so its number is authoritative: a
            # POST that committed but whose response was lost is a card the loop
            # counted as an error. Store the backend's count and say so in notes.
            logger.warning(
                "launch radar run %s finished with cards_posted=%d but the backend "
                "counted %d accepted cards",
                run_uuid,
                cards_posted,
                counted,
            )
            mismatch = f"loop reported {cards_posted} card(s), backend counted {counted}"
            notes = f"{notes}; {mismatch}" if notes else mismatch
        cur.execute(
            "UPDATE launch_radar_runs SET status = %s, events_read = %s, "
            "cards_posted = %s, notes = %s, ended_at = now() "
            "WHERE id = %s RETURNING id, status",
            (status, events_read, counted, notes, run["id"]),
        )
        row = cur.fetchone()
        run_spend, total = _spend_totals(cur, row["id"])
    conn.commit()
    return {
        "run_id": row["id"],
        "status": row["status"],
        "run_spend_usd": usd(run_spend),
        "total_spend_usd": usd(total),
    }


# ---------------------------------------------------------------------------
# Loop: Monitors
# ---------------------------------------------------------------------------


def list_monitors(conn: Connection) -> list[MonitorRow]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_MONITOR_COLUMNS} FROM launch_radar_monitors ORDER BY slot")
        rows = [cast(MonitorRow, dict(r)) for r in cur.fetchall()]
    conn.rollback()  # read-only; return the connection idle
    return rows


def put_monitor(
    conn: Connection,
    slot: str,
    monitor_id: str,
    query: str,
    processor: str,
    frequency: str,
    status: str,
    charged_through: datetime,
) -> MonitorRow:
    """Upsert the Monitor for ``slot``. A NEW ``monitor_id`` for the slot resets
    ``last_event_id`` (the old cursor names another monitor's event stream)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO launch_radar_monitors "
            "(slot, monitor_id, query, processor, frequency, status, charged_through) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (slot) DO UPDATE SET "
            "  monitor_id = EXCLUDED.monitor_id, query = EXCLUDED.query, "
            "  processor = EXCLUDED.processor, frequency = EXCLUDED.frequency, "
            "  status = EXCLUDED.status, charged_through = EXCLUDED.charged_through, "
            "  last_event_id = CASE WHEN launch_radar_monitors.monitor_id = EXCLUDED.monitor_id "
            "    THEN launch_radar_monitors.last_event_id ELSE NULL END, "
            "  updated_at = now() "
            f"RETURNING {_MONITOR_COLUMNS}",
            (slot, monitor_id, query, processor, frequency, status, charged_through),
        )
        row = cur.fetchone()
    conn.commit()
    return cast(MonitorRow, dict(row))


_MONITOR_PATCHABLE = ("last_event_id", "status", "charged_through")


def patch_monitor(conn: Connection, slot: str, changes: dict[str, Any]) -> MonitorRow:
    """Update a subset of ``last_event_id`` / ``status`` / ``charged_through``."""
    keys = [k for k in _MONITOR_PATCHABLE if k in changes]
    if not keys:
        raise ValueError("no patchable fields")
    # Column names come from the fixed tuple above, never from the request.
    assignments = ", ".join(f"{k} = %s" for k in keys)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE launch_radar_monitors SET {assignments}, updated_at = now() "
            f"WHERE slot = %s RETURNING {_MONITOR_COLUMNS}",
            (*[changes[k] for k in keys], slot),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            raise NotFound("monitor not found")
    conn.commit()
    return cast(MonitorRow, dict(row))


# ---------------------------------------------------------------------------
# Loop: dedupe, cards, PR step
# ---------------------------------------------------------------------------


def seen(conn: Connection, domains: list[str], names: list[str]) -> Seen:
    """Which of these companies the loop must not spend on.

    ``domains``: every card for the normalized domain, in ANY status (a tombstone
    counts: a deleted company is never re-posted). ``names``: input names whose
    case-insensitive form matches a tracked public company's display name.
    """
    normalized = sorted({d for d in (normalize_domain(x) for x in domains) if d})
    out: Seen = {"domains": {}, "names": {}}
    with conn.cursor() as cur:
        if normalized:
            cur.execute(
                "SELECT id, domain, status FROM launch_radar_cards WHERE domain = ANY(%s)",
                (normalized,),
            )
            for r in cur.fetchall():
                out["domains"][r["domain"]] = {"card_id": r["id"], "status": r["status"]}
        wanted = [n for n in names if n.strip()]
        if wanted:
            cur.execute(
                "SELECT DISTINCT ON (lower(display_name)) lower(display_name) AS key, id "
                "FROM companies WHERE visibility = 'public' "
                "AND lower(display_name) = ANY(%s) ORDER BY lower(display_name), id",
                ([n.strip().lower() for n in wanted],),
            )
            by_key = {r["key"]: r["id"] for r in cur.fetchall()}
            for n in wanted:
                company_id = by_key.get(n.strip().lower())
                if company_id is not None:
                    out["names"][n] = company_id
    conn.rollback()  # read-only
    return out


def _lock_running_run(conn: Connection, cur: Any, run_uuid: str) -> int:
    cur.execute(
        "SELECT id, status FROM launch_radar_runs WHERE run_uuid = %s FOR UPDATE",
        (run_uuid,),
    )
    run = cur.fetchone()
    if run is None:
        conn.rollback()
        raise NotFound("run not found")
    if run["status"] != "running":
        conn.rollback()
        raise Conflict(f"run is {run['status']}")
    return int(run["id"])


def insert_card(conn: Connection, run_uuid: str, payload: dict[str, Any]) -> CardCreated:
    """Store one card (``payload`` is the snake_case ``model_dump(mode='json')``).

    404 unknown run, 409 run not running, 422 (``InvalidDomain``) when the
    domain is not normalized, 409 (``DomainSeen``) when the domain was ever
    posted before. ``tracked_company_id`` is resolved here from the ATS board.
    """
    domain = payload["domain"]
    with conn.cursor() as cur:
        run_id = _lock_running_run(conn, cur, run_uuid)
        if normalize_domain(domain) != domain:
            conn.rollback()
            raise InvalidDomain(
                f"domain {domain!r} is not normalized "
                f"(expected {normalize_domain(domain)!r})"
            )
        tracked: str | None = None
        ats = payload["ats"]
        if ats.get("board_token"):
            cur.execute(
                "SELECT id FROM companies WHERE visibility = 'public' AND ats = %s "
                "AND lower(board_token) = lower(%s) ORDER BY id LIMIT 1",
                (ats["provider"], ats["board_token"]),
            )
            hit = cur.fetchone()
            tracked = hit["id"] if hit else None
        cur.execute(
            "INSERT INTO launch_radar_cards (domain, company_name, status, "
            "tracked_company_id, payload, run_id, posted_at, updated_at) "
            "VALUES (%s, %s, 'new', %s, %s, %s, now(), now()) "
            "ON CONFLICT ON CONSTRAINT uq_launch_radar_cards_domain DO NOTHING "
            "RETURNING id",
            (domain, payload["company"], tracked, Json(payload), run_id),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            raise DomainSeen()
        cur.execute(
            "UPDATE launch_radar_runs SET cards_posted = cards_posted + 1 WHERE id = %s",
            (run_id,),
        )
    conn.commit()
    return {"id": row["id"], "tracked_company_id": tracked}


def set_pr_url(conn: Connection, card_id: int, pr_url: str) -> tuple[int, str]:
    """Record the add-company PR the skill opened. 404 missing or deleted; 409
    when a PR is already recorded or the company is already tracked."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE launch_radar_cards SET pr_url = %s, updated_at = now() "
            "WHERE id = %s AND status <> 'deleted' AND pr_url IS NULL "
            "AND tracked_company_id IS NULL RETURNING id, pr_url",
            (pr_url, card_id),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "SELECT status, pr_url, tracked_company_id FROM launch_radar_cards "
                "WHERE id = %s",
                (card_id,),
            )
            existing = cur.fetchone()
            conn.rollback()
            if existing is None or existing["status"] == "deleted":
                raise NotFound("card not found")
            if existing["pr_url"] is not None:
                raise Conflict("pr_url already set")
            raise Conflict("company is already tracked")
    conn.commit()
    return int(row["id"]), str(row["pr_url"])


def pr_candidates(conn: Connection, limit: int) -> list[PrCandidate]:
    """New, untracked, PR-less cards whose ATS board was verified (pr_ready)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, domain, company_name, posted_at, "
            "payload->'ats'->>'provider' AS ats_provider, "
            "payload->'ats'->>'board_token' AS board_token, "
            "(payload->'ats'->>'job_count')::int AS job_count "
            "FROM launch_radar_cards "
            "WHERE status = 'new' AND pr_url IS NULL AND tracked_company_id IS NULL "
            "AND (payload->>'pr_ready')::boolean "
            "ORDER BY posted_at DESC, id DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
    conn.rollback()  # read-only
    return [
        {
            "id": r["id"],
            "domain": r["domain"],
            "company": r["company_name"],
            "ats_provider": r["ats_provider"],
            "board_token": r["board_token"],
            "job_count": r["job_count"],
            "posted_at": r["posted_at"],
        }
        for r in rows
    ]


__all__ = [
    "BudgetExceeded",
    "Conflict",
    "DomainSeen",
    "InvalidDomain",
    "LEDGER_LOCK_KEY",
    "LaunchRadarError",
    "NotFound",
    "card_counts",
    "delete_card",
    "finish_run",
    "insert_card",
    "list_cards",
    "list_monitors",
    "normalize_domain",
    "patch_monitor",
    "pr_candidates",
    "put_monitor",
    "reserve_spend",
    "run_stats",
    "seen",
    "set_pr_url",
    "set_status",
    "start_run",
]
