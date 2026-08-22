"""DISCOVERY PROGRESS — the 4-step checklist the user actually reads (E7 capture pivot).

Discovery used to be an opaque spinner ("Setting up…") because the retired DOM agent's
work genuinely was unpredictable: nobody could say what it would do next. The capture
engine's steps are DETERMINISTIC and known before the run starts, so there is no longer
any excuse for a spinner. This module is the vocabulary for saying, out loud, where a
run got to and what it found:

1. :data:`STEP_OPEN_PAGE`   — opening the careers page
2. :data:`STEP_FIND_FEED`   — finding the jobs feed
3. :data:`STEP_VERIFY_READ` — verifying we can read it
4. :data:`STEP_READY`       — ready to track

Four, not the engine's six. The engine's internal steps are named for the code that can
fail (``writing the replay recipe`` is a distinct failure with a distinct log line); the
user's four are named for the things a person can act on. :mod:`api.services.capture.
discover` owns the mapping between them, because it owns both.

**Every completed step carries a SPECIFIC result** ("found 3 candidate feeds", "read 90
jobs"), never a bare tick. That is the whole point: a generic checkmark is a spinner
with extra steps, and the specific number is what tells a user whether the thing we are
about to track is their board.

WHERE IT IS STORED — ``companies.provider_config -> 'discovery'``, and NO MIGRATION.
That column is ``JSONB NOT NULL DEFAULT '{}'``, is written as a literal ``'{}'`` for
every discovered row, and is read only by the ATS-provider branches of the leaf task and
the QA endpoints — none of which ever sees an ``ats='discovered'`` row. The alternatives
were all worse: ``company_scripts.script`` does not exist while a company is
``discovering`` (the placeholder deliberately writes no script row — that script-lessness
is what keeps the nightly leaf task a no-op), ``company_add_attempts`` is append-only
audit no endpoint reads back, and a new column costs a migration for a display-only blob.

PURE AND DEPENDENCY-FREE, like :mod:`.models` beside it: it builds a JSON blob and reads
one back. It must never import a driver, a client or a connection — three callers
(the discovery engine, the data-access service, and the router's response mapper) share
it, and one of them is inside the import-guarded replay worker's closure.

**Nothing here is load-bearing for harvesting.** A missing, stale or malformed blob
degrades to today's badge-only row; it can never make us scrape, close or refuse
anything. That is why :func:`read_progress` is TOTAL — a blob written by an older
deployment, or hand-edited in the database, returns ``None`` or a normalized subset
rather than 500-ing the one endpoint the My-Companies list depends on.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

# The four user-facing steps, in display order. These keys are an API contract: the
# frontend maps them through a closed `Record<DiscoveryStepKey, …>` so a rename here is
# a compile error there rather than a blank row.
STEP_OPEN_PAGE = "open_page"
STEP_FIND_FEED = "find_feed"
STEP_VERIFY_READ = "verify_read"
STEP_READY = "ready"

DISCOVERY_STEPS: tuple[str, ...] = (
    STEP_OPEN_PAGE,
    STEP_FIND_FEED,
    STEP_VERIFY_READ,
    STEP_READY,
)

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

_STATUSES = frozenset({STATUS_PENDING, STATUS_ACTIVE, STATUS_DONE, STATUS_FAILED})

# Terminal-ness of the whole run, so the UI knows whether to render "still working",
# "here is what we found" or "we could not read this board" without re-deriving it from
# four step statuses (and disagreeing with the backend about the edge cases).
OUTCOME_RUNNING = "running"
OUTCOME_TRACKING = "tracking"
OUTCOME_REFUSED = "refused"
# TRACKED, BUT NOT THE WHOLE BOARD. A recipe that reads a sliver — one department of a
# grouped payload, the tab the page happened to open, ten jobs of forty-seven thousand
# — passes every gate we have and is a perfectly valid thing to keep reading. What it
# is not is the same outcome as a board we read completely, and it used to render
# identically: the same green "Successfully tracking" chip, the same "read N jobs" tick.
# ``capture.discover`` decides this by measuring the stored recipe against the counts
# the board published in the response we captured; see its ``_coverage``.
OUTCOME_PARTIAL = "partial"

_OUTCOMES = frozenset({
    OUTCOME_RUNNING, OUTCOME_TRACKING, OUTCOME_PARTIAL, OUTCOME_REFUSED,
})

# A preview, not a job list — enough to recognise "yes, that is my board" at a glance.
# The real list is one click away on the company's trend page once the first harvest
# lands, and a bigger blob here would bloat every row of the polled list response.
MAX_PREVIEW_JOBS = 5

# The preview fields we are willing to echo back. Anything else the board returned
# (ids, salary bands, raw HTML descriptions) is dropped — this blob is rendered, and
# echoing arbitrary captured fields into the DOM is how a scraped payload becomes a
# rendering surface.
_PREVIEW_FIELDS = ("title", "location", "url")

# Result/detail strings come from board data and exception messages; cap them so one
# pathological error cannot make every list response enormous.
_MAX_TEXT_CHARS = 400

# A preview URL is rendered as a LINK. Only http(s) may survive — a ``javascript:`` or
# ``data:`` href harvested from a stranger's board is a stored-XSS vector, and the check
# runs on WRITE and again on READ because a blob already in the database predates
# whatever we tighten later.
_SAFE_URL_PREFIXES = ("https://", "http://")


def _clip(text: object) -> str:
    """One display string, bounded. Never ``None`` — the caller already decided."""
    value = str(text)
    return value if len(value) <= _MAX_TEXT_CHARS else value[: _MAX_TEXT_CHARS - 1] + "…"


def _one_of(value: object, allowed: frozenset[str], fallback: str) -> str:
    """``value`` when it is one of ``allowed``, else ``fallback``.

    The ``isinstance`` guard is not decoration. ``x in frozenset`` HASHES ``x``, so a
    hand-edited or older-deployment blob whose ``status`` is a JSON list (or whose
    ``outcome`` is an object) would raise ``TypeError`` from inside :func:`read_progress`
    — the one reader whose entire contract is that nothing raises, because its caller is
    the endpoint the My-Companies list cannot live without. A display-only field must
    never be able to 500 that list.
    """
    return value if isinstance(value, str) and value in allowed else fallback


def _safe_url(value: object) -> str | None:
    """``value`` if it is an http(s) URL we are willing to render as a link, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.startswith(_SAFE_URL_PREFIXES):
        return None
    return _clip(text)


