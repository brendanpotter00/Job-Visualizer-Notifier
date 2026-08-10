"""DISCOVERY ORCHESTRATOR — one bounded Stagehand session → acceptance (E7 pivot).

Replaces the deleted ``services/discovery/`` observe→author→replay loop. There is no
second blind LLM authoring call any more: Stagehand's own model reasons over the REAL
rendered page inside ONE bounded session, and **that first bounded harvest IS the
acceptance replay + gate** (``oracle_kind='self_consistent'``).

The "bounded and loud" invariant is preserved: ≤ 2 attempts, then REFUSE. The runner
SELECTS the ``id_field`` from the extracted rows — ``url`` (real hrefs), else ``title``
(distinct titles, for href-less boards like YC company pages), else ``title|location``,
else RAISE — and discovery STORES the chosen field in the artifact. Attempt 1 uses a
plain extract instruction; if the runner RAISES (no stable id, subprocess failure, …),
attempt 2 retries with a SHARPER instruction (real hrefs + full distinct titles). Two
failures → ``DiscoveryOutcome(ok=False, refuse_reason=…)``; the task turns that into
``health_state='refused'`` + a ``company_add_attempts`` row and stores no script.

A browser-agent board is ALWAYS ``self_consistent`` (a rendered page proves no trusted
total), so an accepted board is SHOWN but only ever CLOSES a job after the 3-run
VERIFIED streak the leaf task enforces — the gate already guarantees this.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from ..harvest_meta import HarvestEvidence
from ..harvest_verification import HarvestGateError, run_gate
from ..recipe_rows import recipe_rows_to_job_listings
from ..recipe_runner import RecipeExecutionError
from ..discovery.models import DiscoveryOutcome
from . import runner as runner_mod
from .schema import BrowserAgentScriptError, validate_browser_agent_script

logger = logging.getLogger(__name__)

# Hard cap on discovery attempts (invariant 6). Attempt 2 gets the sharper instruction.
_MAX_ATTEMPTS = 2
# Placeholder company id for the acceptance replay only — the real id is minted later.
_PROBE_COMPANY_ID = "discovery-probe"

# The stored artifact keeps a permissive floor (a board must have ≥ 1 job to track);
# the delta-band + 3-run streak in the gate catch a later broken/partial extract.
_STORED_EXPECTED_MIN_JOBS = 1

# The generic job schema the extract is asked to fill (§3.1). ``url`` is the stable
# ``id_field`` — the runner proves its values are real hrefs, not row indices.
_JOB_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "location": {"type": "string"},
                    "url": {"type": "string"},
                },
                # Only ``title`` is required: many boards (e.g. YC) have click-to-open
                # rows with NO per-job href — requiring ``url`` makes the extract DROP
                # every such job → zero rows. url is optional; the runner selects a
                # title-based id_field when real hrefs aren't present.
                "required": ["title"],
            },
        }
    },
    "required": ["jobs"],
}

_BASE_EXTRACT_INSTRUCTION = (
    "Extract EVERY job posting listed on this page. For each job return its full title, "
    "its location, and its link/URL. Include every job — do not skip any."
)
_SHARPER_EXTRACT_INSTRUCTION = (
    "Extract EVERY job posting on this page — include ALL of them, do not skip any. For "
    "each job return: (1) its FULL job title exactly as shown (titles are distinct per "
    "job); (2) its location; (3) the href of the job's own detail/apply link when the row "
    "has one (a URL path such as '/companies/acme/jobs/security-engineer'). If a row has "
    "no link, still include the job and leave url empty."
)

# Placeholder id_field while assembling the artifact; the runner SELECTS the real one
# from the extracted rows and discovery overwrites this before storing (§3.4).
_PLACEHOLDER_ID_FIELD = "url"

RunAgentFn = Callable[..., Awaitable[tuple[list[dict[str, Any]], HarvestEvidence, str]]]


def _build_artifact(url: str, instruction: str) -> dict[str, Any]:
    """Assemble a bounded browser-agent artifact (§3.1) for ``url``."""
    return {
        "script_version": 2,
        "transport": "browser_agent",
        "entry_url": url,
        "extract": {"instruction": instruction, "schema": _JOB_SCHEMA},
        # A pagination block is always present but bounded at 3 pages: a single-page
        # board simply stops after page 1 (the next-page act fails → clean terminus),
        # so this is safe for both single-page and paginated boards.
        "pagination": {
            "next_action": "click the next-page pagination control",
            "max_pages": 3,
        },
        "id_field": _PLACEHOLDER_ID_FIELD,   # overwritten with the runner's selection
        "expected_min_jobs": _STORED_EXPECTED_MIN_JOBS,
        "oracle": {"kind": "self_consistent"},
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "discovered_by": "stagehand/claude-sonnet-4-5",
    }


async def discover(
    url: str,
    *,
    run_agent: RunAgentFn | None = None,
) -> DiscoveryOutcome:
    """Run one discovery. Never raises — the loud failure is a REFUSE outcome.

    ``run_agent`` (the bounded, id-field-SELECTING Stagehand runner) is injectable so
    the unit tests run at $0 against a fake report; production defaults to the real
    subprocess-driving :func:`runner.run_browser_agent_selecting`, which returns
    ``(rows, evidence, chosen_id_field)``.
    """
    run = run_agent or runner_mod.run_browser_agent_selecting

    previous_error: str | None = None
    attempts = 0
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        attempts = attempt
        instruction = (
            _BASE_EXTRACT_INSTRUCTION if attempt == 1 else _SHARPER_EXTRACT_INSTRUCTION
        )
        script = _build_artifact(url, instruction)
        try:
            # Belt: our own artifact must validate (the bound is re-checked on read
            # by the runner too, but validating here fails loudly on a builder bug).
            validate_browser_agent_script(script)
            rows, evidence, id_field = await run(script)
            jobs = recipe_rows_to_job_listings(_PROBE_COMPANY_ID, rows)
            gate = run_gate(jobs, evidence, oracle_kind="self_consistent")
            if gate.is_zero or not gate.jobs:
                raise HarvestGateError(
                    "browser-agent discovery produced no usable rows for this board"
                )
            # STORE the runner's id_field selection, then re-validate the final artifact
            # (id_field must be in the closed set — a builder/runner bug fails loudly).
            script["id_field"] = id_field
            validate_browser_agent_script(
                script, transport="browser_agent", oracle_kind="self_consistent"
            )
        except (
            BrowserAgentScriptError,
            RecipeExecutionError,
            HarvestGateError,
            ValueError,
        ) as exc:
            previous_error = f"{type(exc).__name__}: {exc}"
            logger.info(
                "browser-agent discovery attempt %d rejected for %s: %s",
                attempt, url, previous_error,
            )
            continue

        logger.info(
            "browser-agent discovery accepted %s on attempt %d (transport=browser_agent "
            "oracle=self_consistent id_field=%s)",
            url, attempt, id_field,
        )
        return DiscoveryOutcome(
            ok=True,
            script=script,
            transport="browser_agent",
            oracle_kind="self_consistent",
            attempts=attempt,
            cost_note=f"{attempt} bounded Stagehand session(s)",
        )

    logger.warning(
        "browser-agent discovery REFUSED %s after %d attempts: %s",
        url, attempts, previous_error,
    )
    return DiscoveryOutcome(
        ok=False,
        refuse_reason=previous_error or "browser-agent discovery could not read this site",
        attempts=attempts,
    )
