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

**Admins are exempt from the cap — and only from the cap.** An admin grant is a row in
``admins``, the same concept ``auth.dependencies.require_admin`` reads, keyed by email
via :func:`admin_service.is_admin_by_email`. The exemption lives HERE, inside
:func:`get_quota`, and not at the call site in ``routers/user_companies.add_company``,
because this function is the one thing both the enforcement check and the counter read.
An exemption applied at the call site would refuse nothing while the counter above the
form still counted down to "0 of 20 adds left" — the exact disagreement this module is
built as one function to prevent.

Three things the exemption is NOT:

* **Not a bypass of the burst limiter.** ``enforce_user_company_add_rate_limit`` (10 per
  60s) is an abuse guard, not a budget: an admin hammering the endpoint is still
  hammering somebody's live job board, and 10/minute has never been what blocks real
  work. It stays on for everybody.
* **Not exemption from the audit.** An admin's add writes its ``company_add_attempts``
  row exactly like anybody else's, so ``used`` keeps counting up (it is simply never
  compared against ``limit``) and the admin dashboard still sees every add.
* **Not a way to fail open.** The lookup is a database read, and a database read can
  fail. :func:`is_exempt_from_cap` catches everything and answers **False** — an error
  makes the caller an ordinary user and the cap applies. That direction is not
  negotiable for a guard on money: it is the same fail-open shape that ``0``-means-
  unlimited used to be.

**What an exempt caller SEES** is no counter at all. :func:`quota_response` returns
``None``, the ``quota`` block is absent from ``GET /api/users/companies``, and
``addsRemaining`` in the frontend already answers ``null`` to that — which renders no
line and disables no button. That is the existing "no cap in force" vehicle, reused
rather than duplicated; it is deliberately NOT ``limit: 0``, which means the opposite
(a cap in force that allows nothing).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import NamedTuple

from psycopg2.extensions import connection as Connection