def _clean_preview(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """The first :data:`MAX_PREVIEW_JOBS` rows reduced to a renderable {title, location,
    url}. A row with no title is dropped — a preview entry the user cannot read is worse
    than a shorter preview."""
    out: list[dict[str, str]] = []
    for row in rows:
        if len(out) >= MAX_PREVIEW_JOBS:
            break
        if not isinstance(row, Mapping):
            continue
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        entry: dict[str, str] = {"title": _clip(title.strip())}
        location = row.get("location")
        if isinstance(location, str) and location.strip():
            entry["location"] = _clip(location.strip())
        url = _safe_url(row.get("url"))
        if url is not None:
            entry["url"] = url
        out.append(entry)
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProgressLedger:
    """Accumulates step results across ONE discovery run and renders the stored blob.

    Deliberately a tiny mutable accumulator rather than a stream of events: the row
    carries the WHOLE checklist on every write, so a poll that lands mid-run (or a
    write that never happened because the worker died) always renders a complete,
    self-consistent four-step list instead of a partial one the frontend would have to
    reconstruct.

    :meth:`fail` overrides :meth:`finish` on purpose. A step legitimately completes and
    is then invalidated — the pre-filter finds three job-shaped feeds ("found 3
    candidate feeds" ✓) and the selector then says none of them is a jobs list — and the
    user must see the ✕ on the step that actually decided the outcome.
    """

    def __init__(self, *, live_view_url: str | None = None) -> None:
        self._results: dict[str, str] = {}
        self._active: str | None = None
        self._failed: str | None = None
        self._live_view_url = _safe_url(live_view_url)

    @property
    def live_view_url(self) -> str | None:
        return self._live_view_url

    def set_live_view_url(self, url: str | None) -> None:
        """Attach the hosted live-view URL, if this run got one.

        Only a Browserbase session has one and our default is our own Chromium, so it
        is absent on almost every run — the UI treats it as an optional garnish and
        never blocks the checklist on it (plan DECISION D4).
        """
        self._live_view_url = _safe_url(url)

    def start(self, key: str) -> None:
        """Mark ``key`` the step in progress."""
        self._active = key

    def finish(self, key: str, result: str) -> None:
        """Mark ``key`` done, carrying the SPECIFIC thing it found."""
        self._results[key] = _clip(result)
        if self._active == key:
            self._active = None

    def fail(self, key: str, detail: str) -> None:
        """Mark ``key`` the step that failed, carrying why. At most one per run."""
        self._failed = key
        self._results[key] = _clip(detail)
        self._active = None

    def steps(self) -> list[dict[str, Any]]:
        return [
            {
                "key": key,
                "status": (
                    STATUS_FAILED
                    if key == self._failed
                    else STATUS_DONE
                    if key in self._results
                    else STATUS_ACTIVE
                    if key == self._active
                    else STATUS_PENDING
                ),
                "result": self._results.get(key),
            }
            for key in DISCOVERY_STEPS
        ]

    def snapshot(
        self,
        *,
        outcome: str = OUTCOME_RUNNING,
        job_preview: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        """The JSON blob to store under ``provider_config['discovery']``.

        There is deliberately NO separate "current step" key beside ``steps``: two
        representations of the same fact drift, and the one the UI renders would then
        disagree with the one it summarises.
        """
        return {
            "steps": self.steps(),
            "outcome": _one_of(outcome, _OUTCOMES, OUTCOME_RUNNING),
            "live_view_url": self._live_view_url,
            # Also the hook for the future sweeper that un-wedges a 'discovering' row
            # whose worker was SIGKILLed mid-run (see the WEDGED-ROW CAVEAT on the
            # discovery task): "no progress write in N minutes" is the cheap signal.
            "updated_at": _now_iso(),
            "job_preview": _clean_preview(job_preview),
        }


def initial_snapshot() -> dict[str, Any]:
    """The blob written with the provisional ``discovering`` row, before the task runs.

    Without it the row renders a bare "Setting up…" badge for however long the queue
    takes to pick the job up — which is the spinner this whole unit exists to delete.
    """
    ledger = ProgressLedger()
    ledger.start(STEP_OPEN_PAGE)
    return ledger.snapshot()


def read_progress(provider_config: Any) -> dict[str, Any] | None:
    """The discovery blob inside a ``companies.provider_config``, normalized, or None.

    TOTAL BY CONTRACT. The caller is ``GET /api/users/companies``, the one endpoint the
    My-Companies list cannot live without, and the input is a JSONB column that may hold
    an ATS provider config (no ``discovery`` key → ``None``), a blob written by an older
    deployment, or whatever an operator typed. Nothing in here raises: an unrecognised
    shape degrades to ``None`` (badge-only row, exactly today's render) and a partially
    recognised one is trimmed to the parts we can render.

    Unknown step keys are DROPPED and missing ones are filled as ``pending``, so the
    frontend's closed step union always receives exactly the four steps it maps.
    """
    if not isinstance(provider_config, Mapping):
        return None
    raw = provider_config.get("discovery")
    if not isinstance(raw, Mapping):
        return None

    by_key: dict[str, dict[str, Any]] = {}
    raw_steps = raw.get("steps")
    if isinstance(raw_steps, Sequence) and not isinstance(raw_steps, (str, bytes)):
        for entry in raw_steps:
            if not isinstance(entry, Mapping):
                continue
            key = entry.get("key")
            if not isinstance(key, str) or key not in DISCOVERY_STEPS:
                continue
            status = entry.get("status")
            result = entry.get("result")
            by_key[key] = {
                "key": key,
                "status": _one_of(status, _STATUSES, STATUS_PENDING),
                "result": _clip(result) if isinstance(result, str) and result else None,
            }

    steps = [
        by_key.get(key, {"key": key, "status": STATUS_PENDING, "result": None})
        for key in DISCOVERY_STEPS
    ]

    outcome = raw.get("outcome")
    preview = raw.get("job_preview")
    updated_at = raw.get("updated_at")
    return {
        "steps": steps,
        "outcome": _one_of(outcome, _OUTCOMES, OUTCOME_RUNNING),
        "live_view_url": _safe_url(raw.get("live_view_url")),
        "updated_at": updated_at if isinstance(updated_at, str) else None,
        "job_preview": _clean_preview(
            preview
            if isinstance(preview, Sequence) and not isinstance(preview, (str, bytes))
            else ()
        ),
    }
