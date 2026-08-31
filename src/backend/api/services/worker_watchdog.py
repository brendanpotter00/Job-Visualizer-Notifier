"""Process-level watchdog for a wedged Procrastinate worker.

Companion to :mod:`db_watchdog`. The DB watchdog catches an unreachable or
frozen *database*; this one catches the opposite failure — the database is
healthy but the *worker* has stopped executing jobs, so nothing drains the
queue and no scrape/close cycle runs.

2026-08-29 incident (``docs/incidents/2026-08-29-procrastinate-worker-wedge-
silent-outage.md``): a transient DB blip made the worker's main coroutine raise
``ConnectorException``; Procrastinate requested a graceful stop and then waited
forever for in-flight jobs that could not drain, so ``run_worker_async`` HUNG —
it never returned and never raised. The lifespan supervisor
(``_supervised_worker``) only reacts to a return or an exception, so nothing
restarted it: uvicorn kept serving and the periodic deferrer kept enqueueing
while the executor was dead for 61 hours. ``/health/worker`` went 503, but
Railway consults that path only at deploy cutover — never to restart a
live-but-hung container (see ``railway.toml``).

A hung coroutine cannot be recovered in-process: the cancellation that would
unstick it is swallowed by ``psycopg_pool`` on the async pool, so the task
cannot be cancelled. The only reliable recovery is a process exit, which
Railway's ``ON_FAILURE`` policy turns into a fresh container.

Liveness signal: freshness of ``worker_heartbeats.at``. That row advances ONLY
when the worker *executes* the ``worker_heartbeat`` task. It is deliberately
NOT ``procrastinate_events`` — the periodic deferrer keeps writing ``deferred``
events even with a dead executor, which is exactly why event freshness stayed
green for the whole 61h outage while the heartbeat froze. A stale heartbeat
with a REACHABLE database therefore means "the executor is wedged", which is
this watchdog's trigger. An *unreachable* database is inconclusive here and is
left to :mod:`db_watchdog`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

from scripts.shared.database import augment_db_url

logger = logging.getLogger(__name__)

# EX_TEMPFAIL — distinctive from db_watchdog's 70, greppable as "the worker
# watchdog pulled the trigger". Any non-zero code engages Railway ON_FAILURE.
_EXIT_CODE = 75

# One liveness sample's verdict.
_FRESH = "fresh"  # heartbeat within the staleness window — worker alive
_STALE = "stale"  # heartbeat older than the window, DB reachable — worker dead
_INCONCLUSIVE = "inconclusive"  # DB unreachable / no rows yet — db_watchdog's job


def _default_on_fatal() -> None:
    # os._exit, not sys.exit: SystemExit in this thread would leave the wedged
    # event loop and blocked pool threads running — the exact condition being
    # escaped.
    os._exit(_EXIT_CODE)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkerWatchdog:
    """Exits the process when the Procrastinate worker stops heartbeating.

    Every ``probe_interval_s`` it reads ``MAX(worker_heartbeats.at)`` on a fresh
    connection and classifies the result:

    * **fresh** (gap <= ``stale_after_s``) — worker alive; the stale window resets
      and the worker is marked as having been seen alive at least once.
    * **inconclusive** (read failed / timed out / no rows) — the database is
      unreachable or cold; neither accumulates toward nor resets the verdict.
      Sustained DB unreachability is :class:`DbWatchdog`'s responsibility.
    * **stale** (gap > ``stale_after_s``, DB reachable) — the executor is wedged.

    Once *stale* persists for ``failure_window_s`` (anchored at the first stale
    sample; any *fresh* sample resets it), ``on_fatal`` runs — by default exiting
    the process so Railway restarts the container.

    Boot safety: after a restart the pre-restart heartbeat rows are still present
    (``cleanup_heartbeats`` is itself a worker task, so a dead worker never prunes
    them), so ``MAX(at)`` reads *stale* immediately. Until the freshly-started
    worker has produced its first beat, a stale sample is ignored for
    ``startup_grace_s`` — long enough for a healthy worker to beat, short enough
    that a worker which never starts still trips the window.

    ``read_last_beat_fn`` / ``now_fn`` / ``on_fatal`` are injectable for tests.
    """

    # Best-effort join on stop(); see stop() for why it is a small constant
    # rather than the read deadline.
    _STOP_JOIN_TIMEOUT_S = 2.0

    def __init__(
        self,
        dsn: str,
        *,
        probe_interval_s: float,
        stale_after_s: float,
        failure_window_s: float,
        startup_grace_s: float,
        read_deadline_s: float = 15.0,
        read_last_beat_fn: Callable[[], datetime | None] | None = None,
        now_fn: Callable[[], datetime] | None = None,
        on_fatal: Callable[[], None] | None = None,
    ) -> None:
        # statement_timeout bounds the SELECT; augment_db_url also adds
        # keepalives + connect_timeout so a half-open socket can't block recv().
        self._dsn = augment_db_url(
            dsn, application_name="worker_watchdog", statement_timeout_ms=10_000
        )
        self._probe_interval_s = probe_interval_s
        self._stale_after_s = stale_after_s
        self._failure_window_s = failure_window_s
        self._startup_grace_s = startup_grace_s
        self._read_deadline_s = read_deadline_s
        self._read_last_beat: Callable[[], datetime | None] = (
            read_last_beat_fn if read_last_beat_fn is not None else self._default_read
        )
        self._now: Callable[[], datetime] = (
            now_fn if now_fn is not None else _utc_now
        )
        self._on_fatal: Callable[[], None] = (
            on_fatal if on_fatal is not None else _default_on_fatal
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_monotonic: float | None = None
        self._worker_seen_alive = False
        self._first_stale_monotonic: float | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("WorkerWatchdog already started")
        self._thread = threading.Thread(
            target=self._run, name="worker-watchdog", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        # Setting the event is what matters: the loop checks it and will not
        # os._exit after stop() is called. The join is a short best-effort
        # cleanup — it is NOT sized to the read deadline, because on a
        # shutdown path a read that is mid-hang (a freezing DB) must not make
        # stop() block for ~15s and push the whole shutdown past Railway's
        # SIGTERM->SIGKILL grace. The thread is a daemon and dies with the
        # process regardless.
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._STOP_JOIN_TIMEOUT_S)

    def _default_read(self) -> datetime | None:
        import psycopg2

        # A FRESH connection each read (never the pool): a pooled connection
        # can be individually wedged, and we are specifically asking "is the
        # executor advancing the heartbeat", which a wedged read can't answer.
        conn = psycopg2.connect(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(at) FROM worker_heartbeats")
                row = cur.fetchone()
        finally:
            conn.close()
        latest = row[0] if row else None
        if latest is not None and latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        return latest

    def _sample(self) -> str:
        """Read the heartbeat with a hard deadline; classify freshness.

        A read that raises, times out, or returns no row is *inconclusive* —
        an unreachable/cold DB is db_watchdog's domain, not a worker-death
        verdict. Runs the read in a daemon sub-thread so a frozen socket that
        outlives its own timeouts can't wedge the watchdog loop itself.
        """
        result: list[datetime | None] = []
        errors: list[BaseException] = []

        def _target() -> None:
            try:
                result.append(self._read_last_beat())
            except BaseException as exc:  # any failure is inconclusive
                errors.append(exc)

        reader = threading.Thread(
            target=_target, name="worker-watchdog-read", daemon=True
        )
        reader.start()
        reader.join(timeout=self._read_deadline_s)
        if reader.is_alive():
            logger.warning(
                "worker_watchdog: heartbeat read exceeded %.1fs deadline "
                "(inconclusive)",
                self._read_deadline_s,
            )
            return _INCONCLUSIVE
        if errors:
            logger.warning(
                "worker_watchdog: heartbeat read failed: %s (inconclusive)",
                errors[0],
            )
            return _INCONCLUSIVE
        if not result:
            # Read returned nothing without erroring — shouldn't happen, but
            # treat as inconclusive rather than invent a verdict.
            return _INCONCLUSIVE
        last_beat = result[0]
        if last_beat is None:
            # The read SUCCEEDED (DB reachable) but the table is empty — no
            # beat has ever been written. This is "not fresh", not
            # "inconclusive": at cold start the startup grace tolerates it, and
            # past the grace with a reachable DB and no beat ever, it means the
            # worker failed to start and should trip. (A dead worker never
            # empties the table — cleanup_heartbeats is itself a worker task —
            # so in the wedge case MAX(at) is a stale timestamp, not NULL.)
            return _STALE
        gap = (self._now() - last_beat).total_seconds()
        return _FRESH if gap <= self._stale_after_s else _STALE

    def _fatal(self, elapsed: float) -> None:
        # Raw fd write, not logging: a wedged process can also have a blocked
        # log handler, and this line must not be deferrable.
        os.write(
            2,
            (
                f"CRITICAL worker_watchdog: Procrastinate worker heartbeat stale "
                f"for >{self._stale_after_s:.0f}s and sustained {elapsed:.0f}s "
                f"over the {self._failure_window_s:.0f}s window while the database "
                f"is reachable — the job executor is wedged; exiting so the "
                f"platform restarts the container\n"
            ).encode(),
        )
        self._on_fatal()

    def _run(self) -> None:
        self._start_monotonic = time.monotonic()
        logger.info(
            "worker_watchdog started (interval=%.0fs, stale_after=%.0fs, "
            "window=%.0fs, startup_grace=%.0fs)",
            self._probe_interval_s,
            self._stale_after_s,
            self._failure_window_s,
            self._startup_grace_s,
        )
        # wait() first: one full interval of grace before the first sample.
        while not self._stop_event.wait(self._probe_interval_s):
            sample_started = time.monotonic()
            try:
                state = self._sample()
            except Exception:
                # The watchdog must not die of its own bug or thread
                # exhaustion — an unexpected error is inconclusive, not fatal.
                logger.exception(
                    "worker_watchdog: sample machinery failed (inconclusive)"
                )
                state = _INCONCLUSIVE

            if state == _FRESH:
                self._worker_seen_alive = True
                if self._first_stale_monotonic is not None:
                    logger.info(
                        "worker_watchdog: heartbeat fresh again; stale window reset"
                    )
                    self._first_stale_monotonic = None
                continue

            if state == _INCONCLUSIVE:
                # DB unreachable / cold — neither accumulate nor reset; a later
                # conclusive sample decides. Sustained DB-down is db_watchdog's.
                continue

            # state == _STALE
            if not self._worker_seen_alive:
                assert self._start_monotonic is not None
                uptime = sample_started - self._start_monotonic
                if uptime < self._startup_grace_s:
                    # Pre-first-beat: the stale row is a leftover from before
                    # this process started. Don't judge the worker until it has
                    # had a fair chance to produce its first beat.
                    continue
                # Grace elapsed with the DB reachable and no fresh beat ever
                # seen — the worker failed to start. Fall through and trip it.

            if self._first_stale_monotonic is None:
                self._first_stale_monotonic = sample_started
                continue
            elapsed = time.monotonic() - self._first_stale_monotonic
            if elapsed >= self._failure_window_s:
                self._fatal(elapsed)
                return
