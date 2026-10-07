"""Company brief (Task on ``core``) and team tally (Task on ``pro``).

Both are created at the same moment as FindAll and collected later with
``wait_task``. Their outputs are web research and are treated as data.
"""

from __future__ import annotations

import json
from typing import Any

from .leaders import Deadline, DeadlineReached, RetryLater
from .parallel_client import status_code_of
from .schemas import BRIEF_SCHEMA, TEAM_SCHEMA

BRIEF_PROCESSOR = "core"
TEAM_PROCESSOR = "pro"
RESULT_WINDOW_S = 60  # server-side long-poll window per call


TERMINAL_STATUSES = frozenset({"failed", "cancelled", "action_required"})


class TaskFailed(RuntimeError):
    """The run itself ended without a result (Parallel reports it failed, cancelled or
    action_required, or does not know the run id). Never raised for a transient error."""


def brief_request(name: str, domain: str, context: str | None) -> dict[str, Any]:
    return {
        "input": {
            "company_name": name,
            "company_domain": domain,
            "context": context or "Startup; may have recently announced a funding round or product launch.",
        },
        "processor": BRIEF_PROCESSOR,
        "task_spec": {"output_schema": {"type": "json", "json_schema": BRIEF_SCHEMA}},
        "metadata": {"app": "launch-radar", "company": domain, "step": "brief"},
    }


def team_request(name: str, domain: str) -> dict[str, Any]:
    # The founders' names are not known yet (FindAll runs at the same time), so
    # the exclusion is by role, not by name.
    return {
        "input": (f"Company: {name} ({domain}). Find current employees of this exact company who are NOT "
                  f"its founders, co-founders or C-level executives. Use public profiles (LinkedIn, team "
                  f"pages, personal sites). For the people you find, tally the universities they attended "
                  f"and their notable previous employers. Count each person once per school and per employer. "
                  f"Do not guess: only count facts you found."),
        "processor": TEAM_PROCESSOR,
        "task_spec": {"output_schema": {"type": "json", "json_schema": TEAM_SCHEMA}},
        "metadata": {"app": "launch-radar", "company": domain, "step": "team"},
    }


def create_task(client: Any, request: dict[str, Any]) -> str:
    return str(client.task_run.create(**request).run_id)


def wait_task(client: Any, run_id: str, deadline: Deadline) -> Any:
    """Long-poll ``/result``; 408 means still running.

    Raises ``DeadlineReached``, ``TaskFailed`` (the run itself failed) or ``RetryLater``
    (a transient error: 429, 5xx, an auth/billing error on the poll, a dropped connection).
    A transient error must not turn a paid-for run into a hole on a permanent card, so
    the caller keeps the company's state and a later invocation polls again.
    """
    while True:
        window = int(min(RESULT_WINDOW_S, deadline.remaining()))
        if window < 1:
            raise DeadlineReached(f"task {run_id}")
        try:
            return client.task_run.result(run_id, api_timeout=window, timeout=window + 30)
        except Exception as exc:  # narrowed below by HTTP status; anything else propagates
            code = status_code_of(exc)
            if code == 408:
                continue
            if code == 404:
                # /result answers 404 for a failed run AND for an unknown id; ask the run.
                raise _classify_404(client, run_id) from exc
            if code is not None:
                raise RetryLater(f"task {run_id}: HTTP {code}") from exc
            if _is_transport_error(exc):
                raise RetryLater(f"task {run_id}: {type(exc).__name__}") from exc
            raise


def _classify_404(client: Any, run_id: str) -> Exception:
    try:
        run = client.task_run.retrieve(run_id)
    except Exception as exc:
        code = status_code_of(exc)
        if code == 404:
            return TaskFailed(f"task {run_id}: unknown run (HTTP 404)")
        if code is not None or _is_transport_error(exc):
            return RetryLater(f"task {run_id}: result 404, status check failed ({code or type(exc).__name__})")
        raise
    status = getattr(run, "status", None)
    if status in TERMINAL_STATUSES:
        err = getattr(run, "error", None)
        msg = getattr(err, "message", None) if err is not None else None
        return TaskFailed(f"task {run_id}: {status}" + (f" ({str(msg)[:200]})" if msg else ""))
    return RetryLater(f"task {run_id}: result 404 while the run is {status}")


def _is_transport_error(exc: BaseException) -> bool:
    """Connection drops and client-side timeouts (SDK ``APIConnectionError`` /
    ``APITimeoutError``, httpx transport errors, builtin ``TimeoutError``/``ConnectionError``)."""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    names = {cls.__name__ for cls in type(exc).__mro__}
    return bool(names & {"APIConnectionError", "APITimeoutError", "TransportError", "TimeoutException"})


def task_output(result: Any) -> tuple[dict[str, Any] | None, list[Any]]:
    """The JSON content (or None) and the basis list of a Task result."""
    output = getattr(result, "output", None)
    content = getattr(output, "content", None)
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            content = None
    return (content if isinstance(content, dict) else None), list(getattr(output, "basis", None) or [])
