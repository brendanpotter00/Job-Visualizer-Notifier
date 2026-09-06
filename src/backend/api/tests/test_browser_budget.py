"""The browser budget — the cap that makes 6 interactive queue slots safe.

``main._INTERACTIVE_WORKER_CONCURRENCY`` is 6 so that six simultaneous company
adds all START. Six slots would also let six headless Chromium processes exist at
once, which a 4.0 GB / 1 vCPU Railway container cannot hold. Production does not
currently reach that state — see ``services/browser_budget`` for exactly why, and
for the two live-in-code paths that would. This module proves the cap is real
rather than aspirational.

These tests are deliberately NOT "assert the constant is 4". They drive the real
``_subprocess_run`` on BOTH spawn sites with a fake ``create_subprocess_exec``
that records the maximum number of children alive simultaneously, fire more
concurrent calls than the cap, and assert the observed peak never exceeded it.

The cap is LOCAL-PATH ONLY: a discovery capture that attaches to a remote
Browserbase browser over CDP costs this container no browser, so it must take no
permit. That is the production-normal path, and
``test_capture_takes_no_permit_when_the_browser_is_REMOTE`` is what keeps a
future edit from quietly serialising it.

The load-bearing one is
``test_the_two_spawn_sites_share_one_budget_so_the_bound_is_not_doubled``: if the
two sites ever construct their own semaphore instead of importing the shared one,
the effective bound silently becomes 8 and everything else here still passes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from api.services import browser_budget
from api.services.browser_budget import (
    MAX_CONCURRENT_BROWSERS,
    browser_permit,
    get_browser_budget,
)
from api.services.browser_fetch.runner import (
    _subprocess_run as browser_fetch_subprocess_run,
)
from api.services.capture.network_capture import (
    _subprocess_run as capture_subprocess_run,
)

pytestmark = pytest.mark.asyncio


# The number of concurrent callers every test fires. Comfortably above the cap so
# a missing or per-site semaphore shows up as a peak well past 4.
_OVERSUBSCRIBE = 12


class _PeakTracker:
    """Counts simultaneous holders and remembers the high-water mark."""

    def __init__(self) -> None:
        self.live = 0
        self.peak = 0
        self.entered = 0

    def enter(self) -> None:
        self.live += 1
        self.entered += 1
        self.peak = max(self.peak, self.live)

    def exit(self) -> None:
        self.live -= 1


async def _settle() -> None:
    """Let every runnable task make all the progress it can.

    The gate below is never opened while this runs, so once the loop quiesces,
    exactly as many holders are inside as the semaphore permits — no sleeps, no
    timing assumptions, and a broken bound shows up as a peak of 12 rather than
    as a flake.
    """
    for _ in range(200):
        await asyncio.sleep(0)


# --------------------------------------------------------------------------
# the limiter itself
# --------------------------------------------------------------------------

async def test_permit_never_admits_more_than_the_cap() -> None:
    tracker = _PeakTracker()
    gate = asyncio.Event()

    async def _hold() -> None:
        async with browser_permit():
            tracker.enter()
            try:
                await gate.wait()
            finally:
                tracker.exit()

    tasks = [asyncio.create_task(_hold()) for _ in range(_OVERSUBSCRIBE)]
    await _settle()

    # The whole point: 12 callers asked, 4 are inside, 8 are waiting.
    assert tracker.peak == MAX_CONCURRENT_BROWSERS
    assert tracker.live == MAX_CONCURRENT_BROWSERS
    assert tracker.entered == MAX_CONCURRENT_BROWSERS

    gate.set()
    await asyncio.gather(*tasks)

    # Everyone eventually got in — the cap DELAYS work, it never drops it — and
    # the peak still never exceeded 4 across the whole run.
    assert tracker.entered == _OVERSUBSCRIBE
    assert tracker.peak == MAX_CONCURRENT_BROWSERS
    assert tracker.live == 0


async def test_permit_is_released_when_the_body_raises() -> None:
    """A leaked permit would shrink the cap for the life of the process."""
    for _ in range(MAX_CONCURRENT_BROWSERS * 3):
        with pytest.raises(RuntimeError):
            async with browser_permit():
                raise RuntimeError("boom")

    budget = get_browser_budget()
    acquired = [budget.acquire() for _ in range(MAX_CONCURRENT_BROWSERS)]
    await asyncio.wait_for(asyncio.gather(*acquired), timeout=1)
    assert budget.locked()
    for _ in range(MAX_CONCURRENT_BROWSERS):
        budget.release()


async def test_budget_is_one_shared_instance_per_loop() -> None:
    assert get_browser_budget() is get_browser_budget()
    # Constructed lazily, from inside a running loop — never at import time.
    assert asyncio.get_running_loop() in browser_budget._BUDGETS


# --------------------------------------------------------------------------
# the real spawn sites
# --------------------------------------------------------------------------

_BROWSER_FETCH_REPORT = json.dumps(
    {"pages": [{"status": 200, "text": "{}"}], "pages_fetched": 1}
).encode()
_CAPTURE_REPORT = json.dumps(
    {"responses": [], "final_url": "https://example.com/jobs"}
).encode()


class _FakeStdin:
    def write(self, data: bytes) -> None:
        return None

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeChild:
    """A stand-in for one live Chromium subprocess.

    It enters the tracker the moment the parent starts waiting on it and leaves
    only when *gate* opens, so "inside the tracker" == "a child is alive", which
    is exactly the window a permit is supposed to cover.
    """

    returncode = 0

    def __init__(self, tracker: _PeakTracker, gate: asyncio.Event, report: bytes) -> None:
        self._tracker = tracker
        self._gate = gate
        self._report = report
        # Only the capture parent touches these; the browser_fetch parent uses
        # ``communicate``. One class serves both because a single monkeypatch of
        # ``asyncio.create_subprocess_exec`` covers both call sites.
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self._pump: asyncio.Task | None = None

    async def _alive(self) -> None:
        self._tracker.enter()
        try:
            await self._gate.wait()
        finally:
            self._tracker.exit()

    # -- browser_fetch parent --------------------------------------------
    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        await self._alive()
        return self._report, b""

    # -- capture parent ---------------------------------------------------
    def start_pump(self) -> None:
        async def _run() -> None:
            await self._alive()
            self.stdout.feed_data(self._report + b"\n")
            self.stdout.feed_eof()
            self.stderr.feed_eof()

        self._pump = asyncio.create_task(_run())

    async def wait(self) -> int:
        if self._pump is not None:
            await self._pump
        return 0

    def kill(self) -> None:  # pragma: no cover - a clean exit is never killed
        raise AssertionError("must not kill a child that already exited")


def _patch_spawn(monkeypatch, tracker: _PeakTracker, gate: asyncio.Event) -> None:
    """Replace the real spawn for BOTH sites with a tracked fake."""

    async def _fake_exec(*args: Any, **kwargs: Any) -> Any:
        is_capture = any("capture._capture_main" in str(a) for a in args)
        child = _FakeChild(
            tracker, gate, _CAPTURE_REPORT if is_capture else _BROWSER_FETCH_REPORT
        )
        if is_capture:
            child.start_pump()
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)


async def _drive(coros: list[Any], tracker: _PeakTracker, gate: asyncio.Event) -> None:
    """Run *coros* concurrently, snapshot the peak while the gate is shut, release."""
    tasks = [asyncio.create_task(c) for c in coros]
    await _settle()
    assert tracker.live == MAX_CONCURRENT_BROWSERS, (
        f"{tracker.live} children alive at once; the cap is {MAX_CONCURRENT_BROWSERS}"
    )
    gate.set()
    await asyncio.gather(*tasks)
    assert tracker.entered == len(coros)
    assert tracker.peak == MAX_CONCURRENT_BROWSERS
    assert tracker.live == 0


async def test_browser_fetch_spawns_are_capped(monkeypatch) -> None:
    """The BULK lane's replay subprocess — nothing bounded it before this cap."""
    tracker, gate = _PeakTracker(), asyncio.Event()
    _patch_spawn(monkeypatch, tracker, gate)
    await _drive(
        [browser_fetch_subprocess_run({"origin_url": "https://example.com/"})
         for _ in range(_OVERSUBSCRIBE)],
        tracker,
        gate,
    )


