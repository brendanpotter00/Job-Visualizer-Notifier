"""DISCOVERY PROGRESS — the 5-step checklist the user actually reads (E7 capture pivot).

Discovery used to be an opaque spinner ("Setting up…") because the retired DOM agent's
work genuinely was unpredictable: nobody could say what it would do next. The capture
engine's steps are DETERMINISTIC and known before the run starts, so there is no longer
any excuse for a spinner. This module is the vocabulary for saying, out loud, where a
run got to and what it found:

1. :data:`STEP_OPEN_PAGE`   — opening the careers page
2. :data:`STEP_FIND_FEED`   — finding the jobs feed
3. :data:`STEP_VERIFY_READ` — verifying we can read it
4. :data:`STEP_READY`       — ready to track
5. :data:`STEP_FIRST_SCAN`  — reading the board for the first time

The first four, not the engine's six. The engine's internal steps are named for the code
that can fail (``writing the replay recipe`` is a distinct failure with a distinct log
line); the user's are named for the things a person can act on. :mod:`api.services.
capture.discover` owns the mapping between them, because it owns both.

THE FIFTH RUNG IS NOT DISCOVERY'S — it belongs to the first ``fetch_custom_company``
harvest, and it exists because the first four going green was a LIE ABOUT THE THING THE
USER WAS LOOKING AT. Discovery ends by proving we can read the board and enqueuing the
first harvest; until that harvest lands the company's row honestly says "0 open jobs",
and a complete green checklist above it read as "we finished and found nothing". So
discovery ticks 1-4 and STARTS rung 5, and the harvest task settles it (:func:`with_
first_scan`) with the jobs it actually stored — or an ✕ carrying why it did not. "Ready
to track" stays a discovery outcome because it is TRUE the moment the recipe is proven;
what was missing was any rung for the scan itself.

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

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit

# The four user-facing steps, in display order. These keys are an API contract: the
# frontend maps them through a closed `Record<DiscoveryStepKey, …>` so a rename here is
# a compile error there rather than a blank row.
STEP_OPEN_PAGE = "open_page"
STEP_FIND_FEED = "find_feed"
STEP_VERIFY_READ = "verify_read"
STEP_READY = "ready"
# Written by the HARVEST task, not by discovery — see the module docstring. A row that
# predates this rung reads it back as ``pending`` (``read_progress`` fills missing steps),
# which is exactly right for a board discovered before the rung existed, and self-heals
# to a ✓ on its next nightly harvest.
STEP_FIRST_SCAN = "first_scan"

DISCOVERY_STEPS: tuple[str, ...] = (
    STEP_OPEN_PAGE,
    STEP_FIND_FEED,
    STEP_VERIFY_READ,
    STEP_READY,
    STEP_FIRST_SCAN,
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


# --------------------------------------------------------------------------
# THE NETWORK LOG — the evidence behind the verdict ("show me what you did")
# --------------------------------------------------------------------------
# The checklist says WHAT happened; this says what we SAW. It exists because the
# refusal "none of the 14 JSON requests this page made is a list of job postings" is a
# conclusion with no evidence attached: the user cannot tell whether we looked at the
# wrong page, whether their board is server-rendered, or whether we simply missed it.
# Fourteen rows carrying method/URL/status/size — and, on the one we picked, the bytes
# it actually returned — turn that assertion into something a person can check.
#
# EVERYTHING HERE IS PUBLISHED TO A BROWSER, so the rules are the same ones
# ``capture.discover._clean_headers`` applies to a stored recipe, only stricter:
#
# * NO request headers and NO cookies, ever. Not a filtered subset — none. The capture
#   browser earns a session on the board's own origin, and a header list is where that
#   session lives; there is no display value in it that is worth publishing a bearer
#   token for.
# * NO query VALUES. A board that signs its URLs puts the signature in the query
#   (``?sig=``, ``?token=``, an opaque blob with no ``=`` at all), and there is no
#   reliable way to tell a signed parameter from a benign one by its name. So the names
#   survive — they are a schema, and ``limit``/``offset``/``department`` is exactly how
#   a person recognises the search endpoint — and every value becomes ``…``.
# * NO userinfo and NO port. ``https://user:pass@host`` is a credential in a URL; the
#   hostname is taken through ``urlsplit().hostname``, which drops both.
# * NO POST bodies. A POSTed jobs query is often the whole session envelope.
#
# The residual hole, stated rather than papered over: a board that signs in the PATH
# (``/v0/<sig>/jobs``) publishes that path, and this does not try to guess which path
# segments are opaque. Dropping paths would delete the only part of a URL a person can
# recognise, which is the whole point of the panel. Two things bound it. The row belongs
# to the user who pasted the URL and is served only to them. And the session in question
# is not theirs and never was: the capture runs in a FRESH headless Chromium of ours
# with no profile and no user cookies, so anything credential-shaped in that URL is an
# anonymous token our own browser earned seconds earlier from a public careers page.

# One recorded response, by what happened to it. ``recorded`` is the default and means
# "we saw it"; the rest are the three things that can make a response unusable, and each
# one is a different sentence for the user.
REQUEST_RECORDED = "recorded"
REQUEST_OVERSIZE = "oversize"   # body over the capture's per-response ceiling
REQUEST_BLOCKED = "blocked"     # job-shaped, but its address failed the SSRF re-check
REQUEST_CHOSEN = "chosen"       # the one we picked AND proved we can replay

_REQUEST_STATES = frozenset({
    REQUEST_RECORDED, REQUEST_OVERSIZE, REQUEST_BLOCKED, REQUEST_CHOSEN,
})

# The capture child records at most 40 responses (``_capture_main._MAX_RESPONSES``), so
# this is that same ceiling and not an independent budget: clipping BELOW it would show
# "24 of the 40 requests" as the evidence for a refusal that counted all 40.
MAX_REQUEST_ROWS = 40

# Per-row display budgets. Every one of these is a size guard first and a taste choice
# second: this blob is written to Postgres and re-read by every open tab every ~4s while
# a discovery runs, so an unbounded URL from a stranger's board is a payload multiplier.
_MAX_URL_CHARS = 160
_MAX_QUERY_NAMES = 8
_MAX_NOTE_CHARS = 120

# The payload sample. A SAMPLE, not the body — the body can be 4 MB and the question it
# answers ("is this my board?") is settled by one record. Strings inside it are clipped
# first so the budget is spent on SHAPE (many keys) rather than on one board's
# 40 KB HTML description.
_MAX_SAMPLE_CHARS = 1200
_MAX_SAMPLE_STRING_CHARS = 200
_MAX_SAMPLE_DEPTH = 6

# ...and the whole-object backstop: THE number that actually bounds what every open tab
# re-downloads every 4 seconds while a discovery runs. The per-row budgets multiply
# (40 x 160 characters of URL alone is ~10 KB); this one does not.
#
# It is set to BIND rather than to reassure. At 16,000 it could never fire — the per-row
# caps already held the worst case under it — which is a guard that reads as protection
# and is really dead code, and the mutation test proved exactly that. At 9,000 it binds
# the pathological board (40 responses with 160-character URLs, which loses its last few
# rows while ``recorded`` keeps saying 40) and still clears every real capture measured:
# lifeatspotify.com's 14 rows are ~2.5 KB, and forty Spotify-length URLs would be ~7.6 KB.
_MAX_NETWORK_JSON_CHARS = 9_000

# Keys whose VALUE is redacted out of a payload sample. Same substrings the recipe
# synthesizer drops request headers on, for the same reason: a board that echoes its own
# session token back inside the JSON would otherwise have it rendered into the DOM.
_SECRETISH_KEY_SUBSTRINGS = (
    "token", "auth", "session", "csrf", "xsrf", "signature", "secret", "password",
    "cookie", "apikey", "api_key", "credential",
)


def _as_int(value: object) -> int:
    """``value`` as an ``int``, or ``0``. Bools are NOT ints here — a status of ``True``
    would render as ``1`` and look like a real HTTP code."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _clip_to(text: str, limit: int) -> str:
    """``text`` bounded to ``limit`` characters, with an ellipsis when it was cut."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _http_verb(value: object) -> str:
    """``value`` as an HTTP verb we are willing to render, else ``"GET"``.

    Letters only, eight of them at most. The input is a string a BROWSER reported about
    a request a stranger's page made — or, on the read path, whatever is in a JSONB
    column — and it is rendered. ``str(["GET"])`` is how a hand-edited blob turns a
    method cell into ``['GET']``; this is the same filter on both sides so it cannot.
    """
    if not isinstance(value, str):
        return "GET"
    verb = "".join(c for c in value.upper() if c.isalpha())[:8]
    return verb or "GET"


def display_url(value: object) -> str:
    """The most of a captured URL we are willing to RENDER.

    ``scheme://host/path`` plus the query's parameter NAMES with every value replaced by
    ``…``. See the module's NETWORK LOG note for why the values go and the names stay.

    Total, like everything else in this module: a value that is not a string, or a URL
    that does not parse, becomes ``"(unreadable URL)"`` rather than raising inside a
    display-only writer.
    """
    if not isinstance(value, str) or not value.strip():
        return "(unreadable URL)"
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return "(unreadable URL)"
    scheme = parts.scheme.lower() if parts.scheme.lower() in ("http", "https") else ""
    # ``hostname`` — NOT ``netloc``. It drops the ``user:pass@`` a credential-in-URL
    # lives in, and the port, which is noise on every board we have ever captured.
    host = parts.hostname or ""
    base = f"{scheme}://{host}{parts.path}" if scheme and host else parts.path or value
    if not parts.query:
        return _clip_to(base, _MAX_URL_CHARS)
    # A NAME IS ONLY A NAME IF THE BOARD SPELLED IT AS ONE. ``parse_qsl`` is used to
    # split and percent-decode, but a segment carrying no ``=`` is not a parameter — it
    # is an opaque token in query position (a bare signature, a base64 blob), and
    # ``keep_blank_values`` would happily hand it back as a "name" and render the
    # signature we are here to suppress. Same reason an over-long name is dropped: a
    # 24-character parameter name is a schema, a 300-character one is a payload.
    segments = [seg for seg in parts.query.split("&") if seg]
    shown: list[str] = []
    for segment in segments[:_MAX_QUERY_NAMES]:
        if "=" not in segment:
            shown.append("…")
            continue
        pairs = parse_qsl(segment, keep_blank_values=True)
        name = pairs[0][0] if pairs else ""
        shown.append(f"{name}=…" if name and len(name) <= 24 else "…")
    if len(segments) > _MAX_QUERY_NAMES:
        shown.append(f"+{len(segments) - _MAX_QUERY_NAMES} more")
    if not shown:
        return _clip_to(f"{base}?…", _MAX_URL_CHARS)
    return _clip_to(f"{base}?{'&'.join(shown)}", _MAX_URL_CHARS)


def _redact(node: Any, depth: int = 0) -> Any:
    """One payload node with credential-shaped values removed and strings clipped.

    Two jobs, both size-and-safety: a board that echoes a session token back in its own
    JSON must not have it rendered into the DOM, and a single 40 KB description must not
    eat the entire sample budget before the reader sees the second key.
    """
    if depth >= _MAX_SAMPLE_DEPTH:
        return "…"
    if isinstance(node, Mapping):
        out: dict[str, Any] = {}
        for raw_key, value in node.items():
            key = str(raw_key)
            if any(sub in key.lower() for sub in _SECRETISH_KEY_SUBSTRINGS):
                out[key] = "…"
                continue
            out[key] = _redact(value, depth + 1)
        return out
    if isinstance(node, (list, tuple)):
        return [_redact(item, depth + 1) for item in list(node)[:3]]
    if isinstance(node, str):
        return _clip_to(node, _MAX_SAMPLE_STRING_CHARS)
    return node


def payload_sample(record: Any) -> str | None:
    """ONE record from the chosen feed, pretty-printed, redacted and clipped.

    The answer to "show me the JSON". Deliberately one RECORD and not the response
    envelope: the envelope is where a board puts its own session state, the record is
    the job posting the user is trying to recognise, and a 4 MB body is not a thing to
    put on a 4-second poll either way.
    """
    if record is None:
        return None
    try:
        text = json.dumps(_redact(record), indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - default=str covers the field
        return None
    return _clip_to(text, _MAX_SAMPLE_CHARS)


def _clean_preview(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """The first :data:`MAX_PREVIEW_JOBS` rows reduced to a renderable {title, location,
    url}. A row with no title is dropped — a preview entry the user cannot read is worse
    than a shorter preview.

    Only these three fields are ever echoed back. Anything else the board returned (ids,
    salary bands, raw HTML descriptions) is dropped — this blob is rendered, and echoing
    arbitrary captured fields into the DOM is how a scraped payload becomes a rendering
    surface.
    """
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


def _clean_network(raw: Any) -> dict[str, Any]:
    """A stored network log, normalized for rendering, or the empty one.

    TOTAL, exactly like everything else :func:`read_progress` calls. The input is a
    JSONB column that may hold a blob written before this key existed (``None`` ->
    empty), one written by a newer deployment, or whatever an operator typed. Each row
    is rebuilt field by field rather than passed through, so an extra key someone adds
    to the writer can never reach the DOM without passing through here first.

    The URL is run through :func:`display_url` AGAIN on read. It was already sanitized
    on write, and that is the point: a blob already in the database predates whatever we
    tighten later, and the redaction that matters is the one that runs on the way out.
    """
    empty: dict[str, Any] = {"requests": [], "recorded": 0, "sample": None}
    if not isinstance(raw, Mapping):
        return empty

    rows: list[dict[str, Any]] = []
    raw_rows = raw.get("requests")
    if isinstance(raw_rows, Sequence) and not isinstance(raw_rows, (str, bytes)):
        for entry in raw_rows:
            if len(rows) >= MAX_REQUEST_ROWS:
                break
            if not isinstance(entry, Mapping):
                continue
            records = entry.get("records")
            note = entry.get("note")
            rows.append({
                "method": _http_verb(entry.get("method")),
                "url": display_url(entry.get("url")),
                "status": _as_int(entry.get("status")),
                "bytes": max(0, _as_int(entry.get("bytes"))),
                "records": (
                    _as_int(records)
                    if isinstance(records, int) and not isinstance(records, bool)
                    else None
                ),
                "state": _one_of(
                    entry.get("state"), _REQUEST_STATES, REQUEST_RECORDED
                ),
                "note": (
                    _clip_to(note, _MAX_NOTE_CHARS)
                    if isinstance(note, str) and note else None
                ),
            })

    sample: dict[str, Any] | None = None
    raw_sample = raw.get("sample")
    if isinstance(raw_sample, Mapping):
        body = raw_sample.get("text")
        if isinstance(body, str) and body:
            sample = {
                "path": _clip_to(str(raw_sample.get("path") or ""), 80),
                "records": max(0, _as_int(raw_sample.get("records"))),
                "text": _clip_to(body, _MAX_SAMPLE_CHARS),
            }

    return {
        "requests": rows,
        # Never below the number of rows we are about to render — a blob whose counter
        # was hand-edited down would otherwise produce "3 requests" over a list of 12.
        "recorded": max(_as_int(raw.get("recorded")), len(rows)),
        "sample": sample,
    }


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
        # THE NETWORK LOG, accumulated in CAPTURE ORDER and never re-sorted. Ranking it
        # by score the moment the pre-filter runs would make every row jump position on
        # one poll, which reads as a glitch rather than as progress — and arrival order
        # is the only ordering the reader can check against their own devtools.
        self._requests: list[dict[str, Any]] = []
        self._sample: dict[str, Any] | None = None

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

    # -- the network log ---------------------------------------------------
    #
    # Four calls, in the order discovery makes them: one per response as the browser
    # sees it (live), the authoritative replacement when the capture returns, the
    # pre-filter's verdict on each, and finally the winner plus its payload sample.

    def note_request(
        self,
        *,
        method: object,
        url: object,
        status: object,
        size_bytes: object,
        truncated: bool = False,
    ) -> None:
        """Append ONE response the capture browser recorded. Sanitizes as it goes.

        Called TWICE over the same traffic on purpose — once per streamed event while
        the browser is still open (so the list grows in front of the user), and again
        over the finished capture after :meth:`reset_requests`. The second pass is the
        authoritative one: the parent drops report entries it cannot read, so a streamed
        row and a capture row are not guaranteed to be the same set, and rebuilding
        beats trying to reconcile two lists by index.
        """
        if len(self._requests) >= MAX_REQUEST_ROWS:
            return
        self._requests.append({
            "method": _http_verb(method),
            "url": display_url(url),
            "status": _as_int(status),
            "bytes": max(0, _as_int(size_bytes)),
            # ``None`` means "we have not looked at this yet", which is a different
            # thing from "we looked and found no jobs in it" (``0``). The UI says so.
            "records": None,
            "state": REQUEST_OVERSIZE if truncated else REQUEST_RECORDED,
            "note": None,
        })

    def reset_requests(self) -> None:
        """Drop the live list so the finished capture can replace it wholesale."""
        self._requests = []

    def score_requests(
        self,
        records_by_index: Mapping[int, int],
        *,
        blocked: Iterable[int] = (),
    ) -> None:
        """Attach the pre-filter's verdict to every row: how many job-shaped records.

        EVERY row is marked, not only the survivors. A response we examined and found no
        job array in is the evidence for the commonest refusal we serve ("none of the 14
        JSON requests this page made returned a list of job postings"), and leaving those
        rows at ``records: null`` would make that refusal look like we never got to them.
        """
        blocked_set = set(blocked)
        for index, row in enumerate(self._requests):
            # An oversize body was never parsed, so it has no record count to report and
            # a ``0`` there would blame the board for OUR ceiling — the exact confusion
            # the capture's ``truncated`` flag exists to prevent.
            if row["state"] == REQUEST_OVERSIZE:
                continue
            row["records"] = int(records_by_index.get(index, 0))
            if index in blocked_set:
                row["state"] = REQUEST_BLOCKED
                row["note"] = "we refuse to fetch this address"

    def choose_request(
        self,
        index: int,
        *,
        note: str,
        records_path: str | None = None,
        records: int | None = None,
        sample: str | None = None,
    ) -> None:
        """Mark the winner and attach a sample of what it returned.

        Only ever called once a replay FROM OUR OWN ENVIRONMENT has proved the recipe,
        so "chosen" here means "picked and proved" rather than "the model liked it" —
        which is the whole distinction the acceptance gate exists to make.
        """
        if 0 <= index < len(self._requests):
            row = self._requests[index]
            row["state"] = REQUEST_CHOSEN
            row["note"] = _clip_to(note, _MAX_NOTE_CHARS)
            if records is not None:
                row["records"] = int(records)
        if sample is not None:
            self._sample = {
                "path": _clip_to(str(records_path or ""), 80),
                "records": int(records) if records is not None else 0,
                # ``text``, not ``json``: this is the pretty-printed, redacted, clipped
                # RENDERING of one record, and a key called ``json`` on the wire would
                # also collide with ``BaseModel.json`` in the response model.
                "text": _clip_to(sample, _MAX_SAMPLE_CHARS),
            }

    def _network(self) -> dict[str, Any]:
        """The network log as stored — bounded a second time, on aggregate.

        The per-row caps above MULTIPLY; this one does not. It is the number that
        actually bounds what every open tab downloads every four seconds while a
        discovery runs, so it is applied to the SERIALIZED object rather than to a row
        count somebody would later have to keep in sync with the row schema.
        """
        rows = self._requests
        while rows and len(json.dumps(rows)) > _MAX_NETWORK_JSON_CHARS:
            rows = rows[:-1]
        return {
            "requests": rows,
            # What we SAW, which stays honest even when the aggregate cap dropped rows:
            # a list of 11 under a heading that says 14 is the truth, and "14 requests"
            # over a list of 14 that is really 11 is not.
            "recorded": len(self._requests),
            "sample": self._sample,
        }

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
            # The EVIDENCE behind every line above it. Present on every write, including
            # the very first one, so the shape the frontend reads never changes mid-run.
            "network": self._network(),
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
    frontend's closed step union always receives exactly the five steps it maps — a blob
    written before the FIRST-SCAN rung existed reads back with that rung ``pending``.
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
        "network": _clean_network(raw.get("network")),
    }


def with_first_scan(
    provider_config: Any, *, ok: bool, detail: str
) -> dict[str, Any] | None:
    """``provider_config``'s discovery blob with the FIRST-SCAN rung settled, or None.

    The one seam through which the HARVEST task touches a checklist discovery wrote.
    ``None`` means "this row has no checklist" (every ATS company, and any custom row
    added before discovery existed) and the caller must then write NOTHING — that is
    what keeps this display-only blob off the harvest's critical path.

    It re-normalizes through :func:`read_progress` on purpose: the input is a JSONB
    column, the writer is a task whose whole contract is that it never breaks a harvest,
    and a blob that has been hand-edited or written by an older deployment must degrade
    rather than raise. Same reason the ✕ carries ``detail`` verbatim-but-clipped: it is
    rendered, and an unbounded exception string on a rendered rung is how one bad board
    bloats every row of the list response.

    Deliberately NOT "only if the rung is still pending". A first scan that FAILED must
    be able to become a ✓ when the next nightly harvest succeeds, or the row would carry
    a permanent ✕ describing a problem that has since gone away. Overwriting a ✓ with an
    identical ✓ every night is free by comparison.
    """
    normalized = read_progress(provider_config)
    if normalized is None:
        return None
    normalized["steps"] = [
        {
            "key": STEP_FIRST_SCAN,
            "status": STATUS_DONE if ok else STATUS_FAILED,
            "result": _clip(detail),
        }
        if step["key"] == STEP_FIRST_SCAN
        else step
        for step in normalized["steps"]
    ]
    normalized["updated_at"] = _now_iso()
    return normalized
