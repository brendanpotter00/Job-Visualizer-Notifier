"""Process-wide cap on how many LOCAL Chromium processes may be alive at once.

WHAT THIS IS, STATED HONESTLY
-----------------------------
A guard on a path production does not currently exercise — not a fix for an
observed problem. Nothing has OOMed. Read the next two sections before deciding
this is dead code, because raising the interactive lane from 2 to 6 is exactly
what turns a latent two-browser fallback into a latent six-browser one, and the
failure mode is an OOM of the whole API container, not a slow company add.

Queue slots are not memory. ``main._INTERACTIVE_WORKER_CONCURRENCY`` is 6, which
is the right number of SLOTS — it is what lets six simultaneous adds all START
instead of sitting in ``todo`` looking frozen. It is not a promise that six
headless Chromiums fit. This module is that promise's missing half.

THE TWO PATHS IT BOUNDS (both real in code, neither running today)
------------------------------------------------------------------
1. **The ``browser_fetch`` transport** (``browser_fetch/runner.py``), which is
   ALWAYS a local Chromium: "this child ONLY ever drives a LOCAL Chromium (the
   Browserbase opt-in is discovery-time only)", and ``config.py`` says the same
   from the other side — Browserbase is "never used for the nightly replay".
   Every stored recipe in production is ``http_json`` right now, so this spawns
   nothing today. ``transport`` is chosen per-board BY DISCOVERY, so the first
   board needing an origin-issued fetch (the docstring names TikTok) activates it
   with no code change and no warning. Zero today, unbounded the moment one
   appears.

2. **The Browserbase fallback in discovery.** ``CAPTURE_USE_BROWSERBASE`` is TRUE
   in production, so discovery normally attaches to a REMOTE browser over CDP and
   costs this container almost nothing. But the flag FAILS OPEN by design —
   ``config.py``: "Turning it on cannot make discovery fail: a session-create
   error degrades back to our own browser rather than refusing a board we could
   have read for free." A 402, an expired key, a hit concurrency limit or an
   outage returns ``None`` from ``_open_browserbase_session`` and every concurrent
   discovery launches locally instead. At the old 2 slots that was two local
   Chromiums; at 6 it is six.

A THIRD, WHICH IS RUNNING TODAY: the legacy ATS scrapers
(``services/scraper_runner.py``) launch ``scripts/run_scraper.py --headless``
hourly in this same container, and every scraper in ``scripts/`` extends
``BaseScraper``, which calls ``chromium.launch()``. ``scraper_lock`` already
serialises that path to one at a time, so it can only ever hold ONE permit; what
it could not do is stop that one browser from being the fifth.

WHY A SEMAPHORE AND NOT A SMALLER LANE
--------------------------------------
Those three paths span BOTH worker lanes plus a plain background task. A
lane-size limit only ever bounds one lane, so no lane number can bound a resource
three different callers allocate. A permit taken around the actual spawn bounds
the real resource no matter which lane, which task, or which future caller
reaches it.

THE NUMBER: 4
-------------
This is an ESTIMATE, and it cannot currently be measured — production never
launches a local browser on the discovery path, so no observed memory figure
attributes to Chromium. Do not derive this constant from the container's memory
graph: the 1.9-2.16 GB peaks in that graph were reached with NO local Chromium
running, so they are report parsing and harvest buffers, not browsers.

What it is derived from instead:

* ``MEMORY_LIMIT_GB`` is 4.000, constant across all 10,081 samples of the last
  7 days; typical usage leaves roughly 2 GB of headroom.
* ``browser_fetch/runner.py`` puts one headless Chromium at "hundreds of MB".
* ~2 GB of headroom / "hundreds of MB" lands at about 4, and it is the fallback
  path being sized — the one that only happens when something else is already
  going wrong, which is a reason to be conservative rather than generous.
* ``CPU_LIMIT`` is 1 vCPU, an independent ceiling in the same neighbourhood.

IF THE CONTAINER EVER OOMs, LOWER THIS CONSTANT FIRST. It is the cheapest lever
with the smallest blast radius — ahead of the lane sizes, ahead of the
Procrastinate connector pool, and far ahead of ``db_pool_max``, which must not
move at all (``docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md``).

A TRAP, NAMED SO THE NEXT PERSON AVOIDS IT
------------------------------------------
``capture/_capture_main.py`` opens with "Our OWN Chromium by default". That is
true of the DEFAULT and FALSE of production, where ``CAPTURE_USE_BROWSERBASE`` is
on. Sizing anything here from that docstring without checking the DEPLOYED env
gives the wrong answer — it happened once already while this module was being
written. Check the Railway variable, not the code default.

Note the consequence for scoping: ``network_capture`` takes a permit ONLY when it
is about to launch locally (no ``cdp_url`` in the plan), because throttling a
remote browser would buy nothing and would serialise the path that is normal in
production.

WHY KEEP IT IF IT DOES NOT RUN
------------------------------
About twenty lines. Deleting them means the 2 -> 6 concurrency increase silently
widens a latent OOM on two paths that are one discovery result, or one Browserbase
outage, away from being live.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

__all__ = ["MAX_CONCURRENT_BROWSERS", "browser_permit", "get_browser_budget"]


# See "THE NUMBER" above. Lower this first if the container OOMs.
MAX_CONCURRENT_BROWSERS = 4


# Keyed by event loop, NOT a single module-level ``asyncio.Semaphore``. Both
# worker lanes, the auto-scraper and every request handler share ONE loop inside
# uvicorn, so in production this dict holds exactly one entry and the bound is
# genuinely process-wide.
#
# The keying is not defensive padding — it was MEASURED. ``asyncio.Semaphore``
# binds itself to the first loop that makes a waiter block on it and thereafter
# raises ``RuntimeError: ... is bound to a different event loop``. Building this
# at import time and contending on it from two of pytest-asyncio's per-test loops
# reproduces that error immediately. Production has one loop and would never have
# shown it; the suite would have, as a confusing unrelated failure.
#
# WeakKeyDictionary so a finished loop's semaphore is not a leak.
_BUDGETS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


def get_browser_budget() -> asyncio.Semaphore:
    """The shared permit pool for the RUNNING event loop.

    Constructed lazily on first use rather than at import time so the semaphore
    is only ever created from inside a running loop.
    """
    loop = asyncio.get_running_loop()
    budget = _BUDGETS.get(loop)
    if budget is None:
        budget = asyncio.Semaphore(MAX_CONCURRENT_BROWSERS)
        _BUDGETS[loop] = budget
    return budget


@asynccontextmanager
async def browser_permit() -> AsyncIterator[None]:
    """Hold one browser permit for the body of the ``async with``.

    Wrap the NARROWEST region that actually holds a Chromium process: acquire
    immediately before the launch/spawn and release once the child has been
    reaped. A task waiting on the network with no browser open must never hold a
    permit — that is the difference between bounding memory and re-inventing a
    smaller lane.

    ``asyncio.Semaphore`` (not ``threading.Semaphore``) because every spawn site
    is an ``async def`` that ``await``s ``asyncio.create_subprocess_exec`` on the
    event loop; none of them launches a browser synchronously in a worker thread.
    If a future site ever does, it needs a different primitive and this docstring
    is wrong.
    """
    budget = get_browser_budget()
    await budget.acquire()
    try:
        yield
    finally:
        budget.release()
