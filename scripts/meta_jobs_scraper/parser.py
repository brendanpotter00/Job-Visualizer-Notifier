"""
Pure helpers for the Meta GraphQL capture.

Everything here is IO-free and fully unit-testable — no browser, no network.
The browser-driving capture lives in ``scraper.py::MetaJobsScraper.scrape_query``;
this module owns the reduce → parse → dedupe → completeness-guard → raise-or-return
logic it hands the settled capture to.

**Match on shape, not on names.** Meta renamed both its GraphQL operation
(``CareersJobSearchResultsDataQuery`` → ``...V2DataQuery``) and its response
container (``job_search_with_featured_jobs`` → ``..._v2``), which silently
zeroed the sibling ``job-watcher`` adapter for 41 days. So we select the payload
by looking anywhere under ``data`` for a dict carrying an ``all_jobs`` /
``featured_jobs`` array — that survives the next V3 rename of either name.

**Never return ``[]`` on an empty/short capture — raise ``MetaCaptureError``.**
JVN's incremental lifecycle closes any OPEN job absent from a scrape run after
``MISSED_RUN_THRESHOLD`` misses. A scraper that returns ``[]`` (or a truncated
list) during a transient outage is indistinguishable from "every Meta job is
gone" and would mass-close the board (docs/incidents/2026-03-29-mass-job-closure.md).
Because Meta ships the whole catalogue in one response, the ~85% partial_scrape
guard cannot protect against a payload that was 50% read — the completeness
guard against Meta's own ``job_count`` is what closes that gap.
"""

import logging
from collections.abc import Iterator
from typing import Any, Dict, List, Optional

try:  # package-relative when imported as ``meta_jobs_scraper.parser``
    from .config import (
        ALL_JOBS_KEY,
        FEATURED_JOBS_KEY,
        JOB_COUNT_KEY,
        JOB_COUNT_SUFFIX,
        JOB_DETAIL_URL_TEMPLATE,
        LARGE_BODY_BYTES,
        MIN_COMPLETENESS_RATIO,
    )
except ImportError:  # flat-path import (``from config import ...``)
    from config import (  # type: ignore[no-redef]
        ALL_JOBS_KEY,
        FEATURED_JOBS_KEY,
        JOB_COUNT_KEY,
        JOB_COUNT_SUFFIX,
        JOB_DETAIL_URL_TEMPLATE,
        LARGE_BODY_BYTES,
        MIN_COMPLETENESS_RATIO,
    )

import json

logger = logging.getLogger(__name__)


class MetaCaptureError(Exception):
    """Raised when a Meta capture is empty or truncated.

    Named (rather than a bare ``Exception``) so tests can assert on it and so
    the message can carry the five-way diagnosis from ``_empty_capture_reason``.
    Any exception out of ``scrape_query`` triggers the safe path in
    ``run_incremental_scrape`` (record the failure, re-raise, skip the
    destructive close phase); this type makes that intent explicit. The
    sibling-repo analogue is ``TransientAdapterError``; TikTok's is
    ``JobSearchError``.
    """

    pass


def build_job_url(job_id: str) -> str:
    """The canonical public detail URL for a Meta job id."""
    return JOB_DETAIL_URL_TEMPLATE.format(job_id)


def _join_strings(values: Any) -> Optional[str]:
    """Locations and teams come as ``[str, ...]`` or ``[{title: str}, ...]``."""
    if not isinstance(values, list) or not values:
        return None
    parts: List[str] = []
    for v in values:
        if isinstance(v, str) and v:
            parts.append(v)
        elif isinstance(v, dict):
            title = v.get("title") or v.get("name")
            if isinstance(title, str) and title:
                parts.append(title)
    return ", ".join(parts) if parts else None


def parse_list_job(job: Any) -> Optional[Dict[str, Any]]:
    """Map one Meta GraphQL job dict to a plain card dict, or None.

    Drops the row when ``id`` or ``title`` is missing/malformed — those are the
    two fields ``transform_to_job_model`` and the DB write path require. The
    card keys ``job_url`` (not ``url``) because ``BatchWriter`` / the base class
    read ``job_card["job_url"]``.

    Meta's list query carries no posted date, so no ``posted_on`` / ``posted_at``
    key is emitted here — ``first_seen_at`` becomes first sight downstream.
    """
    if not isinstance(job, dict):
        return None

    job_id = job.get("id")
    if not job_id:
        return None
    job_id_str = str(job_id)

    title = job.get("title")
    if not isinstance(title, str) or not title:
        return None

    location = _join_strings(job.get("locations"))
    teams = _join_strings(job.get("teams"))
    sub_teams = _join_strings(job.get("sub_teams"))
    if teams and sub_teams:
        department: Optional[str] = f"{teams} — {sub_teams}"
    else:
        department = teams or sub_teams

    return {
        "id": job_id_str,
        "title": title,
        "location": location,
        "department": department,
        "job_url": build_job_url(job_id_str),
        "company": "meta",
        "raw": job,
    }


