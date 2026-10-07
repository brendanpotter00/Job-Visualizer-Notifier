"""Leaders: FindAll (preview) for one domain, the ``is_person`` filter, the
brief's ``founders`` fallback, and the pedigree Task Group (one ``base`` run per
leader). No FindAll enrich.

All candidate names, URLs and outputs are web data; they are passed to
Parallel as input fields and stored on the card, never interpreted.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .ats import safe_http_url
from .card import text
from .schemas import PEDIGREE_SCHEMA

MATCH_LIMIT = 8
MAX_LEADERS = 8
POLL_INTERVAL_S = 10.0
PEDIGREE_PROCESSOR = "base"

COMPANY_PAGE = re.compile(r"tracxn\.com/.*/company/|crunchbase\.com/organization/|linkedin\.com/company/", re.I)


class DeadlineReached(Exception):
    """The run's ``--deadline-s`` passed while waiting; state is saved and the next run resumes."""


class RetryLater(Exception):
    """A transient failure (HTTP 429/5xx, a dropped connection) while collecting work that
    may already be paid for. The company keeps its state and a later invocation resumes it,
    instead of posting a card with holes in it (the domain could never be researched again)."""


_ABORT = threading.Event()


def abort_all_deadlines() -> None:
    """Expire every Deadline now (the SIGTERM handler): workers stop at their next check
    and save state, so a killed run resumes instead of losing paid-for work."""
    _ABORT.set()


class Deadline:
    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._end = clock() + seconds

    def remaining(self) -> float:
        if _ABORT.is_set():
            return 0.0
        return self._end - self._clock()

    def expired(self) -> bool:
        return self.remaining() <= 0

    def check(self, what: str) -> None:
        if self.expired():
            raise DeadlineReached(what)


def is_person(cd: Any) -> bool:
    if COMPANY_PAGE.search(getattr(cd, "url", None) or ""):
        return False
    return len((getattr(cd, "name", None) or "").split()) >= 2


def findall_request(name: str, domain: str) -> dict[str, Any]:
    """Objective and match condition as the POC's leadership FindAll, plus the one-person sentence."""
    return {
        "objective": (f"Find the founders and current senior leadership team (CEO, CTO, other C-level "
                      f"executives, VPs and Heads of functions) of {name}, the company whose website is {domain}."),
        "entity_type": "people",
        "match_conditions": [{
            "name": "current_leader_at_company",
            "description": (
                f"The person is a founder/co-founder of {name} ({domain}) or currently holds a C-level "
                f"(CEO, CTO, COO, CPO, CFO, etc.), VP-level or Head-of role at {name} ({domain}). It must be "
                f"this exact company (the one at {domain}), not a different company with a similar name. "
                f"Evidence: the company's own website/team page, LinkedIn, press releases or news. Former "
                f"employees, investors, board-only members and advisors do NOT match. If there is no "
                f"evidence, the condition is not satisfied. The candidate must be one person with a personal "
                f"profile, not a company page."),
        }],
        "generator": "preview",
        "match_limit": MATCH_LIMIT,
        "metadata": {"app": "launch-radar", "company": domain},
    }


def poll_findall(client: Any, findall_id: str, deadline: Deadline, sleep: Callable[[float], None]) -> Any:
    """``retrieve`` every 10s until ``is_active`` is false. Returns the run."""
    while True:
        run = client.beta.findall.retrieve(findall_id)
        if not run.status.is_active:
            return run
        deadline.check(f"findall {findall_id}")
        sleep(min(POLL_INTERVAL_S, max(0.0, deadline.remaining())))


def select_leaders(result: Any) -> tuple[list[Any], int]:
    """Matched candidates that pass ``is_person`` (at most 8), and how many matches it rejected.

    ``match_limit`` is 8 on preview, so in practice the rejected count equals
    matched minus kept (CONTRACT §6.3); the cap only guards an oversized result.
    """
    matched = [cd for cd in (result.candidates or []) if getattr(cd, "match_status", None) == "matched"]
    people = [cd for cd in matched if is_person(cd)]
    return people[:MAX_LEADERS], len(matched) - len(people)


