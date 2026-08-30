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

# ...and for POST /api/companies/resolve, keyed on the authenticated user id
# rather than an IP (the route requires a Bearer token, so there is a real
# identity to key on and no reason to accept a spoofable one).
resolve_rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.resolve_rate_limit_max,
    window_seconds=settings.resolve_rate_limit_window_seconds,
)

# ...and for POST /api/users/companies — the route that actually SPENDS. One call
# can start a headless Chromium session and an LLM call, and until this existed it
# had no rate limit at all: the UI calls ``/resolve`` first, so the front door was
# throttled by accident while a bearer token replayed straight at the add endpoint
# skipped the limiter entirely.
#
# A SEPARATE limiter, not the resolve one reused. The two routes cost different
# things, the UI hits resolve on every submit, and one shared bucket would let a
# page of ordinary previews starve the adds — as well as make the resolve limit's
# tuning silently change how many boards a user may add per minute.
#
# It is only a BURST smoother. It is in-memory and per-process, so it resets on
# every deploy; the real spend guard is the monthly cap in ``add_quota.py``, which
# is a row count in Postgres and survives restarts.
user_company_add_rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.user_company_add_rate_limit_max,
    window_seconds=settings.user_company_add_rate_limit_window_seconds,
)

# ...and for PATCH /api/users/companies/{id} — the rename.
#
# ITS OWN BUCKET, an order of magnitude looser. A rename costs one UPDATE: no browser,
# no outbound request, no LLM call. Sharing the add limiter would make correcting a
# typo eat a slot the add path needs, and it would tie a cheap write's ceiling to an
# expensive one's tuning. The monthly cap is not consulted at all here — that one is
# the spend guard, and a rename spends nothing.
user_company_rename_rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.user_company_rename_rate_limit_max,
    window_seconds=settings.user_company_rename_rate_limit_window_seconds,
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


def enforce_resolve_rate_limit(user_key: str) -> None:
    """429 when ``user_key`` has exceeded the resolve rate limit.

    A plain function rather than a FastAPI dependency: the key is the
    authenticated subject, and importing ``auth.dependencies`` here would point
    a services module at the auth layer for no gain. ``routers/companies.py``
    already resolves the user and calls this first thing in the handler.
    """
    retry_after = resolve_rate_limiter.check(user_key)
    if retry_after is not None:
        logger.info("Rate-limited resolve request from %s", user_key)
        raise HTTPException(
            status_code=429,
            detail=(
                "You're resolving careers URLs too quickly. Please wait a "
                "moment and try again."
            ),
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


def enforce_user_company_add_rate_limit(user_key: str) -> None:
    """429 when ``user_key`` is adding companies faster than the burst limit.

    Same plain-function shape, and the same reasoning, as
    :func:`enforce_resolve_rate_limit`. ``routers/user_companies.py`` calls it
    immediately after the feature-flag check, so a flag-off deployment still
    answers a clean 503 rather than a 429.

    THE WAIT TIME IS IN THE BODY, not only in the header. ``api/users.ts`` forwards
    through ``forwardResponse``, which copies status + body ONLY — the same reason
    ``X-Next-Cursor`` needs its own explicit line in that proxy. A ``Retry-After``
    header therefore never reaches the browser, so a message relying on it would
    read as "too quickly" with no number attached. The header is still sent, because
    direct API callers (curl, the e2e suite) do see it.
    """
    retry_after = user_company_add_rate_limiter.check(user_key)
    if retry_after is not None:
        wait_seconds = int(retry_after) + 1
        logger.info("Rate-limited company add from %s", user_key)
        raise HTTPException(
            status_code=429,
            detail=(
                "You're adding companies too quickly. Please wait about "
                f"{wait_seconds} seconds and try again."
            ),
            headers={"Retry-After": str(wait_seconds)},
        )


def enforce_user_company_rename_rate_limit(user_key: str) -> None:
    """429 when ``user_key`` is renaming companies faster than the burst limit.

    Same plain-function shape as its two neighbours. The wait time is in the BODY as
    well as the header for the reason spelled out in
    :func:`enforce_user_company_add_rate_limit`: ``api/users.ts`` forwards status and
    body only, so a ``Retry-After`` header never reaches the browser.
    """
    retry_after = user_company_rename_rate_limiter.check(user_key)
    if retry_after is not None:
        wait_seconds = int(retry_after) + 1
        logger.info("Rate-limited company rename from %s", user_key)
        raise HTTPException(
            status_code=429,
            detail=(
                "You're renaming companies too quickly. Please wait about "
                f"{wait_seconds} seconds and try again."
            ),
            headers={"Retry-After": str(wait_seconds)},
        )


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
