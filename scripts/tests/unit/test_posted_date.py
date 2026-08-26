"""Unit tests for the shared provider-date parser (shared/posted_date.py).

POSTED-DATE-PLAN.md §5/U1. This module decides what the whole product treats as a
posting date, so the tests below pin the two properties that make it safe to put
in the close-sweep task: it NEVER substitutes ``now()`` for a value it could not
read, and it NEVER raises.

D5 is parse-safety only. There is deliberately no test for "too old" — a per-row
age floor (the credibility ceiling) was DELETED from the plan by D12. A test that
pinned one would be pinning a decision the owner reversed.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.posted_date import (
    FUTURE_SKEW_ALLOWANCE,
    effective_posted_date,
    parse_posted_date,
)

NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)

# 2026-08-25T00:31:21Z as unix seconds, and the same instant as milliseconds.
EPOCH_S_2026 = 1787617881
EPOCH_MS_2026 = 1787617881000


class TestUnparseableNeverBecomesNow:
    """The single most important property: a bad value is None, not today."""

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "   ",
            "Posted 30+ Days Ago",
            "2 days ago",
            "about 12 hours",
            "yesterday",
            "not-a-date",
            "2026-13-45",
            [],
            {},
            object(),
            True,       # a bool is an int; epoch 1 is 1970, not a posting date
            False,
            0,
            -1,
            float("nan"),
            float("inf"),
        ],
    )
    def test_unreadable_value_returns_none(self, value):
        assert parse_posted_date(value, now=NOW) is None

    def test_unparseable_never_returns_something_near_now(self):
        """Regression guard for the failure this module exists to prevent.

        Silently falling back to ``now()`` inside the parser is invisible: every
        row gets a plausible date and the day-one spike looks like real hiring.
        The caller must be the one that decides what a missing date means.
        """
        result = parse_posted_date("Posted 30+ Days Ago", now=NOW)
        assert result is None, f"parser synthesized a date: {result}"

    def test_a_rejected_value_never_raises(self):
        """Per-row degradation, never a per-run abort.

        This runs in the same task as the close sweep — an exception here is not
        a bad date, it is an aborted harvest and a mass closure
        (docs/incidents/2026-03-29-mass-job-closure.md).
        """
        for hostile in [
            object(),
            b"\xff\xfe",
            {"posted": "today"},
            ["2026-01-01"],
            "9" * 400,
            "-" * 40,
            float("-inf"),
            10**400,        # int too large for float()
        ]:
            assert parse_posted_date(hostile, now=NOW) is None

    @pytest.mark.parametrize(
        "edge",
        [
            "9999-12-31T23:59:59-14:00",   # the far end, pushed past datetime.max
            "0001-01-01T00:00:00+14:00",   # the near end, pushed before datetime.min
        ],
    )
    def test_a_datetime_at_the_edge_of_representable_time_returns_none(self, edge):
        """THE hole in "never raises", and it was not in the parsing.

        ``_to_datetime`` is fully guarded, so every test above exercises a value that
        fails to PARSE. These two parse perfectly — and then raise ``OverflowError`` on
        the ``astimezone(utc)`` conversion that follows, because the offset carries them
        past ``datetime.max`` / before ``datetime.min``. The docstring said the function
        never raises; the code said otherwise, and one of them had to change.

        Bounded, but not harmlessly: inside ``batch_writer.add_job`` it degrades a row,
        and everywhere else it fails the whole task — which harvests nothing and closes
        nothing. "Unreadable" is the honest answer for a date at the end of time.
        """
        assert parse_posted_date(edge, now=NOW) is None

    def test_a_reference_clock_at_the_edge_does_not_reject_a_good_date(self):
        """The other side of the same arithmetic: ``reference + FUTURE_SKEW_ALLOWANCE``
        overflows too when ``now`` is ``datetime.max``. Catching that must not turn a
        perfectly ordinary 2026 date into a NULL — nothing can be beyond the last
        representable instant, so the horizon clamps instead of rejecting."""
        result = parse_posted_date(
            "2026-01-01T00:00:00Z", now=datetime.max.replace(tzinfo=timezone.utc)
        )
        assert result is not None and result.year == 2026


class TestFutureWindow:
    """Rejects what cannot be a posting date. Not a staleness rule (D5/D12)."""

    def test_thirty_days_in_the_future_is_rejected(self):
        assert parse_posted_date((NOW + timedelta(days=30)).isoformat(), now=NOW) is None

    def test_three_days_in_the_future_survives(self):
        """Board timezones and day-granularity stamps routinely read as tomorrow."""
        soon = NOW + timedelta(days=3)
        assert parse_posted_date(soon.isoformat(), now=NOW) == soon

    def test_the_allowance_boundary_is_inclusive(self):
        edge = NOW + FUTURE_SKEW_ALLOWANCE
        assert parse_posted_date(edge.isoformat(), now=NOW) == edge
        assert parse_posted_date(
            (edge + timedelta(seconds=1)).isoformat(), now=NOW
        ) is None

    def test_no_age_floor_exists(self):
        """D12: a board that re-lists a 2009 job publishes a 2009 date, and we
        pass it through. A per-row 'too old' rule was deleted from the plan."""
        ancient = datetime(2009, 4, 1, tzinfo=timezone.utc)
        assert parse_posted_date("2009-04-01T00:00:00Z", now=NOW) == ancient


class TestTimezoneHandling:
    def test_naive_timestamp_is_read_as_utc(self):
        """Not as the runner's local zone — every producer here stores UTC, and
        guessing local would shift dates by whatever offset the box happens to
        have (the same class of bug as the Postgres MCP timezone trap)."""
        assert parse_posted_date("2026-08-01T09:30:00", now=NOW) == datetime(
            2026, 8, 1, 9, 30, tzinfo=timezone.utc
        )

    def test_naive_date_only_is_read_as_utc_midnight(self):
        assert parse_posted_date("2026-08-08", now=NOW) == datetime(
            2026, 8, 8, 0, 0, tzinfo=timezone.utc
        )

    def test_z_suffix_parses(self):
        assert parse_posted_date("2026-08-01T09:30:00Z", now=NOW) == datetime(
            2026, 8, 1, 9, 30, tzinfo=timezone.utc
        )

    def test_offset_is_converted_to_utc(self):
        assert parse_posted_date("2026-08-01T09:30:00-05:00", now=NOW) == datetime(
            2026, 8, 1, 14, 30, tzinfo=timezone.utc
        )

    def test_result_is_always_timezone_aware(self):
        for value in ["2026-08-08", "2026-08-08T00:00:00", EPOCH_S_2026]:
            assert parse_posted_date(value, now=NOW).tzinfo is not None


class TestEpochInput:
    """``>1e11 -> /1000``, mirroring eightfold_client.py:536-539."""

    def test_epoch_seconds_land_in_2026(self):
        assert parse_posted_date(EPOCH_S_2026, now=NOW).year == 2026

    def test_epoch_milliseconds_land_in_2026_not_year_58000(self):
        """Without the ms guard this is year 58,626 — which the future window
        would then reject, silently turning every row of a ms-emitting board
        into a NULL date."""
        assert parse_posted_date(EPOCH_MS_2026, now=NOW).year == 2026

    def test_seconds_and_milliseconds_agree_to_the_second(self):
        assert parse_posted_date(EPOCH_S_2026, now=NOW) == parse_posted_date(
            EPOCH_MS_2026, now=NOW
        )

    def test_numeric_strings_are_read_as_epochs(self):
        assert parse_posted_date(str(EPOCH_S_2026), now=NOW).year == 2026
        assert parse_posted_date(str(EPOCH_MS_2026), now=NOW).year == 2026

    def test_epoch_zero_is_not_a_date(self):
        """1970-01-01 is what an empty/absent field coerces to, not a posting."""
        assert parse_posted_date(0, now=NOW) is None

    def test_an_iso_date_is_never_misread_as_an_epoch(self):
        assert parse_posted_date("20260808", now=NOW) == datetime(
            2026, 8, 8, tzinfo=timezone.utc
        )


class TestEffectivePostedDate:
    """The write-side rule in one call (POSTED-DATE-PLAN.md §2)."""

    FALLBACK = "2026-08-26T12:00:00Z"

    def test_real_provider_date_wins(self):
        assert effective_posted_date("2026-08-08", self.FALLBACK, now=NOW) == (
            "2026-08-08T00:00:00+00:00"
        )

    def test_missing_provider_date_falls_back_verbatim(self):
        assert effective_posted_date(None, self.FALLBACK, now=NOW) == self.FALLBACK

    def test_unparseable_provider_date_falls_back_not_forward(self):
        assert (
            effective_posted_date("Posted 30+ Days Ago", self.FALLBACK, now=NOW)
            == self.FALLBACK
        )

    def test_future_provider_date_falls_back(self):
        far = (NOW + timedelta(days=400)).isoformat()
        assert effective_posted_date(far, self.FALLBACK, now=NOW) == self.FALLBACK

    def test_return_value_is_never_empty(self):
        """first_seen_at is NOT NULL in the schema — this function is the last
        thing standing between a junk provider value and a failed INSERT."""
        for value in [None, "", "garbage", 0, object()]:
            assert effective_posted_date(value, self.FALLBACK, now=NOW)