# ---- the brief's founders: the fallback when FindAll confirms no person ---------------------
LINKEDIN_URL = re.compile(r"^https?://([a-z0-9-]+\.)*linkedin\.com/", re.I)
BRIEF_LEADERS_ISSUE = "leaders from the brief (FindAll found none)"


def name_key(name: str) -> str:
    """Case, punctuation and spacing folded: ``"Sam  Rivera"``, ``"sam rivera."`` are one person."""
    return " ".join(re.sub(r"[^\w\s]", " ", name.casefold()).split())


def brief_founders(brief: Any) -> list[dict[str, str | None]]:
    """The brief's ``founders``, cleaned: entries without a name dropped, deduped by
    ``name_key`` (first wins), at most ``MAX_LEADERS``, and ``linkedin_url`` kept only
    when it is an http(s) LinkedIn URL (anything else becomes None)."""
    raw = brief.get("founders") if isinstance(brief, dict) else None
    out: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for f in raw if isinstance(raw, list) else []:
        if not isinstance(f, dict):
            continue
        name = text(f.get("name"), 200)
        key = name_key(name) if name else ""
        if not name or not key or key in seen:
            continue
        seen.add(key)
        url = safe_http_url(f.get("linkedin_url"))
        out.append({"name": name, "title": text(f.get("title"), 200),
                    "linkedin_url": url if url and LINKEDIN_URL.match(url) else None})
        if len(out) == MAX_LEADERS:
            break
    return out


@dataclass(frozen=True)
class BriefLeader:
    """A leader from the brief's ``founders``. It carries the FindAll candidate attributes
    the pipeline reads (``name``, ``url``, ``description``, ``candidate_id``, ``basis``), so
    the pedigree Task Group and ``card.build_leader`` treat it like a FindAll person."""

    name: str
    fallback_title: str | None  # the brief's title; card.build_leader uses it when pedigree has none
    linkedin_url: str | None

    @property
    def url(self) -> str | None:
        return self.linkedin_url

    @property
    def description(self) -> str | None:
        return self.fallback_title

    @property
    def candidate_id(self) -> str:
        return f"brief:{name_key(self.name)}"

    @property
    def basis(self) -> list[Any]:
        return []


def brief_leaders(founders: list[dict[str, str | None]]) -> list[BriefLeader]:
    """``BriefLeader`` objects from ``brief_founders`` output (or its saved copy on resume)."""
    return [BriefLeader(name=str(f["name"]), fallback_title=f.get("title"), linkedin_url=f.get("linkedin_url"))
            for f in founders if f.get("name")]


def pedigree_inputs(leaders: list[Any], company: str, domain: str) -> list[dict[str, Any]]:
    """One run per leader; ``row_id`` is the leader's index. A ``None`` placeholder (a leader
    missing on resume) keeps its index but gets no run."""
    out = []
    for i, cd in enumerate(leaders):
        if cd is None:
            continue
        url = getattr(cd, "url", None) or ""
        out.append({
            "input": {
                "person_name": cd.name,
                "current_title": _description_title(cd),
                "linkedin_url": url if "linkedin.com/in/" in url.lower() else None,
                "company_name": company,
                "company_domain": domain,
            },
            "processor": PEDIGREE_PROCESSOR,
            "metadata": {"row_id": str(i)},
        })
    return out


def _description_title(cd: Any) -> str | None:
    desc = getattr(cd, "description", None)
    return desc[:200] if isinstance(desc, str) and desc.strip() else None


def pedigree_spec() -> dict[str, Any]:
    return {"output_schema": {"type": "json", "json_schema": PEDIGREE_SCHEMA}}


def create_pedigree_group(client: Any, domain: str) -> str:
    return str(client.task_group.create(metadata={"app": "launch-radar", "company": domain}).task_group_id)


