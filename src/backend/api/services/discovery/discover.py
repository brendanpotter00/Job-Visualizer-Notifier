"""DISCOVERY ORCHESTRATOR — observe → author → validate → replay → gate (E7 3b).

Closes the acceptance loop for a one-time discovery run and enforces the
non-negotiable "bounded and loud" invariant: ≤ 2 authoring attempts, then REFUSE.

A candidate script is accepted ONLY if it survives the SAME deterministic,
agent-free path the nightly harvest uses:

    1. observer.observe(url)                     — local browser, OUT OF PROCESS
    2. author.author_script(report)              — one Sonnet call (attempt N)
    3. recipe_schema.validate_recipe(script)     — closed-vocabulary shape check
    4. recipe_runner.run_recipe(script, http)    — AGENT-FREE replay → rows+evidence
    5. run_gate(jobs, evidence, oracle_kind)     — Phase-2 structural gate

If steps 3–5 fail, the error is fed back to the model for one retry. After 2
attempts (or an author/observe failure, or a keyless env) it returns
``DiscoveryOutcome(ok=False, refuse_reason=…)``; the task turns that into
``health_state='refused'`` + a ``company_add_attempts`` row and creates nothing.

``run_recipe`` and ``run_gate`` are the exact agent-free modules the replay leaf
task uses. Discovery can call them safely because the runner's runtime guard
forbids only browser drivers, and the observer keeps Playwright out of process —
so ``anthropic`` (resident via ``author``) never contaminates the replay proof.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

import httpx

from .. import recipe_runner, recipe_schema
from ..guarded_client import guarded_sync_client
from ..harvest_verification import HarvestGateError, run_gate
from ..recipe_rows import recipe_rows_to_job_listings
from . import author as author_mod
from . import observer as observer_mod
from .models import DiscoveryOutcome

logger = logging.getLogger(__name__)

# Hard cap on authoring attempts (invariant 6). Attempt 2 gets the failure reason.
_MAX_ATTEMPTS = 2
# Placeholder company id for the acceptance replay only — the discovered company's
# real id is minted later by the task's create path.
_PROBE_COMPANY_ID = "discovery-probe"

ObserveFn = Callable[[str], Awaitable[dict[str, Any]]]
AuthorFn = Callable[..., Awaitable[dict[str, Any]]]
HttpFactory = Callable[[], httpx.Client]


def _default_http_client() -> httpx.Client:
    # The SAME SSRF-guarded client the nightly leaf task uses, so the add-time
    # acceptance replay validates/host-pins/IP-pins the authored URLs exactly as the
    # nightly replay will — an authored URL that would be blocked nightly is blocked
    # at discovery time too, and REFUSED rather than stored.
    return guarded_sync_client()


def _replay_and_gate(script: dict[str, Any], http_factory: HttpFactory) -> None:
    """Validate → replay → gate the candidate. Raises on any failure.

    Runs synchronously (``run_recipe`` is sync ``httpx``); callers wrap it in a
    thread. Raises ``RecipeError`` / ``RecipeExecutionError`` / ``HarvestGateError``
    / ``ValueError`` — the discover loop treats any of these as "this script does
    not work, retry or refuse".
    """
    recipe_schema.validate_recipe(script)  # closed-vocabulary shape check
    oracle_kind = script["oracle"]["kind"]
    http = http_factory()
    try:
        rows, evidence = recipe_runner.run_recipe(script, http)
    finally:
        http.close()
    jobs = recipe_rows_to_job_listings(_PROBE_COMPANY_ID, rows)
    gate = run_gate(jobs, evidence, oracle_kind=oracle_kind)
    if gate.is_zero or not gate.jobs:
        # run_recipe already raises on zero rows, so this is a belt-and-braces
        # refusal: a discovered board that proves empty on day one is not trackable.
        raise HarvestGateError("replay produced no usable rows for a discovered board")


async def discover(
    url: str,
    *,
    observe_fn: ObserveFn | None = None,
    author_fn: AuthorFn | None = None,
    http_client_factory: HttpFactory | None = None,
) -> DiscoveryOutcome:
    """Run one discovery. Never raises — the loud failure is a REFUSE outcome.

    The browser (``observe_fn``), the LLM (``author_fn``), and the replay HTTP
    client (``http_client_factory``) are all injectable so the unit tests run at
    $0 against a fixture observation + a mocked author + a MockTransport client.
    """
    observe = observe_fn or observer_mod.observe
    author = author_fn or author_mod.author_script
    http_factory = http_client_factory or _default_http_client

    try:
        report = await observe(url)
    except observer_mod.ObserveError as exc:
        logger.warning("discovery observe failed for %s: %s", url, exc)
        return DiscoveryOutcome(ok=False, refuse_reason=f"observe_failed: {exc}", attempts=0)

    previous_error: str | None = None
    attempts = 0
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            script = await author(report, previous_error=previous_error)
        except author_mod.MissingAnthropicKeyError as exc:
            # Keyless env: REFUSE without burning an attempt (§6 test d).
            return DiscoveryOutcome(
                ok=False, refuse_reason=f"missing_api_key: {exc}", attempts=attempts
            )
        except author_mod.DiscoveryAuthorError as exc:
            attempts = attempt
            previous_error = f"author_error: {exc}"
            logger.info("discovery attempt %d authoring failed: %s", attempt, exc)
            continue

        attempts = attempt
        try:
            await asyncio.to_thread(_replay_and_gate, script, http_factory)
        except (
            recipe_schema.RecipeError,
            recipe_runner.RecipeExecutionError,
            HarvestGateError,
            httpx.HTTPError,   # a guarded-client transport/connect failure → refuse, not crash
            ValueError,
        ) as exc:
            previous_error = f"{type(exc).__name__}: {exc}"
            logger.info("discovery attempt %d rejected: %s", attempt, previous_error)
            continue

        oracle_kind = script["oracle"]["kind"]
        logger.info(
            "discovery accepted %s on attempt %d (transport=%s oracle=%s)",
            url, attempt, script["transport"], oracle_kind,
        )
        return DiscoveryOutcome(
            ok=True,
            script=script,
            transport=script["transport"],
            oracle_kind=oracle_kind,
            attempts=attempt,
            cost_note=f"{attempt} Sonnet authoring call(s)",
        )

    # ≤2 attempts exhausted → REFUSE loudly.
    logger.warning("discovery REFUSED %s after %d attempts: %s", url, attempts, previous_error)
    return DiscoveryOutcome(
        ok=False,
        refuse_reason=previous_error or "no valid recipe after 2 attempts",
        attempts=attempts,
    )
