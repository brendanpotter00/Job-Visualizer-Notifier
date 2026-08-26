"""Unit tests for the DB watchdog and the boot-time migration retry.

No database needed: the watchdog's probe and fatal hooks are injectable, and
the migration retry is tested against a monkeypatched apply function. Timing
uses tiny intervals plus generous wait ceilings so the tests are fast without
being flaky under load.
"""

import threading
import time

import psycopg2
import pytest

from api import migrations
from api.services.db_watchdog import DbWatchdog


_WAIT_CEILING_S = 10.0


def _wait_for(event: threading.Event, timeout: float = _WAIT_CEILING_S) -> bool:
    return event.wait(timeout)


class TestDbWatchdog:
    def _make(
        self,
        probe_fn,
        on_fatal,
        *,
        interval: float = 0.01,
        deadline: float = 0.25,
        window: float = 0.05,
    ) -> DbWatchdog:
        return DbWatchdog(
            "postgresql://unused:unused@localhost:5/unused",
            probe_interval_s=interval,
            probe_deadline_s=deadline,
            failure_window_s=window,
            probe_fn=probe_fn,
            on_fatal=on_fatal,
        )

    def test_sustained_probe_failure_triggers_fatal(self) -> None:
        fatal = threading.Event()

        def probe() -> None:
            raise ConnectionError("db down")

        wd = self._make(probe, fatal.set)
        wd.start()
        try:
            assert _wait_for(fatal), "on_fatal not called despite sustained failures"
        finally:
            wd.stop()

    def test_hung_probe_counts_as_failure(self) -> None:
        # The 2026-08-10 signature: the probe neither succeeds nor raises —
        # it just never returns. Must still trip the failure window.
        fatal = threading.Event()

        def probe() -> None:
            time.sleep(30)

        wd = self._make(probe, fatal.set, deadline=0.02)
        wd.start()
        try:
            assert _wait_for(fatal), "hung probe did not count as failure"
        finally:
            wd.stop()

    def test_probe_success_resets_failure_window(self) -> None:
        # Alternate failure/success with a window several intervals wide. A
        # working reset means no failure STREAK ever spans the window, so
        # on_fatal never fires; a broken reset would measure every failure
        # against the very first one and trip within ~window seconds.
        fatal = threading.Event()
        calls = {"n": 0}

        def probe() -> None:
            calls["n"] += 1
            if calls["n"] % 2 == 1:
                raise ConnectionError("transient blip")

        wd = self._make(probe, fatal.set, window=0.2)
        wd.start()
        try:
            deadline = time.monotonic() + 8.0
            while calls["n"] < 10 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert calls["n"] >= 10, "watchdog stopped probing"
            assert not fatal.is_set(), "on_fatal fired despite intervening successes"
        finally:
            wd.stop()

    def test_stop_halts_probing(self) -> None:
        fatal = threading.Event()
        probed = threading.Event()

        wd = self._make(probed.set, fatal.set, window=10.0)
        wd.start()
        assert _wait_for(probed), "watchdog never probed"
        wd.stop()
        assert not fatal.is_set()

    def test_start_twice_raises(self) -> None:
        wd = self._make(lambda: None, lambda: None, window=10.0)
        wd.start()
        try:
            with pytest.raises(RuntimeError):
                wd.start()
        finally:
            wd.stop()


class TestDefaultProbe:
    def test_opens_a_fresh_augmented_connection(self, monkeypatch) -> None:
        # Pins the load-bearing behavior: a NEW connection per probe (never
        # the pool), on a DSN carrying keepalives + a watchdog identity.
        from unittest.mock import MagicMock

        conn = MagicMock()
        connect = MagicMock(return_value=conn)
        monkeypatch.setattr("psycopg2.connect", connect)

        wd = DbWatchdog(
            "postgresql://u:p@dbhost:5432/db",
            probe_interval_s=1.0,
            probe_deadline_s=1.0,
            failure_window_s=1.0,
        )
        wd._default_probe()

        connect.assert_called_once()
        dsn = connect.call_args.args[0]
        assert "application_name=db_watchdog" in dsn
        assert "connect_timeout=10" in dsn
        conn.close.assert_called_once()


class TestApplyMigrationsWithRetry:
    def test_connectivity_error_retries_then_succeeds(self, monkeypatch) -> None:
        calls: list[str] = []

        def fake_apply(database_url: str) -> None:
            calls.append(database_url)
            if len(calls) < 3:
                raise psycopg2.OperationalError(
                    'connection to server at "dbhost" failed: Connection refused'
                )

        monkeypatch.setattr(migrations, "apply_alembic_migrations", fake_apply)
        monkeypatch.setattr(migrations.time, "sleep", lambda s: None)

        migrations.apply_alembic_migrations_with_retry("postgresql://x", 60.0)
        assert len(calls) == 3
        # Boot path must carry the augmented DSN (keepalives + identity).
        assert "application_name=alembic_startup" in calls[0]

    def test_auth_failure_raises_immediately(self, monkeypatch) -> None:
        # OperationalError but NOT connectivity: retrying a bad password for
        # the whole boot budget would hide a broken deploy.
        calls = {"n": 0}

        def fake_apply(database_url: str) -> None:
            calls["n"] += 1
            raise psycopg2.OperationalError(
                'connection to server at "dbhost" failed: FATAL:  '
                'password authentication failed for user "postgres"'
            )

        monkeypatch.setattr(migrations, "apply_alembic_migrations", fake_apply)
        monkeypatch.setattr(migrations.time, "sleep", lambda s: None)

        with pytest.raises(psycopg2.OperationalError):
            migrations.apply_alembic_migrations_with_retry("postgresql://x", 60.0)
        assert calls["n"] == 1

    def test_disk_full_raises_immediately(self, monkeypatch) -> None:
        # DiskFull subclasses OperationalError (the 2026-04-18 incident
        # class) — must fail the deploy, not retry.
        calls = {"n": 0}

        def fake_apply(database_url: str) -> None:
            calls["n"] += 1
            raise psycopg2.errors.DiskFull(
                "could not extend file: No space left on device"
            )

        monkeypatch.setattr(migrations, "apply_alembic_migrations", fake_apply)
        monkeypatch.setattr(migrations.time, "sleep", lambda s: None)

        with pytest.raises(psycopg2.OperationalError):
            migrations.apply_alembic_migrations_with_retry("postgresql://x", 60.0)
        assert calls["n"] == 1

    def test_non_operational_error_raises_immediately(self, monkeypatch) -> None:
        def fake_apply(database_url: str) -> None:
            raise ValueError("broken revision")

        monkeypatch.setattr(migrations, "apply_alembic_migrations", fake_apply)

        with pytest.raises(ValueError):
            migrations.apply_alembic_migrations_with_retry("postgresql://x", 60.0)

    def test_budget_exhaustion_reraises_connectivity_error(self, monkeypatch) -> None:
        def fake_apply(database_url: str) -> None:
            raise psycopg2.OperationalError(
                'connection to server at "dbhost" failed: timeout expired'
            )

        monkeypatch.setattr(migrations, "apply_alembic_migrations", fake_apply)
        monkeypatch.setattr(migrations.time, "sleep", lambda s: None)

        with pytest.raises(psycopg2.OperationalError):
            migrations.apply_alembic_migrations_with_retry("postgresql://x", 0.0)
