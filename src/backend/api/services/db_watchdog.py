"""Process-level watchdog for a wedged or unreachable database.

A frozen Postgres whose host kernel still ACKs TCP keepalives defeats every
connection-level timeout (2026-08-10 incident — see
docs/incidents/2026-08-10-postgres-container-freeze-backend-wedge.md). The
only reliable detector is a wall-clock deadline enforced outside the
connection; the only reliable recovery is a process exit, which Railway's
ON_FAILURE restart policy turns into a fresh container.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable

from scripts.shared.database import augment_db_url

logger = logging.getLogger(__name__)

# EX_SOFTWARE — distinctive, greppable "the watchdog pulled the trigger".
_EXIT_CODE = 70


def _default_on_fatal() -> None:
    # os._exit, not sys.exit: SystemExit in this thread would leave the
    # wedged event loop and blocked pool threads running — the exact
    # condition being escaped.
    os._exit(_EXIT_CODE)


class DbWatchdog:
    """Periodically probes the database with a hard wall-clock deadline.

    A probe that raises OR fails to finish within ``probe_deadline_s`` is a
    failure. Once failures persist for ``failure_window_s`` (anchored at the
    first failing probe's start; any success resets), ``on_fatal`` runs —
    by default exiting the process. ``probe_fn`` / ``on_fatal`` are
    injectable for tests only.
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
            # The loop only blocks on the stop event or a bounded probe
            # join, so this join is bounded too.
            self._thread.join(timeout=self._probe_deadline_s + 5.0)

    def _default_probe(self) -> None:
        import psycopg2

        # A FRESH connection each probe is the point: what's measured is
        # "can this process reach the database right now, from scratch" —
        # pooled connections can be individually wedged.
        conn = psycopg2.connect(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        finally:
            conn.close()

    def _probe_ok(self) -> bool:
        """True iff the probe finished successfully within the deadline.

        A probe that hangs (frozen peer whose kernel still ACKs keepalives)
        counts as a failure when the join deadline elapses; the abandoned
        daemon thread is bounded by window/interval leaks before exit.
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

    def _fatal(self, elapsed: float) -> None:
        # Raw fd write, not logging: a wedged process can also have a
        # blocked log handler, and this line must not be deferrable.
        os.write(
            2,
            (
                f"CRITICAL db_watchdog: database unreachable for {elapsed:.0f}s "
                f"(window {self._failure_window_s:.0f}s) — exiting so the "
                f"platform restarts the container\n"
            ).encode(),
        )
        self._on_fatal()

    def _run(self) -> None:
        logger.info(
            "db_watchdog started (interval=%.0fs, probe deadline=%.0fs, "
            "failure window=%.0fs)",
            self._probe_interval_s,
            self._probe_deadline_s,
            self._failure_window_s,
        )
        # wait() first: one full interval of boot grace before probing.
        while not self._stop_event.wait(self._probe_interval_s):
            probe_started = time.monotonic()
            try:
                ok = self._probe_ok()
            except Exception:
                # The watchdog must not die of its own bug or of thread
                # exhaustion — an unexpected error counts as a failed probe.
                logger.exception(
                    "db_watchdog: probe machinery failed (treating as failure)"
                )
                ok = False
            if ok:
                if self._first_failure_monotonic is not None:
                    logger.info(
                        "db_watchdog: database reachable again; failure window reset"
                    )
                    self._first_failure_monotonic = None
                continue
            if self._first_failure_monotonic is None:
                self._first_failure_monotonic = probe_started
                continue
            elapsed = time.monotonic() - self._first_failure_monotonic
            if elapsed >= self._failure_window_s:
                self._fatal(elapsed)
                return