def _payload_data(payload: Any) -> Any:
    """Return the ``data`` subtree of a GraphQL payload, or None."""
    return payload.get("data") if isinstance(payload, dict) else None


def _container_jobs(container: Dict[str, Any]) -> List[Any]:
    """The job dicts in one container: ``all_jobs`` then ``featured_jobs``.

    A container qualifies on either array, so the other may be absent or a
    non-list — take each only when it really is a list.
    """
    all_jobs = container.get(ALL_JOBS_KEY)
    featured = container.get(FEATURED_JOBS_KEY)
    return [
        *(all_jobs if isinstance(all_jobs, list) else []),
        *(featured if isinstance(featured, list) else []),
    ]


def _iter_job_containers(node: Any) -> Iterator[Dict[str, Any]]:
    """Yield every dict under ``node`` that carries a job array.

    "Carries a job array" means it has an ``all_jobs`` or ``featured_jobs``
    list. Meta wraps those arrays in a versioned container key
    (``job_search_with_featured_jobs``, then ``..._v2``, presumably ``..._v3``
    one day), so we search by shape instead of hardcoding the wrapper — that
    rename is exactly what broke the sibling adapter for 41 days.

    The walk does NOT stop at a match. Returning at the first hit meant an outer
    node holding an empty ``featured_jobs`` strip hid the real container nested
    beneath it and the whole result set was lost. Descending costs a key lookup
    per job dict — cheap enough that correctness wins easily.
    """
    if isinstance(node, dict):
        if isinstance(node.get(ALL_JOBS_KEY), list) or isinstance(
            node.get(FEATURED_JOBS_KEY), list
        ):
            yield node
        for value in node.values():
            yield from _iter_job_containers(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_job_containers(item)


def _capture_stats(payloads: List[Any]) -> tuple[int, int]:
    """``(containers, job dicts)`` across every captured payload.

    Two numbers rather than one because they diagnose different failures: no
    containers means the payload was renamed, containers-but-no-jobs means Meta
    served an empty board, and jobs-but-nothing-parsed means the per-job field
    names changed.
    """
    containers = 0
    jobs = 0
    for payload in payloads:
        for container in _iter_job_containers(_payload_data(payload)):
            containers += 1
            jobs += len(_container_jobs(container))
    return containers, jobs


def _has_job_payload(payloads: List[Any]) -> bool:
    """True once a captured payload carries a NON-EMPTY job array.

    The settle poll's predicate. It must require actual jobs: the page renders
    strips (saved searches, featured) whose arrays can arrive empty, and
    treating those as "the results are in" ends the poll early and tears the
    browser context down while the real payload is still being read.
    """
    for payload in payloads:
        for container in _iter_job_containers(_payload_data(payload)):
            if _container_jobs(container):
                return True
    return False


def _iter_job_counts(node: Any) -> Iterator[int]:
    """Yield every plausible job-count scalar under ``node``.

    Every one, not the first: a first-hit DFS returns whichever key dict
    iteration order happens to reach first, so a small strip count (say 6) could
    shadow the real total (890) and silently license a partial capture as
    complete.

    Rejects ``bool`` (an int subclass — a stray ``True`` must not become a count
    of 1) and non-positive values (zero/negative sentinels).
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == JOB_COUNT_KEY or key.endswith(JOB_COUNT_SUFFIX):
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value > 0
                ):
                    yield value
            yield from _iter_job_counts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_job_counts(item)


def _advertised_job_count(payloads: List[Any]) -> Optional[int]:
    """Largest job-count scalar the page reported, or None with a warning.

    Meta's filters-bar query returns ``{"job_count": 890}`` alongside the
    results query's 890-entry ``all_jobs`` array, which makes it a free
    completeness oracle.

    None disables the completeness check, so it must not be silent — that is the
    same fail-quiet shape as the bug this whole design exists to avoid. Taking
    the max is deliberate: live, exactly one job_count appears in the whole
    capture, so max and min agree; if Meta ever ships a broader-scope counter,
    over-reporting fails a healthy fetch (the expensive direction), but
    truncation logs before it raises, so a misfire names itself.
    """
    counts = [c for p in payloads for c in _iter_job_counts(_payload_data(p))]
    if not counts:
        logger.warning(
            "Meta capture carried no %r scalar — the completeness check is "
            "disabled for this fetch and a truncated payload would pass "
            "unnoticed. Meta may have renamed the count field.",
            JOB_COUNT_KEY,
        )
        return None
    return max(counts)


def _is_truncated(parsed: int, advertised: Optional[int]) -> bool:
    """True when we parsed materially fewer jobs than the page advertised.

    An absent ``advertised`` disables the check — a missing count must not fail
    an otherwise healthy fetch.
    """
    if advertised is None:
        return False
    return parsed < advertised * MIN_COMPLETENESS_RATIO


def _reduce_payloads(payloads: List[Any]) -> List[Dict[str, Any]]:
    """Flatten captured GraphQL payloads into deduped card dicts.

    Meta's response shape is
    ``{"data": {<versioned container>: {"all_jobs": [...], "featured_jobs": [...]}}}``.
    Containers are located by :func:`_iter_job_containers` rather than by name.
    Featured jobs routinely duplicate entries already present in ``all_jobs``;
    we dedupe on the parsed card ``id`` so the same posting isn't upserted twice.
    """
    cards: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for payload in payloads:
        data = _payload_data(payload)
        if data is None:
            continue
        for container in _iter_job_containers(data):
            for job in _container_jobs(container):
                card = parse_list_job(job)
                if card is None or card["id"] in seen:
                    continue
                seen.add(card["id"])
                cards.append(card)
    return cards


def _unparseable_body_is_suspicious(body: str) -> bool:
    """Whether a GraphQL body we could not JSON-decode deserves a WARNING.

    Most undecodable bodies are page chatter and warning on each would train the
    reader to ignore the log. But if Meta ever moves the results query to
    multipart/``@defer`` streaming, the job payload lands here and a DEBUG line
    is exactly the silence that cost 41 days. Two signals promote it: the body
    mentions the job array, or it is large enough to be the results payload.
    """
    return ALL_JOBS_KEY in body or len(body) >= LARGE_BODY_BYTES


def _decode_graphql_payload(body: str) -> Optional[Dict[str, Any]]:
    """JSON-decode a captured GraphQL body, or None if it is unusable.

    Split out of the response handler so the decode-and-log decision is testable
    — the handler itself runs inside Playwright's event loop.
    """
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        # Normally page chatter. But a body that mentions the job array, or is
        # big enough to BE the results payload, is the shape Meta switching to
        # multipart/@defer would take, and dropping that at DEBUG is how a
        # rename goes unnoticed for 41 days.
        if _unparseable_body_is_suspicious(body):
            logger.warning(
                "Meta GraphQL response of %d bytes could not be JSON-decoded "
                "and looks like it held job data — the results query may now "
                "be streamed in chunks.",
                len(body),
            )
        else:
            logger.debug("Meta GraphQL response wasn't valid JSON")
        return None
    return payload if isinstance(payload, dict) else None


class _SettlePoll:
    """Decides when the response capture has settled. Pure — no I/O, no sleep.

    Two phases:

    *wait* — poll until a payload with a non-empty job array lands, or the wait
    budget runs out (the caller then raises with a diagnosis).

    *drain* — once one has, keep polling until the number of captured payloads
    holds steady for ``stable_polls`` ticks, capped by ``drain_polls``. Leaving
    the browser context cancels any response body still being read, so anything
    that lands after the results payload is lost.

    The load-bearing half is the wait phase requiring a *non-empty* array: a
    strip resolving empty ahead of the results would otherwise end the poll
    before the real payload had been read at all.
    """

    def __init__(
        self, wait_polls: int, drain_polls: int, stable_polls: int
    ) -> None:
        self._wait_polls = wait_polls
        self._drain_polls = drain_polls
        self._stable_polls = stable_polls
        self._waited = 0
        self._drained = 0
        self._stable = 0
        self._last_len = -1
        self.draining = False

    def should_stop(self, payloads: List[Any]) -> bool:
        """True when the caller should stop polling and tear the page down."""
        if not self.draining:
            if _has_job_payload(payloads):
                self.draining = True
                self._last_len = len(payloads)
                return False
            self._waited += 1
            return self._waited >= self._wait_polls
        self._drained += 1
        if len(payloads) == self._last_len:
            self._stable += 1
        else:
            self._last_len = len(payloads)
            self._stable = 0
        return (
            self._stable >= self._stable_polls
            or self._drained >= self._drain_polls
        )


def _empty_capture_reason(
    graphql_seen: int,
    nav_error: Optional[BaseException],
    *,
    containers_seen: int = 0,
    jobs_seen: int = 0,
) -> str:
    """Explain *why* the capture produced no jobs, for the raised error message.

    Five distinguishable failure modes, and the operator response differs for
    each: the page never loaded (retry / check the network), the page loaded but
    issued no GraphQL (bot wall, markup rewrite), GraphQL responded but nothing
    carried job arrays (Meta renamed the payload again), the arrays arrived
    well-formed and empty (a served-empty board), or the arrays were full but no
    entry parsed (the per-job field names changed, a rename one level down).
    """
    if jobs_seen > 0:
        return (
            f"Meta scrape found {jobs_seen} job entries but parsed none of "
            f"them — the per-job fields (id/title) have likely been renamed, "
            f"so check parse_list_job against a live payload"
        )
    if containers_seen > 0:
        return (
            "Meta scrape found a well-formed job array but it was empty — "
            "Meta served an empty board (regional block or bot wall?) rather "
            "than renaming the payload"
        )
    if graphql_seen == 0:
        if nav_error is not None:
            return (
                f"Meta scrape saw no GraphQL traffic and the page navigation "
                f"failed: {nav_error!r}"
            )
        return (
            "Meta scrape loaded the page but observed zero GraphQL POST "
            "responses — the listings page may be behind a bot wall"
        )
    suffix = f" (page navigation also failed: {nav_error!r})" if nav_error else ""
    return (
        f"Meta scrape captured {graphql_seen} GraphQL response(s) but none "
        f"contained a {ALL_JOBS_KEY!r}/{FEATURED_JOBS_KEY!r} array — Meta has "
        f"likely renamed the job-search payload again{suffix}"
    )


def _finalize_capture(
    captured: List[Any],
    *,
    graphql_seen: int,
    nav_error: Optional[BaseException],
) -> List[Dict[str, Any]]:
    """Turn a settled capture into card dicts, or raise explaining why not.

    Deliberately pure — no browser, no network — so both raise sites and the
    completeness check are exercised by unit tests.

    Raises ``MetaCaptureError`` rather than returning ``[]`` so an empty or
    partial result never reaches the incremental lifecycle's close sweep. The
    truncation guard runs on the FULL parsed set, BEFORE any US/title filter:
    ``job_count`` counts Meta's whole returned catalogue, so comparing it
    against a post-filter kept count would false-trip every run.
    """
    cards = _reduce_payloads(captured)

    if not cards:
        containers_seen, jobs_seen = _capture_stats(captured)
        raise MetaCaptureError(
            _empty_capture_reason(
                graphql_seen,
                nav_error,
                containers_seen=containers_seen,
                jobs_seen=jobs_seen,
            )
        )

    # Meta ships the whole catalogue in one response, so a shortfall against the
    # advertised count means a truncated payload, not a shrinking board — and
    # upserting the partial list would let the sweep close every posting the
    # capture missed.
    advertised = _advertised_job_count(captured)
    if _is_truncated(len(cards), advertised):
        # Log before raising: if this guard ever misfires on healthy data it
        # takes Meta to zero, so the numbers behind the decision have to be in
        # the operator's log rather than only in the exception.
        logger.warning(
            "Meta capture looks truncated: parsed %d jobs against an "
            "advertised %d (threshold %.0f%%). Refusing to report a partial "
            "catalogue.",
            len(cards),
            advertised,
            MIN_COMPLETENESS_RATIO * 100,
        )
        raise MetaCaptureError(
            f"Meta scrape parsed {len(cards)} jobs but the page advertised "
            f"{advertised} — the captured payload looks truncated; refusing to "
            f"report a partial catalogue"
        )

    if nav_error is not None:
        # Recovered: the capture succeeded despite a failed/timed-out
        # navigation. Surfaced as a warning so a page that is quietly
        # half-failing every run does not look perfectly healthy.
        logger.warning(
            "Meta list page navigation raised %r, but the capture still "
            "produced %d jobs — continuing. Repeated occurrences mean the page "
            "is loading slowly or partially.",
            nav_error,
            len(cards),
        )

    return cards