def add_pedigree_runs(client: Any, group_id: str, inputs: list[dict[str, Any]]) -> None:
    """Add the runs (this is the call that bills). Not idempotent: Parallel adds the runs
    again on a second call, so the caller tracks attempts (``CompanyJob.add_pedigree_runs``)."""
    client.task_group.add_runs(group_id, inputs=inputs, default_task_spec=pedigree_spec())


def pedigree_run_count(client: Any, group_id: str) -> int:
    """How many runs the group holds: ``status.num_task_runs``, else the sum of
    ``task_run_status_counts``. Free (a ``retrieve``)."""
    status = client.task_group.retrieve(group_id).status
    n = getattr(status, "num_task_runs", None)
    if isinstance(n, int) and not isinstance(n, bool):
        return n
    counts = getattr(status, "task_run_status_counts", None) or {}
    return sum(int(v) for v in counts.values())


def poll_group(client: Any, group_id: str, deadline: Deadline, sleep: Callable[[float], None]) -> Any:
    while True:
        status = client.task_group.retrieve(group_id).status
        if not status.is_active:
            return status
        deadline.check(f"task group {group_id}")
        sleep(min(POLL_INTERVAL_S, max(0.0, deadline.remaining())))


def _content(output: Any) -> dict[str, Any] | None:
    """The JSON object of a run output, or None when it is not valid JSON / not an object."""
    content = getattr(output, "content", None)
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return None
    return content if isinstance(content, dict) else None


def basis_confidence(basis: Any) -> dict[str, str | None]:
    """Confidence per top-level field: ``basis[].field.split('.')[0]``."""
    conf: dict[str, str | None] = {}
    for b in basis or []:
        field = getattr(b, "field", None)
        if isinstance(field, str):
            conf.setdefault(field.split(".")[0], getattr(b, "confidence", None))
    return conf


def collect_pedigree(
    client: Any, group_id: str, n: int, expected: set[int] | None = None
) -> tuple[dict[int, dict[str, Any]], list[str]]:
    """Completed pedigree outputs keyed by row index (joined on ``metadata.row_id``).

    Every index in ``expected`` (default: all ``n``) that yields no usable row gets an
    issue, so a leader with no pedigree is never silently scored as "no people data".
    """
    rows: dict[int, dict[str, Any]] = {}
    issues: list[str] = []
    reported: set[int] = set()
    for ev in client.task_group.get_runs(group_id, include_input=True, include_output=True):
        etype = getattr(ev, "type", None)
        if etype == "error":
            err = getattr(ev, "error", None)
            issues.append(f"pedigree stream error: {str(getattr(err, 'message', err))[:200]}")
            continue
        if etype != "task_run.state":
            continue
        run = ev.run
        row_id = (getattr(run, "metadata", None) or {}).get("row_id")
        try:
            i = int(str(row_id))
        except ValueError:
            issues.append(f"pedigree run {getattr(run, 'run_id', '?')} has no usable row_id")
            continue
        if not 0 <= i < n:
            issues.append(f"pedigree run {getattr(run, 'run_id', '?')} has row_id {i} out of range")
            continue
        output = getattr(ev, "output", None)
        if getattr(run, "status", None) != "completed" or output is None:
            issues.append(f"pedigree run for leader {i + 1} ended {getattr(run, 'status', 'unknown')}")
            reported.add(i)
            continue
        content = _content(output)
        if content is None:
            issues.append(f"pedigree run for leader {i + 1} returned no JSON")
            reported.add(i)
            continue
        basis = getattr(output, "basis", None) or []
        rows[i] = {"content": content, "confidence": basis_confidence(basis), "basis": basis}
    for i in sorted(set(range(n)) if expected is None else expected):
        if i not in rows and i not in reported:
            issues.append(f"pedigree for leader {i + 1} missing from results")
    return rows, issues