async def test_capture_spawns_are_capped_on_the_local_path(monkeypatch) -> None:
    """The INTERACTIVE lane's discovery capture subprocess, launching LOCALLY.

    No ``cdp_url`` in the plan is exactly the condition ``_capture_main`` uses to
    choose ``chromium.launch()`` over ``connect_over_cdp()``.
    """
    tracker, gate = _PeakTracker(), asyncio.Event()
    _patch_spawn(monkeypatch, tracker, gate)
    await _drive(
        [capture_subprocess_run({"target_url": "https://example.com/"})
         for _ in range(_OVERSUBSCRIBE)],
        tracker,
        gate,
    )


async def test_capture_takes_no_permit_when_the_browser_is_REMOTE(monkeypatch) -> None:
    """A Browserbase capture costs this container a pipe, not a browser.

    ``CAPTURE_USE_BROWSERBASE`` is on in production, so this is the NORMAL path.
    Throttling it would serialise discovery for no memory saved. Twelve concurrent
    remote captures must therefore all run at once — and, crucially, must leave
    the budget completely untouched for the local paths that do need it.
    """
    tracker, gate = _PeakTracker(), asyncio.Event()
    _patch_spawn(monkeypatch, tracker, gate)

    remote_plan = {"target_url": "https://example.com/", "cdp_url": "wss://bb/session"}
    tasks = [
        asyncio.create_task(capture_subprocess_run(dict(remote_plan)))
        for _ in range(_OVERSUBSCRIBE)
    ]
    await _settle()

    # Every one of them got in; the cap did not apply.
    assert tracker.live == _OVERSUBSCRIBE
    # And not one permit was taken, so a local caller still sees all four free.
    budget = get_browser_budget()
    assert not budget.locked()
    held = [budget.acquire() for _ in range(MAX_CONCURRENT_BROWSERS)]
    await asyncio.wait_for(asyncio.gather(*held), timeout=1)
    for _ in range(MAX_CONCURRENT_BROWSERS):
        budget.release()

    gate.set()
    await asyncio.gather(*tasks)


async def test_the_two_spawn_sites_share_one_budget_so_the_bound_is_not_doubled(
    monkeypatch,
) -> None:
    """THE regression this file exists for.

    Discovery (interactive) and browser_fetch (bulk) draw on the SAME container
    memory. If each site built its own ``asyncio.Semaphore(4)`` the per-site tests
    above would both still pass while the real ceiling silently became 8. Firing
    both kinds of caller at once is the only assertion that catches that.
    """
    tracker, gate = _PeakTracker(), asyncio.Event()
    _patch_spawn(monkeypatch, tracker, gate)
    mixed: list[Any] = []
    for index in range(_OVERSUBSCRIBE):
        if index % 2:
            mixed.append(capture_subprocess_run({"target_url": "https://example.com/"}))
        else:
            mixed.append(
                browser_fetch_subprocess_run({"origin_url": "https://example.com/"})
            )
    await _drive(mixed, tracker, gate)
