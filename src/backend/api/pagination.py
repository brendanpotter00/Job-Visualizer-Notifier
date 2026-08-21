"""Opaque keyset cursors for the ``GET /api/jobs`` list endpoint.

WHY KEYSET AND NOT OFFSET
-------------------------
``LIMIT/OFFSET`` paging over ``/api/jobs`` is unsound here for two independent
reasons, and both fail *silently* — the caller gets a 200 with a plausible-looking
page that is quietly missing rows:

1. **The sort key churns.** The legacy ordering is ``job_freshness.last_seen_at
   DESC``, and that column is re-stamped on *every* OPEN row on *every* hourly
   scrape cycle (see ``docs/incidents/2026-07-13-api-jobs-outage.md``). A scrape
   landing between page N and page N+1 reshuffles the entire ordering underneath
   the offset, so rows slide across the page boundary and are never returned.
2. **Inserts shift the window.** New listings land at the head of a DESC ordering,
   pushing every subsequent row one slot further down; an offset-based page N+1
   then re-serves rows the caller already saw and skips the same number at the tail.

Keyset paging fixes both by remembering *where you were* rather than *how far in*.
This module owns the wire format of that "where".

THE SORT KEY: ``(first_seen_at DESC, source_id DESC, id DESC)``
--------------------------------------------------------------
* ``first_seen_at`` is **immutable** — stamped once when we first observe a listing
  and never rewritten (unlike ``last_seen_at``, which is the churny one). An
  immutable sort key is what makes a cursor stable across concurrent scrapes.
* ``(source_id, id)`` is ``job_listings``' composite PRIMARY KEY, so appending it
  makes the tuple **unique**. Without a unique tiebreak, rows sharing a
  ``first_seen_at`` (batch inserts do this constantly — a whole company's first
  scrape shares one timestamp) would page non-deterministically: rows dropped,
  rows duplicated, no error.
* It matches what the UI already does client-side — ``selectRecentJobsSorted``
  (``src/frontend/src/features/filters/selectors/recentJobsSelectors.ts``) sorts by
  ``firstSeenAt`` DESC — so server-side paging does not reorder the list.

WIRE FORMAT
-----------
``base64url( "<first_seen_at ISO-8601 UTC>|<source_id>|<id>" )``, unpadded.

Opaque *by convention* — it is deliberately not signed or encrypted. It encodes
nothing a caller could not already read off the response body, so obfuscation
would buy nothing; base64url is here to keep the delimiter and any exotic ATS job
id out of the query string, not to hide anything. Callers must treat it as a
blob and echo it back verbatim.

Validation is **fail-loud** (:class:`InvalidCursorError` -> HTTP 422 at the router),
never "ignore it and serve page 1". A cursor the server silently discards is
indistinguishable to the client from a cursor it honoured, and the result is the
exact failure this whole module exists to prevent: a paging walk that quietly
restarts and never terminates, or terminates early and drops the tail.
"""

import base64
import binascii
import re
from datetime import datetime, timezone
from typing import NamedTuple

# ``source_id`` is a controlled vocabulary (``scripts/shared/constants.py``
# ``SourceId``: google_scraper, greenhouse_api, ashby_api, ...) plus the E7
# per-company custom namespace ``custom:<company_id>``. The pattern is
# deliberately a little wider than today's values so adding an ATS does not
# require touching this file, but narrow enough to reject the ``|`` delimiter
# and any binary garbage a malformed cursor might carry.
#
# ``:`` is in the class for ``custom:<id>``. Without it every private custom job
# was un-pageable: ``encode_job_cursor`` raised a ValueError -> 500 on the FIRST
# full page of the owner-scoped feed. It is safe to admit — the field separator
# is ``|`` and ``:`` cannot appear in the leading ISO-8601 field's *split*
# semantics (``maxsplit=2`` only ever splits on ``|``).
#
# ``\Z``, NOT ``$``: in Python ``$`` also matches immediately before a trailing
# newline, so ``"google_scraper\n"`` would pass a ``$``-anchored check and then be
# compared against the column as a different string — a cursor that validates and
# silently matches nothing. ``\Z`` anchors at the true end of the string.
_SOURCE_ID_RE = re.compile(r"\A[A-Za-z0-9_.:\-]{1,100}\Z")

# Bounds the decode work a single request can ask for. A real cursor is ~100
# chars; anything near this ceiling is an attack or a bug, not a page token.
MAX_CURSOR_LENGTH = 512

# Bounds the ``since`` parameter. An ISO-8601 instant is <= ~40 chars.
MAX_TIMESTAMP_LENGTH = 64

_CURSOR_FIELD_SEPARATOR = "|"


class JobCursor(NamedTuple):
    """Decoded keyset position: the last row of the previous page.

    The next page is every row that sorts strictly *after* this tuple under
    ``(first_seen_at DESC, source_id DESC, id DESC)``.
    """

    first_seen_at: datetime
    source_id: str
    job_id: str


class InvalidCursorError(ValueError):
    """A client-supplied ``cursor`` could not be decoded into a :class:`JobCursor`.

    Carries a human-readable reason; the router surfaces it verbatim in the 422
    ``detail`` so a caller debugging a broken paging loop sees *which* part of
    their cursor was wrong rather than a generic "bad request".
    """


