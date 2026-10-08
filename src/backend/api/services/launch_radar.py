"""Launch Radar persistence: cards, runs, the spend ledger and the Monitors.

The SQL behind both Launch Radar surfaces:

* the admin dashboard (``routers/admin.py``, ``require_admin``): ``list_cards``,
  ``card_counts``, ``run_stats``, ``set_status`` and ``delete_card``;
* the loop (``routers/internal_launch_radar.py``, X-Internal-Key): runs, the
  ledger (``reserve_spend``), Monitors, ``seen``, ``insert_card``, the
  ``refresh`` pair (``find_cards``, ``replace_payload``).

Every function that writes OWNS ITS COMMIT, and rolls back before raising one of
the domain errors below, so a route only has to roll back on a raw
``psycopg2.Error``. Money is ``NUMERIC`` in the database and ``Decimal`` here;
it becomes ``float`` only at the response boundary (``usd``).

Card lifecycle (``_ALLOWED_FROM``): new -> saved (save) -> new (unsave); new or
saved -> archived (archive) -> new (restore) or deleted (delete, only from
archived). A delete is a TOMBSTONE: the payload and tracked company (and the
legacy, unused ``pr_url``; see ``db_models.LaunchRadarCard``) are cleared but the
row and its domain stay, so the UNIQUE on ``domain`` keeps the loop from ever
posting that company again. Nothing here ever runs
``DELETE FROM launch_radar_cards``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
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

CardStatus = Literal["new", "saved", "archived"]

# The live (non-deleted) statuses, in tab order. A tombstone is never listed.
CARD_STATUSES: tuple[CardStatus, ...] = ("new", "saved", "archived")

# The admin list's sort keys (``?sort=``), the same for every tab.
CardSort = Literal["announced", "talent", "vc", "added"]

# Announcement date, newest first. A card with no event (or an undated one)
# sorts last. ``announced_at`` is stored as text, and the payload model admits
# only an ISO date (``2026-09-17``) or year-month (``2026-09``), for which text
# order is date order (a month sorts just after the days within it).
_BY_ANNOUNCED = "(payload->'event'->>'announced_at') DESC NULLS LAST"

# Sort key -> a FIXED ORDER BY clause. The request only ever picks a key from
# this dict (the route validates ``sort`` as a ``Literal``); nothing from the
# request is interpolated into SQL. Every clause ends in the same tie-breaks
# (announced date, then posted_at, then id), so equal scores page in one stable
# order and LIMIT/OFFSET never repeats or skips a card. A null score (no data)
# sorts after every scored card.
_CARD_ORDER: dict[CardSort, str] = {
    "announced": f"{_BY_ANNOUNCED}, posted_at DESC, id DESC",
    "talent": (
        "(payload->'scores'->>'talent')::numeric DESC NULLS LAST, "
        f"{_BY_ANNOUNCED}, posted_at DESC, id DESC"
    ),
    "vc": (
        "(payload->'scores'->>'vc')::numeric DESC NULLS LAST, "
        f"{_BY_ANNOUNCED}, posted_at DESC, id DESC"
    ),
    "added": f"posted_at DESC, {_BY_ANNOUNCED}, id DESC",
}

# Target status -> the statuses a card may move to it from. Every other move
# (same state, archived -> saved, anything from deleted) is refused.
_ALLOWED_FROM: dict[CardStatus, tuple[str, ...]] = {
    "saved": ("new",),  # Save
    "new": ("saved", "archived"),  # Unsave / Restore
    "archived": ("new", "saved"),  # Archive
}


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


class StoredCard(TypedDict):
    id: int
    domain: str
    status: str
    payload: dict[str, Any]


class PayloadReplaced(TypedDict):
    id: int
    domain: str
    status: str
    posted_at: datetime
    updated_at: datetime


_CARD_COLUMNS = (
    "id, domain, company_name, status, tracked_company_id, payload, "
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
    conn: Connection,
    status: CardStatus,
    limit: int,
    offset: int,
    sort: CardSort = "announced",
) -> tuple[list[CardRow], int]:
    """One page of cards with ``status`` plus the total with that status.

    Ordered by ``sort`` (``_CARD_ORDER``), the same way on every tab: newest
    announcement, Talent or VC score (highest first, unscored last), or newest
    posted. Only a single non-deleted status is ever selected, so a tombstone
    can never reach the admin client.
    """
    order = _CARD_ORDER[sort]
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
    """Counts for EVERY tab (new, saved, archived), whatever the requested filter."""
    counts: dict[str, int] = {s: 0 for s in CARD_STATUSES}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, count(*) AS n FROM launch_radar_cards "
            "WHERE status = ANY(%s) GROUP BY status",
            (list(CARD_STATUSES),),
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


# The 409 for a guarded UPDATE that missed because another request moved the
# card between that UPDATE and the follow-up read: the status read back would
# have allowed the move, so naming it would contradict the refusal.
_RACED = "card changed while this request ran; reload and try again"


def _status_after_missed_update(conn: Connection, cur: Any, card_id: int) -> str:
    """After a guarded UPDATE matched no row: the card's current status, so the
    caller can raise a 409 that names it. Raises ``NotFound`` (404) when the
    card is missing or a tombstone. Rolls back either way.

    The read is a separate statement, so another request can commit between the
    UPDATE and it. A caller that gets back a status its UPDATE would have
    accepted must raise the generic ``_RACED`` 409, never one naming that
    status."""
    cur.execute("SELECT status FROM launch_radar_cards WHERE id = %s", (card_id,))
    row = cur.fetchone()
    conn.rollback()
    if row is None or row["status"] == "deleted":
        raise NotFound("card not found")
    return str(row["status"])


def set_status(
    conn: Connection,
    card_id: int,
    status: CardStatus,
    admin_email: str,
    expected_from: CardStatus | None = None,
) -> CardRow:
    """Move a card between the live tabs, per ``_ALLOWED_FROM``: save (new ->
    saved), unsave (saved -> new), archive (new or saved -> archived) and
    restore (archived -> new). Any other move is a ``Conflict`` (409).

    ``expected_from`` (the PATCH body's ``from``) makes the move a
    compare-and-swap: the guarded UPDATE matches only a card still in that
    status, so a click made on a stale view (an Unsave on a card someone has
    since archived: both send ``new``) is a 409 naming the real status instead of
    a move the admin never asked for. ``None`` keeps every allowed source."""
    allowed = _ALLOWED_FROM[status]
    sources = allowed if expected_from is None else tuple(s for s in allowed if s == expected_from)
    # Only an archived card has an archived_at; every other target clears it.
    archived_at = "now()" if status == "archived" else "NULL"
    sql = (
        f"UPDATE launch_radar_cards SET status = %s, archived_at = {archived_at}, "
        "updated_at = now(), updated_by = %s "
        f"WHERE id = %s AND status = ANY(%s) RETURNING {_CARD_COLUMNS}"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (status, admin_email, card_id, list(sources)))
        row = cur.fetchone()
        if row is None:
            current = _status_after_missed_update(conn, cur, card_id)
            if expected_from is not None and current != expected_from:
                raise Conflict(
                    f"card is {current}, not {expected_from}; reload and try again"
                )
            if current == status:
                raise Conflict(f"card is already {status}")
            if current in sources:
                raise Conflict(_RACED)
            raise Conflict(
                f"card is {current}; only a {' or '.join(allowed)} card can move to {status}"
            )
    conn.commit()
    return cast(CardRow, dict(row))


def delete_card(conn: Connection, card_id: int, admin_email: str) -> None:
    """Tombstone an ``archived`` card. A ``new`` or ``saved`` card must be
    archived first (409)."""
    with conn.cursor() as cur:
        # ``pr_url`` is legacy (nothing writes it since the PR step was removed), but a
        # row written before that may still hold one, and the tombstone CHECK
        # (ck_launch_radar_cards_tombstone_clean) requires it cleared.
        cur.execute(
            "UPDATE launch_radar_cards SET status = 'deleted', payload = NULL, "
            "pr_url = NULL, tracked_company_id = NULL, archived_at = NULL, "
            "deleted_at = now(), updated_at = now(), updated_by = %s "
            "WHERE id = %s AND status = 'archived' RETURNING id",
            (admin_email, card_id),
        )
        if cur.fetchone() is None:
            current = _status_after_missed_update(conn, cur, card_id)
            if current == "archived":
                raise Conflict(_RACED)
            raise Conflict(f"card is {current}; archive it before deleting it permanently")
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
# Loop: dedupe, cards
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


# A card with no leaders' part of Talent (``missing_talent``). A blended card
# (``talent_basis`` set) carries the part as ``talent_leaders``; a legacy card
# (scored before the 50/50 blend, no ``talent_basis``) has only the leaders' raw
# score, as ``talent``. ->> yields SQL NULL for a JSON null as well as for a
# missing key. Not ``talent IS NULL``: a team-only card has a Talent number but no
# leader data, which is what ``refresh --missing-talent`` exists to find.
_MISSING_LEADERS_PART = (
    "(CASE WHEN (payload->'scores'->>'talent_basis') IS NULL"
    " THEN (payload->'scores'->>'talent') IS NULL"
    " ELSE (payload->'scores'->>'talent_leaders') IS NULL END)"
)


def find_cards(
    conn: Connection,
    domains: list[str],
    missing_talent: bool,
    limit: int,
    statuses: Sequence[CardStatus] = CARD_STATUSES,
    after_id: int = 0,
) -> list[StoredCard]:
    """Live cards with their stored payload, for the loop's ``refresh`` and
    ``rescore``: those in ``statuses`` (default every live one; empty means the
    default too), whose domain is in ``domains`` (normalized here, like ``seen``)
    when any are given, and with no leaders' part of Talent when ``missing_talent``
    (``_MISSING_LEADERS_PART``). With neither filter it is every live card: the
    route only allows that behind an explicit ``all=true``. Tombstones are never
    returned. One keyset page: ``id > after_id``, ordered by id, at most
    ``limit``; the caller pages with the last id until a page comes back short."""
    # Every clause is a fixed string; only the bound values come from the request.
    clauses = ["status = ANY(%s)", "id > %s"]
    params: list[Any] = [list(statuses or CARD_STATUSES), after_id]
    if domains:
        clauses.append("domain = ANY(%s)")
        params.append(sorted({d for d in (normalize_domain(x) for x in domains) if d}))
    if missing_talent:
        clauses.append(_MISSING_LEADERS_PART)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, domain, status, payload FROM launch_radar_cards "
            f"WHERE {' AND '.join(clauses)} ORDER BY id LIMIT %s",
            (*params, limit),
        )
        rows = [cast(StoredCard, dict(r)) for r in cur.fetchall()]
    conn.rollback()  # read-only
    return rows


def replace_payload(conn: Connection, card_id: int, payload: dict[str, Any]) -> PayloadReplaced:
    """Replace a live card's payload (the loop's ``refresh``; ``payload`` is the
    validated ``model_dump(mode='json')``).

    404 when the card is missing or a tombstone; 422 (``InvalidDomain``) when the
    payload's domain is not the card's. The status, ``posted_at``,
    ``tracked_company_id``, ``run_id`` and ``updated_by`` are kept;
    ``company_name`` follows the payload and ``updated_at`` moves.
    """
    with conn.cursor() as cur:
        # Locked, so an admin delete cannot tombstone the card between the check and the write.
        cur.execute(
            "SELECT domain, status FROM launch_radar_cards WHERE id = %s FOR UPDATE",
            (card_id,),
        )
        row = cur.fetchone()
        if row is None or row["status"] == "deleted":
            conn.rollback()
            raise NotFound("card not found")
        if payload["domain"] != row["domain"]:
            conn.rollback()
            raise InvalidDomain(
                f"payload domain {payload['domain']!r} is not the card's domain {row['domain']!r}"
            )
        cur.execute(
            "UPDATE launch_radar_cards SET payload = %s, company_name = %s, updated_at = now() "
            "WHERE id = %s RETURNING id, domain, status, posted_at, updated_at",
            (Json(payload), payload["company"], card_id),
        )
        out = cur.fetchone()
    conn.commit()
    return cast(PayloadReplaced, dict(out))


__all__ = [
    "BudgetExceeded",
    "CARD_STATUSES",
    "Conflict",
    "DomainSeen",
    "InvalidDomain",
    "LEDGER_LOCK_KEY",
    "LaunchRadarError",
    "NotFound",
    "card_counts",
    "delete_card",
    "find_cards",
    "finish_run",
    "insert_card",
    "list_cards",
    "list_monitors",
    "normalize_domain",
    "patch_monitor",
    "put_monitor",
    "replace_payload",
    "reserve_spend",
    "run_stats",
    "seen",
    "set_status",
    "start_run",
]
