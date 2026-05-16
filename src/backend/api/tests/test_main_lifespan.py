"""Tests for the FastAPI lifespan startup contract.

The lifespan hook runs `apply_alembic_migrations` BEFORE `init_pool`. If the
migration call raises, the app must NOT start serving requests. A future
regression that wraps the migration call in try/except-log would silently
serve a broken deployment — these tests pin that contract down.

After Unit 1 of greenhouseBackendMigration, lifespan also opens the
Procrastinate connector + applies its schema between ``apply`` and ``init``,
and runs an in-process worker task. Those steps are patched here with
AsyncMock stand-ins so the unit tests don't touch the real DB.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import psycopg2
import pytest
from fastapi.testclient import TestClient

from api import main as api_main
from api.config import settings


def _make_fake_procrastinate(call_order: list[str] | None = None) -> MagicMock:
    """Build a stand-in for ``api.main.procrastinate_app``.

    Replaces the real ``App`` so lifespan doesn't actually open a Postgres
    pool. ``run_worker_async`` returns a forever-sleeping coroutine that the
    lifespan can cancel cleanly — matching the real worker's long-running
    shape and avoiding ``coroutine was never awaited`` warnings.
    """
    fake = MagicMock(name="procrastinate_app")
    fake.open_async = AsyncMock(
        side_effect=(lambda: call_order.append("open")) if call_order is not None else None
    )
    fake.close_async = AsyncMock()

    async def _forever_worker(*args, **kwargs):
        if call_order is not None:
            call_order.append("worker")
        import asyncio as _asyncio
        try:
            await _asyncio.Event().wait()
        except _asyncio.CancelledError:
            raise

    fake.run_worker_async = _forever_worker
    return fake


class TestLifespanHappyPath:
    def test_apply_migrations_called_with_settings_then_init_pool(self):
        call_order: list[str] = []

        def _fake_apply(database_url):
            call_order.append("apply")

        def _fake_init(*args, **kwargs):
            call_order.append("init")

        async def _fake_ensure_schema(app):
            call_order.append("schema")

        async def _tracking_scraper(*args, **kwargs):
            # Record that the auto-scraper task actually started, so the
            # ordering assertion below can pin "scraper launches AFTER
            # init_pool" — a future regression that moves create_task above
            # apply_alembic_migrations would background-start the scraper
            # while the DB pool is uninitialized, which this pins down.
            call_order.append("scraper")
            import asyncio as _asyncio
            try:
                await _asyncio.Event().wait()
            except _asyncio.CancelledError:
                raise

        fake_procrastinate = _make_fake_procrastinate(call_order)

        # apply_alembic_migrations / init_pool / close_pool / procrastinate_app
        # are imported at api.main module top, so patch on api.main.
        # auto_scraper_loop is imported inside lifespan() (`from
        # .services.auto_scraper import auto_scraper_loop`), so it must be
        # patched at its source module. Use `new=_tracking_scraper` (the
        # async function itself) rather than side_effect — MagicMock with a
        # coroutine-returning side_effect confuses asyncio.create_task and
        # emits "coroutine was never awaited" warnings.
        with patch.object(api_main, "apply_alembic_migrations", side_effect=_fake_apply) as mock_apply, \
             patch.object(api_main, "init_pool", side_effect=_fake_init) as mock_init, \
             patch.object(api_main, "close_pool") as mock_close, \
             patch.object(api_main, "procrastinate_app", new=fake_procrastinate), \
             patch.object(api_main, "ensure_schema_async", new=_fake_ensure_schema), \
             patch("api.services.auto_scraper.auto_scraper_loop", new=_tracking_scraper):
            with TestClient(api_main.app) as client:
                # Lifespan startup completed without raising. The body of
                # the test isn't important; we care about call ordering.
                response = client.get("/health")
                # /health may return 503 because the patched init_pool didn't
                # actually create a pool — that's fine, we only care that
                # lifespan succeeded enough for the app to handle a request.
                assert response.status_code in (200, 503)

        mock_apply.assert_called_once_with(settings.database_url)
        mock_init.assert_called_once()
        # apply must precede open (Procrastinate connector) which must
        # precede init (request-path pool) which must precede the worker and
        # auto-scraper background tasks. Reordering risks: scraper starts
        # before pool exists; worker queries procrastinate_jobs before
        # schema is in place; etc.
        for step in ("apply", "open", "schema", "init", "scraper", "worker"):
            assert step in call_order, f"missing {step!r} in call_order={call_order}"
        assert (
            call_order.index("apply")
            < call_order.index("open")
            < call_order.index("schema")
            < call_order.index("init")
            < call_order.index("scraper")
            < call_order.index("worker")
        ), (
            f"lifecycle must be apply → open → schema → init → scraper → worker; "
            f"got order={call_order}"
        )
        # close_pool runs once at shutdown.
        mock_close.assert_called_once()
        fake_procrastinate.close_async.assert_called_once()


class TestLifespanFailurePath:
    def test_migration_failure_prevents_pool_init_and_shutdown(self):
        """If apply_alembic_migrations raises, init_pool must NOT run, and
        close_pool must NOT be called during shutdown cleanup either —
        otherwise we'd close a pool that was never opened (or worse, leak
        pool state from a prior test) and mask the real failure.

        After Unit 1: the Procrastinate connector also must NOT be opened
        if migrations failed, since open_async/apply_schema both assume the
        DB is migrated.
        """
        fake_procrastinate = _make_fake_procrastinate()
        async def _fake_ensure_schema(app):
            pass
        with patch.object(api_main, "apply_alembic_migrations", side_effect=RuntimeError("boom")) as mock_apply, \
             patch.object(api_main, "init_pool") as mock_init, \
             patch.object(api_main, "close_pool") as mock_close, \
             patch.object(api_main, "procrastinate_app", new=fake_procrastinate), \
             patch.object(api_main, "ensure_schema_async", new=_fake_ensure_schema), \
             patch("api.services.auto_scraper.auto_scraper_loop", new=_noop_coro):
            with pytest.raises(RuntimeError, match="boom"):
                with TestClient(api_main.app):
                    # Should never reach here — lifespan startup must
                    # propagate the migration failure.
                    pytest.fail("TestClient context entered despite migration failure")

        mock_apply.assert_called_once()
        mock_init.assert_not_called()
        mock_close.assert_not_called()
        fake_procrastinate.open_async.assert_not_called()
        fake_procrastinate.close_async.assert_not_called()


async def _noop_coro(*args, **kwargs):
    """Stand-in for auto_scraper_loop(settings). Sleeps forever so the
    lifespan's shutdown path (cancel + await) actually has something to
    cancel — matches the real auto_scraper_loop's long-running shape and
    avoids 'coroutine was never awaited' warnings from completing before
    the task-done callback fires."""
    import asyncio
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        raise


class TestLifespanSeedFailureGuard:
    """If `seed_starter_features` raises `psycopg2.Error`, the app must
    still boot — the seed is best-effort lifecycle work, not a hard
    prerequisite for serving requests. The lifespan guards the seed call
    with `try/except (psycopg2.Error, RuntimeError)` and logs via
    `logger.exception`. A regression that dropped the guard would make a
    transient DB hiccup during seed INSERTs a full boot failure.
    """

    def _fake_get_db(self):
        """Stand-in for `get_db()` that yields a Mock connection without
        needing a real pool. The lifespan only drives the generator via
        `next(gen)` twice (once to retrieve the conn, once to exhaust it);
        mirror that contract exactly.
        """
        from unittest.mock import MagicMock
        def _gen():
            yield MagicMock()
        return _gen()

    def test_psycopg2_error_during_seed_does_not_prevent_app_boot(self):
        def _failing_seed(conn):
            raise psycopg2.OperationalError("seed boom")

        fake_procrastinate = _make_fake_procrastinate()
        async def _fake_ensure_schema(app):
            pass

        # Patch at the source module — main.py imports the function
        # inside the lifespan body via `from .services.features_seed
        # import seed_starter_features`, so patching `api.main.<name>`
        # would miss the import. Same story for `get_db` (imported inline).
        with patch(
            "api.services.features_seed.seed_starter_features",
            side_effect=_failing_seed,
        ) as mock_seed, \
             patch(
                 "api.dependencies.get_db",
                 side_effect=lambda: self._fake_get_db(),
             ), \
             patch.object(api_main, "apply_alembic_migrations") as mock_apply, \
             patch.object(api_main, "init_pool") as mock_init, \
             patch.object(api_main, "close_pool"), \
             patch.object(api_main, "procrastinate_app", new=fake_procrastinate), \
             patch.object(api_main, "ensure_schema_async", new=_fake_ensure_schema), \
             patch("api.services.auto_scraper.auto_scraper_loop", new=_noop_coro):
            # Lifespan startup must complete successfully despite the seed
            # raising psycopg2.Error. If the guard were removed, entering
            # the TestClient context would re-raise and this with-block
            # would throw.
            with TestClient(api_main.app) as client:
                resp = client.get("/health")
                # /health returns 200 when the pool is healthy, 503 when
                # the patched init_pool didn't create a real pool. Either
                # is fine here — the point is the app booted (no exception
                # propagated out of lifespan), which is what the guard is
                # load-bearing for.
                assert resp.status_code in (200, 503)

        mock_apply.assert_called_once()
        mock_init.assert_called_once()
        mock_seed.assert_called_once()

    def test_runtime_error_during_seed_does_not_prevent_app_boot(self):
        """Parallel guard arm: the same except clause also catches
        `RuntimeError` (e.g. from get_db() / pool-not-initialized). Both
        branches of `(psycopg2.Error, RuntimeError)` must keep the app
        alive.
        """
        def _failing_seed(conn):
            raise RuntimeError("simulated get_db failure")

        fake_procrastinate = _make_fake_procrastinate()
        async def _fake_ensure_schema(app):
            pass

        with patch(
            "api.services.features_seed.seed_starter_features",
            side_effect=_failing_seed,
        ), \
             patch(
                 "api.dependencies.get_db",
                 side_effect=lambda: self._fake_get_db(),
             ), \
             patch.object(api_main, "apply_alembic_migrations"), \
             patch.object(api_main, "init_pool"), \
             patch.object(api_main, "close_pool"), \
             patch.object(api_main, "procrastinate_app", new=fake_procrastinate), \
             patch.object(api_main, "ensure_schema_async", new=_fake_ensure_schema), \
             patch("api.services.auto_scraper.auto_scraper_loop", new=_noop_coro):
            with TestClient(api_main.app) as client:
                resp = client.get("/health")
                assert resp.status_code in (200, 503)