from ..config import settings
from ..models import AddQuotaResponse
from . import custom_companies_service as svc
from .admin_service import is_admin_by_email

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

    ``exempt`` is the admin exemption (see the module docstring). It changes ONE thing:
    :attr:`exhausted`. ``used`` and ``limit`` stay exactly what they are for everybody
    else — an admin's adds are still recorded and still counted, they are simply never
    compared against the cap — so an operator reading a log line or the dashboard sees
    real numbers rather than a hole.
    """

    used: int
    limit: int
    resets_at: datetime
    # Defaulted so the two constructions in this module are the only places that ever
    # decide it. False is the safe value, which is the right default for a spend guard.
    exempt: bool = False

    @property
    def over_limit(self) -> bool:
        """Whether the allowance is spent, ignoring any exemption.

        ``>=``, not ``>``: ``used`` counts submissions already made, so at
        ``used == limit`` the allowance is spent and the NEXT one is the 21st. That
        same comparison is the whole implementation at ``limit == 0``, where a fresh
        user is already at ``0 >= 0`` and every add is refused — no branch, no
        sentinel, and nothing to get wrong when someone reads this in a year.

        Split out from :attr:`exhausted` for exactly one caller: the add endpoint logs
        "the cap would have refused this, and did not, because you are an admin". A
        second inline ``used >= limit`` at that call site is the kind of duplicate this
        module exists to avoid.
        """
        return self.used >= self.limit

    @property
    def exhausted(self) -> bool:
        """Whether the next submission must be refused. THE server-side question.

        An exempt caller is never refused for the cap — that is the whole exemption,
        and it is one line here rather than a branch at the call site so that no future
        caller of this function can forget it.

        There is deliberately no ``remaining`` here. The server never needs it — the
        only server-side question is this one — and the counter's arithmetic lives in
        exactly one place, ``addsRemaining`` in the frontend. A second definition on
        this side would be a second thing that can disagree with the number the user
        is reading.
        """
        return not self.exempt and self.over_limit


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


def is_exempt_from_cap(conn: Connection, email: str | None) -> bool:
    """Whether this caller is exempt from the monthly cap. **Fails CLOSED.**

    One question, one source of truth: a row in ``admins``, read through
    :func:`admin_service.is_admin_by_email` — the same function
    ``auth.dependencies.require_admin`` uses, keyed by email for the same reason
    (it is the stable identifier across provider switches). No second admin concept.

    Every unhappy answer is **False**, i.e. "apply the cap":

    * **No email on the token.** The routers 401 before they get here, so this is
      belt-and-braces; a caller we cannot identify is not an admin.
    * **The lookup raised.** A dead connection, a lock timeout, an aborted
      transaction — anything. A database error must never become an exemption from a
      spend guard: an outage would silently uncap every user, which is precisely the
      fail-open shape that ``0``-means-unlimited used to be. We log it loudly (the
      admin still gets refused at 20, which is a bug worth seeing in the log) and
      apply the cap.

    ONE extra indexed ``EXISTS`` per call, and the list endpoint is polled (every 15s,
    4s while a discovery runs). That is the price of the counter and the refusal being
    decided by the same value; a cached answer would be a second place the two could
    disagree, and it would take an admin grant minutes to take effect.

    The ``rollback`` is not incidental. psycopg2 leaves the transaction in an aborted
    state after a failed statement, and every subsequent statement on that connection
    fails with ``InFailedSqlTransaction`` — including the ``count_add_attempts_since``
    immediately below, which would turn a survivable admin-lookup blip into a 500 on
    the whole endpoint. Rolling back is safe because this path is read-only and both
    callers reach it before they have written anything they need to keep.
    """
    if not email:
        return False
    try:
        return is_admin_by_email(conn, email)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            # A connection too broken to roll back is a connection the count below
            # cannot use either; that raises, and the router answers 500. Still
            # closed — a 500 refuses the add.
            logger.exception("Rollback failed after an admin-status lookup error")
        logger.exception(
            "Admin-status lookup failed for %s — applying the monthly add cap "
            "(failing CLOSED)", email,
        )
        return False


def get_quota(
    conn: Connection, user_id: str, *, email: str | None, now: datetime | None = None
) -> AddQuota:
    """The caller's allowance right now. Reads only — never writes.

    ONE function behind both consumers: the enforcement check in ``add_company`` and
    the counter on ``GET /api/users/companies``. Two implementations of "how many are
    left" would eventually disagree, and the disagreement a user would see is a
    counter reading "3 adds left" above a refusal. The admin exemption is resolved
    here, inside that one function, for exactly the same reason.

    ``email`` is a REQUIRED keyword argument, deliberately without a default. A caller
    that forgets it is a ``TypeError`` at the call site rather than a silently
    cap-enforcing admin — the failure mode of an optional parameter on a check like
    this is that it quietly stops being applied.
    """
    start, nxt = month_window(now)
    exempt = is_exempt_from_cap(conn, email)
    used = svc.count_add_attempts_since(conn, user_id, start)
    return AddQuota(
        used=used,
        limit=settings.custom_company_monthly_add_limit,
        resets_at=nxt,
        exempt=exempt,
    )


def get_quota_for_new_user(*, now: datetime | None = None) -> AddQuota:
    """The allowance of a caller who has no ``users`` row yet — a full month.

    A separate function rather than ``AddQuota(0, limit, ...)`` inline at the call
    site, so the "no row means nothing spent" reasoning is stated once and the limit
    is still read from settings rather than assumed.

    Never exempt, and it needs no lookup to say so: ``admins.user_id`` is a foreign key
    to ``users.id``, so a caller with no ``users`` row cannot have an admin grant. The
    first thing an admin's very first add does is create that row, and the quota read
    that follows it goes through :func:`get_quota`.
    """
    _, nxt = month_window(now)
    return AddQuota(
        used=0, limit=settings.custom_company_monthly_add_limit, resets_at=nxt
    )


def quota_response(quota: AddQuota) -> AddQuotaResponse | None:
    """The ``quota`` block for ``GET /api/users/companies`` — or ``None`` if exempt.

    THE OTHER HALF OF THE EXEMPTION, and it lives next to :attr:`AddQuota.exhausted`
    on purpose: what the server enforces and what the counter shows are decided by one
    module, from one value, so they cannot drift apart.

    ``None`` (the block absent from the payload) is the frontend's EXISTING "no cap in
    force" case — ``addsRemaining`` already answers ``null`` to a missing quota, which
    renders no counter and disables no button. Reusing it means an exempt caller needs
    no new field, no new wire concept, and no frontend change. It is emphatically not
    ``limit: 0``, which is a cap that IS in force and allows nothing.
    """
    if quota.exempt:
        return None
    return AddQuotaResponse(
        used=quota.used, limit=quota.limit, resets_at=quota.resets_at
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
