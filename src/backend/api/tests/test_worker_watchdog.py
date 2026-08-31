"""Unit tests for the worker-liveness watchdog.

No database needed: the heartbeat read, the clock, and the fatal hook are all
injectable. Staleness is made deterministic by pinning ``now_fn`` and the
returned beat; the failure window / startup grace use tiny real intervals plus
a generous wait ceiling so the tests are fast without being flaky under load.

The scenario each test defends is the 2026-08-29 outage: the worker's executor
wedged (``run_worker_async`` hung mid-drain and never returned), the heartbeat
froze while the DB stayed reachable, and nothing restarted the process.
"""

import threading
import time
from datetime import datetime, timezone

import pytest

from api.services.worker_watchdog import WorkerWatchdog

_WAIT_CEILING_S = 10.0
_NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
_FRESH_BEAT = datetime(2026, 8, 31, 11, 59, 30, tzinfo=timezone.utc)  # 30s gap
_STALE_BEAT = datetime(2026, 8, 31, 11, 0, 0, tzinfo=timezone.utc)  # 1h gap


def _wait_for(event: threading.Event, timeout: float = _WAIT_CEILING_S) -> bool:
    return event.wait(timeout)


class TestWorkerWatchdog:
    def _make(
        self,
        read_last_beat_fn,
        on_fatal,
        *,
        now_fn=lambda: _NOW,
        interval: float = 0.01,
        stale_after: float = 60.0,
        window: float = 0.05,
        startup_grace: float = 0.0,
        read_deadline: float = 0.25,
    ) -> WorkerWatchdog:
        return WorkerWatchdog(
            "postgresql://unused:unused@localhost:5/unused",
            probe_interval_s=interval,
            stale_after_s=stale_after,
            failure_window_s=window,
            startup_grace_s=startup_grace,
            read_deadline_s=read_deadline,
            read_last_beat_fn=read_last_beat_fn,
            now_fn=now_fn,
            on_fatal=on_fatal,
        )

    def test_stale_after_seen_alive_triggers_fatal(self) -> None:
        # The exact incident shape: the worker WAS alive (one fresh beat), then
        # its executor wedged and the beat froze. Must restart even under a huge
        # startup grace — the grace only shields a not-yet-started worker.
        fatal = threading.Event()
        calls = {"n": 0}

        def read() -> datetime:
            calls["n"] += 1
            return _FRESH_BEAT if calls["n"] == 1 else _STALE_BEAT

        wd = self._make(read, fatal.set, window=0.05, startup_grace=3600.0)
        wd.start()
        try:
            assert _wait_for(fatal), "wedged-after-alive worker did not restart"
        finally:
            wd.stop()

    def test_sustained_stale_from_boot_triggers_after_grace(self) -> None:
        # A worker that never starts: the heartbeat is stale from the first
        # sample and never goes fresh. With grace ~0 it must still trip.
        fatal = threading.Event()
        wd = self._make(lambda: _STALE_BEAT, fatal.set, startup_grace=0.0)
        wd.start()
        try:
            assert _wait_for(fatal), "worker that never beat did not restart"
        finally:
            wd.stop()

    def test_stale_leftover_ignored_during_startup_grace(self) -> None:
        # After a restart the pre-restart (stale) rows are still present. Until
        # the fresh worker beats, that leftover must NOT trigger a restart while
        # the startup grace is unspent — otherwise every restart crash-loops.
        fatal = threading.Event()
        probed = threading.Event()

        def read() -> datetime:
            probed.set()
            return _STALE_BEAT

        wd = self._make(read, fatal.set, window=0.02, startup_grace=30.0)
        wd.start()
        try:
            assert _wait_for(probed), "watchdog never sampled"
            time.sleep(0.3)  # many intervals
            assert not fatal.is_set(), "restarted on a pre-first-beat leftover"
        finally:
            wd.stop()

    def test_fresh_heartbeat_never_fatal(self) -> None:
        fatal = threading.Event()
        probed = threading.Event()

        def read() -> datetime:
            probed.set()
            return _FRESH_BEAT

        wd = self._make(read, fatal.set)
        wd.start()
        try:
            assert _wait_for(probed), "watchdog never sampled"
            time.sleep(0.3)
            assert not fatal.is_set(), "restarted a healthy worker"
        finally:
            wd.stop()

    def test_fresh_resets_stale_window(self) -> None:
        # Alternate stale/fresh with a window several intervals wide. A working
        # reset means no stale STREAK ever spans the window, so on_fatal never
        # fires; a broken reset would measure every stale sample against the
        # very first and trip within ~window seconds.
        fatal = threading.Event()
        calls = {"n": 0}

        def read() -> datetime:
            calls["n"] += 1
            return _STALE_BEAT if calls["n"] % 2 == 1 else _FRESH_BEAT

        wd = self._make(read, fatal.set, window=0.2)
        wd.start()
        try:
            deadline = time.monotonic() + 8.0
            while calls["n"] < 10 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert calls["n"] >= 10, "watchdog stopped sampling"
            assert not fatal.is_set(), "fired despite intervening fresh beats"
        finally:
            wd.stop()

    def test_unreachable_db_is_inconclusive_not_fatal(self) -> None:
        # A read that raises = DB unreachable = db_watchdog's job, never ours.
        # This watchdog must not restart on a DB outage (it would double-count
        # with db_watchdog and could crash-loop a healthy worker).
        fatal = threading.Event()
        probed = threading.Event()

        def read() -> datetime:
            probed.set()
            raise ConnectionError("db down")

        wd = self._make(read, fatal.set, window=0.02, startup_grace=0.0)
        wd.start()
        try:
            assert _wait_for(probed), "watchdog never sampled"
            time.sleep(0.3)
            assert not fatal.is_set(), "restarted on an unreachable DB"
        finally:
            wd.stop()

    def test_hung_read_is_inconclusive_not_fatal(self) -> None:
        # A read that never returns (frozen socket) must not itself wedge the
        # watchdog loop, and must count as inconclusive (db_watchdog territory),
        # not as a worker-death verdict.
        fatal = threading.Event()
        entered = threading.Event()

        def read() -> datetime:
            entered.set()
            time.sleep(30)
            return _STALE_BEAT

        wd = self._make(read, fatal.set, read_deadline=0.02, window=0.02)
        wd.start()
        try:
            assert _wait_for(entered), "read never entered"
            time.sleep(0.3)
            assert not fatal.is_set(), "a hung read was treated as worker death"
        finally:
            wd.stop()

    def test_no_heartbeat_rows_is_inconclusive(self) -> None:
        # Cold DB before the first beat: MAX(at) is NULL. Not a verdict.
        fatal = threading.Event()
        probed = threading.Event()

        def read() -> None:
            probed.set()
            return None

        wd = self._make(read, fatal.set, window=0.02, startup_grace=0.0)
        wd.start()
        try:
            assert _wait_for(probed), "watchdog never sampled"
            time.sleep(0.3)
            assert not fatal.is_set(), "restarted on an empty heartbeat table"
        finally:
            wd.stop()

    def test_stop_halts_sampling(self) -> None:
        fatal = threading.Event()
        sampled = threading.Event()

        def read() -> datetime:
            sampled.set()
            return _FRESH_BEAT

        wd = self._make(read, fatal.set, window=10.0)
        wd.start()
        assert _wait_for(sampled), "watchdog never sampled"
        wd.stop()
        assert not fatal.is_set()

    def test_start_twice_raises(self) -> None:
        wd = self._make(lambda: _FRESH_BEAT, lambda: None, window=10.0)
        wd.start()
        try:
            with pytest.raises(RuntimeError):
                wd.start()
        finally:
            wd.stop()


