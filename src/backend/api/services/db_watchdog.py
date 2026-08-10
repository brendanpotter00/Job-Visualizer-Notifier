"""Process-level watchdog for a wedged or unreachable database.

Born from the 2026-08-10 incident
(docs/incidents/2026-08-10-postgres-container-freeze-backend-wedge.md): the
Railway Postgres container froze mid-checkpoint. Its host kernel stayed alive
and kept ACKing TCP keepalive probes, so every timeout the app already had —
libpq keepalives, connect_timeout, server-side statement_timeout — was blind.
Established connections blocked in recv() forever, the FastAPI pool wedged one
checkout probe at a time, the Procrastinate connector hung mid-await, and the
process sat "green" but unable to serve for 45+ minutes. Railway's
healthcheckPath could not save us: Railway calls it only to gate deploy
cutover ("not used for continuous monitoring" — Railway docs) and never
restarts a live-but-hung container.

The only detector that survives that failure mode is a wall-clock deadline
enforced OUTSIDE the connection: probe on a fresh connection from a dedicated
thread, join() the probe thread with a hard timeout, and treat "still running"
exactly like "raised". The only recovery that reliably unsticks every layer
(HTTP pool, Procrastinate connector, half-open sockets) is a process exit:
Railway's ON_FAILURE restart policy brings up a clean container, and the
boot-time connectivity retry (``migrations.apply_alembic_migrations_with_retry``)
keeps the restart budget from burning while the DB is still down.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable

from scripts.shared.database import augment_db_url

logger = logging.getLogger(__name__)

# EX_SOFTWARE. Any non-zero exit code triggers Railway's ON_FAILURE restart;
# a distinctive one makes "the watchdog pulled the trigger" greppable.
_EXIT_CODE = 70


def _default_on_fatal() -> None:
    # os._exit, not sys.exit: sys.exit raises SystemExit in *this* thread
    # only — the wedged event loop and blocked pool threads would keep the
    # process alive, which is the exact condition we are escaping. Skipping
    # atexit/finalizers is acceptable: a process whose DB sockets are wedged
    # beyond recovery has nothing left worth flushing that stderr hasn't
    # already received.
    os._exit(_EXIT_CODE)


class DbWatchdog:
    """Periodically probes the database with a hard wall-clock deadline.

    A probe that raises OR fails to finish within ``probe_deadline_s`` counts
    as a failure. Once failures have persisted for ``failure_window_s``
    (measured from the first failure of the streak; any success resets the
    streak), ``on_fatal`` runs — by default exiting the process so the
    platform restarts the container.

    ``probe_fn`` / ``on_fatal`` are injectable for tests only.
    """

    def __init__(
        self,
        dsn: str,
        *,
        probe_interval_s: float,
        probe_deadline_s: float,
        failure_window_s: float,
        probe_fn: Callable[[], None] | None = None,
        on_fatal: Callable[[], None] | None = None,
    ) -> None:
        self._dsn = augment_db_url(dsn, application_name="db_watchdog")
        self._probe_interval_s = probe_interval_s
        self._probe_deadline_s = probe_deadline_s
        self._failure_window_s = failure_window_s
        self._probe_fn: Callable[[], None] = (
            probe_fn if probe_fn is not None else self._default_probe
        )
        self._on_fatal: Callable[[], None] = (
            on_fatal if on_fatal is not None else _default_on_fatal
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._first_failure_monotonic: float | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("DbWatchdog already started")
        self._thread = threading.Thread(
            target=self._run, name="db-watchdog", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            # The loop only ever blocks on the stop event or a bounded
            # probe join, so this join is bounded too.
            self._thread.join(timeout=self._probe_deadline_s + 5.0)

    def _default_probe(self) -> None:
        # Import here so tests injecting probe_fn never touch the driver.
        import psycopg2

        # A FRESH connection each probe is the point: pooled connections can
        # be individually wedged; what we are measuring is "can this process
        # reach the database right now, from scratch".
        conn = psycopg2.connect(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        finally:
            conn.close()

    def _probe_ok(self) -> bool:
        """True iff the probe completed successfully within the deadline.

        The probe runs in its own daemon thread. A probe that HANGS (the
        2026-08-10 signature: connect() or recv() blocked while the frozen
        peer's kernel still ACKs keepalives) counts as a failure the moment
        the deadline elapses. The hung thread is deliberately abandoned; at
        one per interval, leakage is bounded by failure_window/interval
        probes before on_fatal ends the process anyway.
        """
        errors: list[BaseException] = []

        def _target() -> None:
            try:
                self._probe_fn()
            except BaseException as exc:  # any failure is a failure
                errors.append(exc)

        probe_thread = threading.Thread(
            target=_target, name="db-watchdog-probe", daemon=True
        )
        probe_thread.start()
        probe_thread.join(timeout=self._probe_deadline_s)
        if probe_thread.is_alive():
            logger.warning(
                "db_watchdog: probe still running after %.1fs deadline "
                "(treating as failure)",
                self._probe_deadline_s,
            )
            return False
        if errors:
            logger.warning("db_watchdog: probe failed: %s", errors[0])
            return False
        return True

    def _run(self) -> None:
        logger.info(
            "db_watchdog started (interval=%.0fs, probe deadline=%.0fs, "
            "failure window=%.0fs)",
            self._probe_interval_s,
            self._probe_deadline_s,
            self._failure_window_s,
        )
        # wait() first so the app gets one full interval to finish booting
        # before the first probe.
        while not self._stop_event.wait(self._probe_interval_s):
            if self._probe_ok():
                if self._first_failure_monotonic is not None:
                    logger.info(
                        "db_watchdog: database reachable again; failure window reset"
                    )
                    self._first_failure_monotonic = None
                continue
            now = time.monotonic()
            if self._first_failure_monotonic is None:
                self._first_failure_monotonic = now
                continue
            elapsed = now - self._first_failure_monotonic
            if elapsed >= self._failure_window_s:
                logger.critical(
                    "db_watchdog: database unreachable for %.0fs "
                    "(failure window %.0fs exhausted) — exiting so the "
                    "platform restarts the container",
                    elapsed,
                    self._failure_window_s,
                )
                self._on_fatal()
                return
