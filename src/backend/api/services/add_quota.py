"""The per-user monthly cap on ``POST /api/users/companies``.

**The rule.** 20 URLs per user per calendar month, resetting at midnight UTC on the
1st. Every submission we ACT on spends a slot — a success, a board we refused after
reading it, and a board that turns out to be one we already publish. Deleting a
company does **not** give one back.

**The one exception, and it is narrow.** A URL we could not read at all — refused by
``url_guard`` (``http://``, userinfo, an odd port, a bare IP, a private address) or
lost to DNS / a dead connection / a redirect loop — is refused *before* the resolver
has anything to say about a board, writes no ``company_add_attempts`` row, and
therefore costs nothing. That exception exists because the Add Companies page stopped
calling ``/api/companies/resolve`` for a free preview: with the preview gone, every
mistyped scheme lands on the add endpoint, and charging somebody 1/20 of their month
for a URL that cost us a DNS lookup is not "capping the input", it is a fine for a
typo. ``routers/user_companies``' ``unreachable`` branch is the whole implementation.

Three things about that rule are deliberate and were chosen over the alternatives:

* **URLs entered, not boards created.** Capping the input is easier to explain and
  easier to trust than capping "real spend", and it deletes a bug: a spend-based rule
  needs a dedupe so that an idempotent re-add does not overcount, and this one does
  not need any. ("Entered" means entered *at a board* — see the exception above.)
* **Calendar month, not a rolling 30-day window.** "It resets on the 1st" is a
  sentence a user can hold in their head. The midnight-double-burst risk that usually
  argues for a rolling window is not real here, because a slot costs a *click*, not a
  created board — 40 submissions across a month boundary are 40 cheap submissions,
  paced by the 10/60s burst limiter.
* **UTC.** So the reset is one instant for everybody rather than a per-user clock the
  server would have to know. On a US Central machine that is 7pm on the last day of
  the month, not local midnight.

**Where the count comes from.** ``company_add_attempts`` — the append-only audit that
the add endpoint already writes on every path, and that a company purge deliberately
leaves behind. That is what makes "no refund" real rather than a rule we have to
remember to enforce. See
:func:`custom_companies_service.count_add_attempts_since` for the one subtlety (the
worker writes a second row per discovered board, and it must not be billed).

**Every way this can be misconfigured fails CLOSED.** The number is simply the number
of adds allowed. ``0`` allows **none** — there is no sentinel value, because you
should not have to understand the business context to know what zero means. Two
misconfigurations, and neither one opens the gate:

* **A typo'd env var name.** ``Settings.model_config`` sets ``extra="ignore"``, so the
  name is silently dropped and the compiled-in default of 20 stands — the cap stays
  ON. An ``..._ENABLED=false``-shaped flag would fail OPEN on the same typo, which is
  why there isn't one.
* **A value that lands on 0** — a typo, a bad deploy template, an empty string coerced
  to an int. ``0`` USED TO MEAN UNLIMITED, so that accident silently handed every
  signed-in user unbounded browser + LLM spend. It now refuses every add instead. For
  a guard on money, refusing is the correct direction to fail.

``0`` is therefore also a real kill switch: one env var stops every add for everybody,
without a deploy. Local development buys its freedom with a large number
(``CUSTOM_COMPANY_MONTHLY_ADD_LIMIT=10000`` in ``.env.local``), never with a sentinel.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import NamedTuple

from psycopg2.extensions import connection as Connection

from ..config import settings
from . import custom_companies_service as svc

logger = logging.getLogger(__name__)

# The machine-readable ``reason`` the add endpoint returns when the cap is hit.
# 422 and NOT 403: the frontend's ``asAddFailure`` hard-checks ``status !== 422``
# before it will read a ``reason``, so a 403 would fall through to the generic
# "we couldn't add that company" copy and lose the explanation entirely.
MONTHLY_LIMIT_REASON = "monthly_limit_reached"


class AddQuota(NamedTuple):
    """One user's add allowance for the current UTC calendar month.

    ``limit`` is the configured cap and means exactly what it says: the number of adds
    allowed this month. ``0`` allows none — it is a kill switch, not "unlimited".
    ``used`` is reported alongside it because it costs one query we are making anyway,
    and it is the number an operator wants when deciding what the limit should be.
    """

    used: int
    limit: int
    resets_at: datetime

    @property
    def exhausted(self) -> bool:
        """Whether the next submission must be refused.

        ``>=``, not ``>``: ``used`` counts submissions already made, so at
        ``used == limit`` the allowance is spent and the NEXT one is the 21st. That
        same comparison is the whole implementation at ``limit == 0``, where a fresh
        user is already at ``0 >= 0`` and every add is refused — no branch, no
        sentinel, and nothing to get wrong when someone reads this in a year.

        There is deliberately no ``remaining`` here. The server never needs it — the
        only server-side question is this one — and the counter's arithmetic lives in
        exactly one place, ``addsRemaining`` in the frontend. A second definition on
        this side would be a second thing that can disagree with the number the user
        is reading.
        """
        return self.used >= self.limit


def month_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """``(start_of_this_UTC_month, start_of_next_UTC_month)``.

    ``now`` is injectable so the month-rollover tests do not have to wait for one.
    A naive ``now`` is rejected rather than assumed-UTC: the whole point of this
    function is that the boundary is an unambiguous instant, and silently adopting
    the server's local timezone is exactly how that stops being true.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("month_window requires a timezone-aware datetime")
    now = now.astimezone(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # December rolls to January of the next year; every other month just increments.
    if start.month == 12:
        nxt = start.replace(year=start.year + 1, month=1)
    else:
        nxt = start.replace(month=start.month + 1)
    return start, nxt


def get_quota(
    conn: Connection, user_id: str, *, now: datetime | None = None
) -> AddQuota:
    """The caller's allowance right now. Reads only — never writes.

    ONE function behind both consumers: the enforcement check in ``add_company`` and
    the counter on ``GET /api/users/companies``. Two implementations of "how many are
    left" would eventually disagree, and the disagreement a user would see is a
    counter reading "3 adds left" above a refusal.
    """
    start, nxt = month_window(now)
    used = svc.count_add_attempts_since(conn, user_id, start)
    return AddQuota(
        used=used, limit=settings.custom_company_monthly_add_limit, resets_at=nxt
    )


def get_quota_for_new_user(*, now: datetime | None = None) -> AddQuota:
    """The allowance of a caller who has no ``users`` row yet — a full month.

    A separate function rather than ``AddQuota(0, limit, ...)`` inline at the call
    site, so the "no row means nothing spent" reasoning is stated once and the limit
    is still read from settings rather than assumed.
    """
    _, nxt = month_window(now)
    return AddQuota(
        used=0, limit=settings.custom_company_monthly_add_limit, resets_at=nxt
    )


def limit_reached_detail(quota: AddQuota) -> str:
    """The sentence the user reads when the cap refuses their submission.

    Names the number and the reset date, because "you've hit your limit" with neither
    leaves the reader with nothing to do and no idea when that changes.
    """
    # ``limit == 0`` is the kill switch, not an allowance somebody spent, and
    # "you've used all 0 of your company adds" is nonsense aimed at the one reader
    # who most needs a straight answer. This is a COPY branch, not a second meaning
    # for zero: ``exhausted`` still has no idea the case exists.
    if quota.limit == 0:
        return "Adding companies is turned off right now. Please try again later."
    # ``day`` + ``%B`` rather than ``%-d %B``: the no-pad flag is a platform
    # extension (fine on glibc and BSD, absent on Windows), and this is an error
    # path — the last place that should be able to raise on a formatting flag.
    return (
        f"You've used all {quota.limit} of your company adds for this month. "
        f"Your next {quota.limit} become available on "
        f"{quota.resets_at.day} {quota.resets_at.strftime('%B')}."
    )


def warn_if_adds_disabled() -> None:
    """Emit a single WARNING at startup when the cap is 0 and no add can succeed.

    KEPT, but inverted. This used to warn that the gate was WIDE OPEN, because ``0``
    meant unlimited; that reason is gone with the sentinel. The reason to keep a
    startup line is that ``0`` is still an extreme state — every add returns 422, for
    every user — and it is reachable both deliberately (the kill switch) and by
    accident (a typo'd value, an empty string coerced to an int). From the outside
    either one looks like a broken feature, and "the endpoint is off" belongs in the
    boot log rather than in a bug report a week later.

    Called from the FastAPI lifespan, exactly like ``auth.internal_key.warn_if_unset``.
    """
    if settings.custom_company_monthly_add_limit == 0:
        logger.warning(
            "CUSTOM_COMPANY_MONTHLY_ADD_LIMIT is 0 — NO user can add a company; "
            "every POST /api/users/companies is refused with 422. That is the "
            "deliberate kill switch, but it is also what a misconfigured value looks "
            "like. For local development set a large number (e.g. 10000), not 0."
        )
