"""The one place a provider-supplied posting date is turned into a real date.

POSTED-DATE-PLAN.md §5/U1. Every source — the six backend ATS clients, the four
script scrapers, the recipe path — hands us a "posted date" in whatever shape its
board felt like emitting: an ISO string, a bare ``YYYY-MM-DD``, unix seconds,
unix milliseconds, an empty string, or English prose. This module is the single
answer to "is that a date, and which one".

**D5 is parse-safety, nothing more.** The window here rejects what *cannot* be a
date — an unparseable value, and a date so far in the future that it is a clock
bug or a corrupt field rather than a posting. It is deliberately **not** a
staleness judgement: a per-row "too old" rule (the credibility ceiling) was
considered and DELETED from the plan (D12). A board that stamps a 2009 date on a
job it re-listed today is publishing a wrong date, and we pass it through —
that is their data being wrong, not ours. Do not add an age floor here.

**Never synthesize.** An unparseable value returns ``None``, never ``now()``.
The caller decides what a missing date means; conflating "the board said nothing"
with "the board said today" is how a day-one spike gets baked into the graph.

**Never raises.** This runs inside the same task as the close sweep, where an
exception is not a bad date — it is an aborted harvest and a mass closure
(``docs/incidents/2026-03-29-mass-job-closure.md``). Degradation is per-row.

Why this file lives under ``scripts/shared/`` and not next to its sibling
consumers in ``src/backend/api/services/``: the deployed image copies
``src/backend/api/`` to ``/app/api`` and ``scripts/`` to ``/app/scripts``, so the
backend can import ``scripts.shared.*`` under one name everywhere while the
reverse import has no name that resolves both in the container and in a local
checkout. ``api/services/posted_date.py`` re-exports this module for the backend
side; there is exactly one implementation, and it is this one.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# How far into the future a posting date may sit and still be believed.
#
# Boards stamp dates in their own timezone, sometimes at day granularity, and a
# scraper can run minutes before a board's midnight — so "tomorrow" is routine
# and rejecting it would throw away good dates. A week is comfortably past any
# timezone/rounding artifact while still catching the failure this guards: a
# field that is not a posting date at all (an expiry, a "valid through", a
# fabricated epoch) landing in the sort key that decides what users see first.
#
# It matches the future half of the window the custom path already ships
# (``fetch_custom_company._validated_posted_on``, ``[now-365d, now+7d]``). The
# past half is deliberately NOT reproduced here — see the D5 note above.
FUTURE_SKEW_ALLOWANCE = timedelta(days=7)

# Above this, a numeric timestamp is milliseconds, not seconds. 1e11 seconds is
# the year 5138, so nothing that is genuinely seconds can reach it, and anything
# in real millisecond range (1.7e12 today) clears it easily. Mirrors the guard
# ``eightfold_client._parse_eightfold_epoch`` has carried since it shipped
# (``eightfold_client.py:536-539``) — same constant, same reasoning, one place.
_EPOCH_MS_THRESHOLD = 1e11


def parse_posted_date(
    value: Any, *, now: Optional[datetime] = None
) -> Optional[datetime]:
    """``value`` as a timezone-aware UTC ``datetime``, or ``None``.

    Accepts an ISO-8601 string (``Z`` or offset suffix, or none at all), a bare
    ``YYYY-MM-DD``, a ``datetime``, or unix epoch seconds/milliseconds as a
    number or a numeric string. A naive value is READ AS UTC — every producer in
    this repo normalizes to UTC before storing, so guessing a local zone here
    would silently shift dates by the runner's offset.

    Returns ``None`` — never a substituted "now" — for anything unparseable,
    empty, non-positive as an epoch, or dated more than
    ``FUTURE_SKEW_ALLOWANCE`` beyond ``now``.

    :param now: reference instant for the future check; defaults to the real
        clock. Pass it in tests so the window is deterministic.
    """
    parsed = _to_datetime(value)
    if parsed is None:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)

    reference = now if now is not None else datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)

    if parsed > reference.astimezone(timezone.utc) + FUTURE_SKEW_ALLOWANCE:
        return None
    return parsed


def effective_posted_date(
    value: Any, fallback: str, *, now: Optional[datetime] = None
) -> str:
    """The provider's date as a UTC ISO string, or ``fallback`` when there isn't one.

    This is the write-side rule from POSTED-DATE-PLAN.md §2 in one call:
    ``first_seen_at`` is the provider's posting date when the provider gives us a
    real one, and the run timestamp otherwise. ``fallback`` is returned verbatim
    so the caller keeps whatever ISO shape the rest of its run uses.
    """
    parsed = parse_posted_date(value, now=now)
    return parsed.isoformat() if parsed is not None else fallback


def _to_datetime(value: Any) -> Optional[datetime]:
    """``value`` in whatever shape a board emitted, as a ``datetime`` or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    # bool before int: ``True`` is an int, and epoch 1 is 1970-01-01. A flag that
    # leaked into a date field is not a date.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _from_epoch(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # ISO first: a 10-character epoch string cannot be misread as a date
        # (``fromisoformat`` rejects it), but a date must never be read as an
        # epoch.
        return _from_iso(text) or _from_epoch(text)
    return None


def _from_iso(text: str) -> Optional[datetime]:
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _from_epoch(value: Any) -> Optional[datetime]:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric) or numeric <= 0:
        return None
    if numeric > _EPOCH_MS_THRESHOLD:
        numeric = numeric / 1000.0
    try:
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