def parse_utc_timestamp(raw: str, *, field: str) -> datetime:
    """Parse a strict ISO-8601 **timezone-aware** instant and normalize to UTC.

    Naive (offset-less) input is rejected on purpose. ``first_seen_at`` is a
    ``TIMESTAMP WITH TIME ZONE``; comparing it against a naive literal would make
    the boundary depend on the server's ``TimeZone`` GUC — a silently
    environment-dependent result set, which is precisely the class of bug this
    endpoint is being hardened against. ``Z`` is accepted as ``+00:00``.

    :raises ValueError: on anything that is not a tz-aware ISO-8601 instant, or on
        an instant that parses but cannot be shifted to UTC (see below).
    """
    if len(raw) > MAX_TIMESTAMP_LENGTH:
        raise ValueError(f"{field} must be at most {MAX_TIMESTAMP_LENGTH} characters")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError(
            f"{field} must be an ISO-8601 timestamp with a UTC offset "
            f"(e.g. 2026-08-05T00:00:00Z); got {raw!r}"
        ) from None
    if parsed.tzinfo is None:
        raise ValueError(
            f"{field} must carry a timezone offset (e.g. 2026-08-05T00:00:00Z); "
            f"got the naive value {raw!r}"
        )
    try:
        return parsed.astimezone(timezone.utc)
    except OverflowError:
        # NOT hypothetical, and NOT covered by the ValueError above: a value at the
        # very edge of `datetime`'s range with a non-zero offset parses fine and
        # then overflows when shifted to UTC — e.g. `0001-01-01T00:00:00+14:00`
        # (would land before year 1) or `9999-12-31T23:59:59-14:00` (after year
        # 9999). OverflowError is not a subclass of ValueError, so it would escape
        # both call sites' handlers and surface as a public 500, contradicting the
        # fail-loud-with-a-422 contract this module is built around. Converted here
        # rather than at the call sites so every future caller inherits the fix.
        # (Same defensive shape as `services/lever_client.py:200`, which catches
        # `(OverflowError, OSError, ValueError)` around epoch conversion.)
        raise ValueError(
            f"{field} is outside the representable date range once converted to "
            f"UTC; got {raw!r}"
        ) from None


def encode_job_cursor(
    first_seen_at: datetime | str, source_id: str, job_id: str
) -> str:
    """Build the opaque cursor that points *at* the given row.

    ``first_seen_at`` accepts a ``str`` because the list rows have already been
    ISO-serialized by ``services.database._row_to_job_dict`` by the time the
    router mints the next-page cursor. Postgres timestamps are microsecond
    precision and :meth:`datetime.isoformat` round-trips microseconds exactly, so
    the string path loses nothing — a lossy round-trip here would land the keyset
    boundary between two real rows and drop or duplicate one.

    ``source_id`` is validated against the SAME pattern :func:`decode_job_cursor`
    enforces. Encode and decode must agree: a ``source_id`` containing the ``|``
    separator would mint a cursor that decodes into different fields than it was
    built from, so the very next page would resume from a position nobody chose.
    Failing at mint time turns that into a loud server-side error on the row that
    caused it, instead of a quietly wrong walk for the client.

    :raises ValueError: on a naive ``first_seen_at`` or an out-of-vocabulary
        ``source_id``.
    """
    if not _SOURCE_ID_RE.match(source_id):
        raise ValueError(
            f"encode_job_cursor got a source_id that cannot round-trip through a "
            f"cursor: {source_id!r}"
        )
    if isinstance(first_seen_at, str):
        moment = parse_utc_timestamp(first_seen_at, field="first_seen_at")
    else:
        if first_seen_at.tzinfo is None:
            raise ValueError(
                "encode_job_cursor requires a timezone-aware first_seen_at"
            )
        moment = first_seen_at.astimezone(timezone.utc)
    raw = _CURSOR_FIELD_SEPARATOR.join(
        (moment.isoformat(), source_id, job_id)
    )
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_job_cursor(raw: str) -> JobCursor:
    """Decode a cursor produced by :func:`encode_job_cursor`.

    :raises InvalidCursorError: on any malformed input — over-long, non-base64url,
        non-UTF-8, wrong field count, unparseable/naive timestamp, or a
        ``source_id`` outside the controlled vocabulary's shape.
    """
    if not raw:
        raise InvalidCursorError("cursor must not be empty")
    if len(raw) > MAX_CURSOR_LENGTH:
        raise InvalidCursorError(
            f"cursor must be at most {MAX_CURSOR_LENGTH} characters"
        )
    # Re-add the padding stripped by encode_job_cursor. Tolerates a caller that
    # echoed back a padded variant, since '=' is legal in a query-string value.
    padded = raw + "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError):
        raise InvalidCursorError("cursor is not valid base64url") from None
    try:
        text = decoded.decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidCursorError("cursor does not decode to UTF-8 text") from None

    # maxsplit=2: the trailing ``id`` is an OPAQUE ATS-assigned string and may
    # legitimately contain the separator, while the two leading fields cannot (an
    # ISO-8601 instant has no '|', and source_id is validated against
    # _SOURCE_ID_RE below). Splitting greedily instead would make a job whose id
    # contains '|' un-pageable — a per-row cliff in the middle of a walk.
    parts = text.split(_CURSOR_FIELD_SEPARATOR, 2)
    if len(parts) != 3:
        raise InvalidCursorError(
            f"cursor must decode to 3 '{_CURSOR_FIELD_SEPARATOR}'-separated fields "
            f"(first_seen_at, source_id, id); got {len(parts)}"
        )
    timestamp_text, source_id, job_id = parts

    try:
        first_seen_at = parse_utc_timestamp(timestamp_text, field="cursor first_seen_at")
    except ValueError as exc:
        raise InvalidCursorError(str(exc)) from None
    if not _SOURCE_ID_RE.match(source_id):
        raise InvalidCursorError(f"cursor carries an invalid source_id: {source_id!r}")
    if not job_id:
        raise InvalidCursorError("cursor carries an empty id")

    return JobCursor(first_seen_at=first_seen_at, source_id=source_id, job_id=job_id)
