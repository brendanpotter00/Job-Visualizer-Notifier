"""In-process per-key rate limiting for public endpoints.

A tiny dependency-free sliding-window limiter used to throttle the public,
unauthenticated ``POST /api/feedback`` endpoint (the first anonymous write
surface in the app). Keeping it in-memory is deliberate:

- Production runs a single uvicorn process (see ``src/backend/Dockerfile`` —
  no ``--workers``), so one in-process counter is authoritative.
- It resets on each deploy/restart. For a spam guard with a sub-minute window
  that is acceptable: the abuse it blocks is high-frequency scripted bursts,
  not slow drips spread across restarts.

If the backend ever scales horizontally, or stronger guarantees are needed,
move this behind a shared store (Postgres) or a Vercel WAF rate-limit rule.
``time.monotonic`` is injectable so unit tests are deterministic without
sleeping.
"""

import logging
import threading
import time
from collections import deque
from typing import Callable

from fastapi import HTTPException, Request

from ..config import settings

logger = logging.getLogger(__name__)

# Above this many distinct keys, sweep fully-expired entries so a flood of
# unique IPs can't grow the dict without bound.
_SWEEP_THRESHOLD = 10_000


class SlidingWindowRateLimiter:
    """Per-key sliding-window limiter: at most ``max_requests`` per ``window``.

    Thread-safe (uvicorn may dispatch sync routes on a worker thread pool).
    ``check`` is the only mutating entrypoint: it prunes the key's expired
    timestamps, and either records the hit (returning ``None``) or rejects it
    (returning the seconds until the oldest hit in the window expires).
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._now = time_fn
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> float | None:
        """Record a hit for ``key``. Return ``None`` if allowed, else the
        ``retry_after`` seconds the caller should wait."""
        now = self._now()
        cutoff = now - self._window
        with self._lock:
            if len(self._hits) > _SWEEP_THRESHOLD:
                self._sweep(cutoff)
            bucket = self._hits.get(key)
            if bucket is None:
                bucket = deque()
                self._hits[key] = bucket
            # Drop timestamps that have aged out of the window.
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                # Oldest in-window hit expires self._window after it landed.
                retry_after = bucket[0] + self._window - now
                return max(retry_after, 0.0)
            bucket.append(now)
            return None

    def _sweep(self, cutoff: float) -> None:
        """Drop keys whose every timestamp has aged out. Caller holds the lock."""
        stale = [
            k
            for k, bucket in self._hits.items()
            if not bucket or bucket[-1] <= cutoff
        ]
        for k in stale:
            del self._hits[k]

    def reset(self) -> None:
        """Clear all state. Intended for tests."""
        with self._lock:
            self._hits.clear()


# Module-level singleton for the feedback endpoint, sized from settings.
feedback_rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.feedback_rate_limit_max,
    window_seconds=settings.feedback_rate_limit_window_seconds,
)


def client_ip_from_request(request: Request) -> str:
    """Best-effort client IP for rate-limit keying.

    The Vercel proxy forwards the caller's IP as ``X-Forwarded-For`` (see
    ``api/feedback.ts``). Take the first token — the original client per the XFF
    convention — and fall back to the socket peer when the header is absent
    (e.g. local dev hitting the backend directly).

    Spoofing caveat: a client can prepend fake entries to ``X-Forwarded-For``,
    so a determined attacker can rotate the key and weaken the limit. That is
    inherent to IP-based throttling and acceptable for this threat model; a
    Vercel WAF rule is the stronger upgrade if abuse persists.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_feedback_rate_limit(request: Request) -> None:
    """FastAPI dependency: 429 when the caller exceeds the feedback rate limit."""
    ip = client_ip_from_request(request)
    retry_after = feedback_rate_limiter.check(ip)
    if retry_after is not None:
        logger.info("Rate-limited feedback submission from %s", ip)
        raise HTTPException(
            status_code=429,
            detail=(
                "You're sending feedback too quickly. Please wait a moment and "
                "try again."
            ),
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
