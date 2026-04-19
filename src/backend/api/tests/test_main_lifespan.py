"""Tests for the FastAPI lifespan startup contract.

The lifespan hook runs `apply_alembic_migrations` BEFORE `init_pool`. If the
migration call raises, the app must NOT start serving requests. A future
regression that wraps the migration call in try/except-log would silently
serve a broken deployment — these tests pin that contract down.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api import main as api_main
from api.config import settings


class TestLifespanHappyPath:
    def test_apply_migrations_called_with_settings_then_init_pool(self):
        call_order: list[str] = []

        def _fake_apply(database_url, env):
            call_order.append("apply")

        def _fake_init(*args, **kwargs):
            call_order.append("init")

        # apply_alembic_migrations / init_pool / close_pool are imported at
        # api.main module top, so patch on api.main. auto_scraper_loop is
        # imported inside lifespan() (`from .services.auto_scraper import
        # auto_scraper_loop`), so it must be patched at its source module.
        # Use `new=_noop_coro` (the async function itself) rather than
        # side_effect — MagicMock with a coroutine-returning side_effect
        # confuses asyncio.create_task and emits "coroutine was never
        # awaited" warnings.
        with patch.object(api_main, "apply_alembic_migrations", side_effect=_fake_apply) as mock_apply, \
             patch.object(api_main, "init_pool", side_effect=_fake_init) as mock_init, \
             patch.object(api_main, "close_pool") as mock_close, \
             patch("api.services.auto_scraper.auto_scraper_loop", new=_noop_coro):
            with TestClient(api_main.app) as client:
                # Lifespan startup completed without raising. The body of
                # the test isn't important; we care about call ordering.
                response = client.get("/health")
                # /health may return 503 because the patched init_pool didn't
                # actually create a pool — that's fine, we only care that
                # lifespan succeeded enough for the app to handle a request.
                assert response.status_code in (200, 503)

        mock_apply.assert_called_once_with(
            settings.database_url, settings.scraper_environment
        )
        mock_init.assert_called_once()
        # apply must precede init.
        assert call_order.index("apply") < call_order.index("init"), (
            f"apply_alembic_migrations must run before init_pool; got order={call_order}"
        )
        # close_pool runs once at shutdown.
        mock_close.assert_called_once()


class TestLifespanFailurePath:
    def test_migration_failure_prevents_pool_init_and_shutdown(self):
        """If apply_alembic_migrations raises, init_pool must NOT run, and
        close_pool must NOT be called during shutdown cleanup either —
        otherwise we'd close a pool that was never opened (or worse, leak
        pool state from a prior test) and mask the real failure."""
        with patch.object(api_main, "apply_alembic_migrations", side_effect=RuntimeError("boom")) as mock_apply, \
             patch.object(api_main, "init_pool") as mock_init, \
             patch.object(api_main, "close_pool") as mock_close, \
             patch("api.services.auto_scraper.auto_scraper_loop", new=_noop_coro):
            with pytest.raises(RuntimeError, match="boom"):
                with TestClient(api_main.app):
                    # Should never reach here — lifespan startup must
                    # propagate the migration failure.
                    pytest.fail("TestClient context entered despite migration failure")

        mock_apply.assert_called_once()
        mock_init.assert_not_called()
        mock_close.assert_not_called()


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