class TestDefaultRead:
    def test_reads_max_at_on_augmented_connection(self, monkeypatch) -> None:
        # Pins the load-bearing behavior: a fresh connection on a DSN carrying
        # the watchdog identity, a MAX(at) read of worker_heartbeats, and a
        # naive timestamp coerced to UTC-aware.
        from unittest.mock import MagicMock

        naive = datetime(2026, 8, 31, 11, 0, 0)  # tz-naive, as psycopg may return
        cur = MagicMock()
        cur.fetchone.return_value = (naive,)
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        ctx.__exit__.return_value = False
        conn = MagicMock()
        conn.cursor.return_value = ctx
        connect = MagicMock(return_value=conn)
        monkeypatch.setattr("psycopg2.connect", connect)

        wd = WorkerWatchdog(
            "postgresql://u:p@dbhost:5432/db",
            probe_interval_s=1.0,
            stale_after_s=1.0,
            failure_window_s=1.0,
            startup_grace_s=1.0,
        )
        result = wd._default_read()

        connect.assert_called_once()
        dsn = connect.call_args.args[0]
        assert "application_name=worker_watchdog" in dsn
        assert "worker_heartbeats" in cur.execute.call_args.args[0]
        conn.close.assert_called_once()
        assert result == naive.replace(tzinfo=timezone.utc)
