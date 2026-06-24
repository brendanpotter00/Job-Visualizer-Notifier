"""PostHog analytics client — module-level singleton.

Initialized once from lifespan; imported in routers to capture events.
Call ``init_posthog`` on startup and ``shutdown_posthog`` on shutdown.
"""

from posthog import Posthog

_client: Posthog | None = None


def init_posthog(api_key: str, host: str) -> None:
    global _client
    _client = Posthog(api_key, host=host, enable_exception_autocapture=True)


def shutdown_posthog() -> None:
    if _client is not None:
        _client.shutdown()


def get_posthog() -> Posthog | None:
    return _client
