"""The only module that imports the Parallel SDK at runtime.

The import is lazy so the unit tests (which inject a fake client) run without
``parallel-web`` installed. The SDK reads ``PARALLEL_API_KEY`` from the
environment itself; this code never reads, logs or stores the key.
"""

from __future__ import annotations

from typing import Any


def make_client() -> Any:
    from parallel import Parallel

    # max_retries=0: the SDK retries POSTs without an idempotency key, so a
    # retried create could start (and bill) a second run.
    return Parallel().with_options(max_retries=0)


def status_code_of(exc: BaseException) -> int | None:
    """HTTP status of a Parallel ``APIStatusError`` (duck-typed, no SDK import)."""
    code = getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None
