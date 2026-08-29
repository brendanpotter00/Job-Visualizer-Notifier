"""Data access for custom (user-added, private) companies — E7 Phase 1.

Shared by the ``/api/users/companies`` endpoints and the ``custom_ats_fetch``
worker. Every custom company is ``visibility='user'`` and owned by one or more
users via ``user_companies``; its jobs live under the per-company
``source_id = custom:<id>`` namespace so the database enforces cross-company
isolation on every destructive lifecycle write.

None of these helpers touch the six public ATS fan-outs or the public read
paths — those are guarded separately (see the visibility-leak fixes).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import psycopg2
from psycopg2.extensions import connection as Connection

from scripts.shared.constants import custom, new_custom_company_id
from .careers_host_match import match_any_careers_url
from .company_name_match import build_name_index, match_name_in_any_url
from .discovery.progress import initial_snapshot, with_first_scan
from .pending_jobs import cancel_queued_jobs

logger = logging.getLogger(__name__)

# How often a custom company is re-harvested. next_run_at is seeded to now() so the row
# is DUE the instant it exists. The add path then enqueues the first harvest itself
# (``claim_custom_companies.start_first_harvest``) and pushes next_run_at forward; the
# seeded-due state is what the 15-minute claim tick falls back to when that enqueue
# could not happen.
#
# ONE HOUR, matching the published fleet as closely as an INTEGER column can. Every
# public board is re-read every 30 minutes (``enqueue_*_fan_out``, all six on
# ``*/30 * * * *``); ``cadence_hours`` cannot express 30 minutes, and 0.25 h ("every
# 15 minutes") is both unrepresentable and shorter than one harvest's own timeout
# (``fetch_custom_company._TASK_TIMEOUT_S`` = 900 s), so 1 h is the nearest legal value
# and it errs slow. The old 24 h was chosen when a harvest meant a Browserbase browser
# session; a stored board now replays as one ``http_json`` / ``ats_client`` request.
#
# Read ``claim_custom_companies._JITTER_FRACTION`` before changing this: the jitter is a
# fraction of THIS number, precisely so a shorter cadence cannot push ``next_run_at``
# into the past.
DEFAULT_CADENCE_HOURS = 1
# Bounded retry on the astronomically-unlikely companies.id PK collision.
_ID_GENERATION_ATTEMPTS = 5


def canonical_source_key(ats: str, board_token: str) -> str:
    """The idempotency key for ``UNIQUE(user_id, canonical_source_key)``."""
    return f"{ats}:{board_token}"


def find_owned_company_by_source_key(
    conn: Connection, user_id: str, source_key: str
) -> Optional[dict[str, Any]]:
    """The caller's company for ``source_key`` (idempotent re-add), or None."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.id, c.display_name, c.ats, c.board_token, c.health_state,
               c.last_success_at, c.tracking_started_at, c.created_at,
               c.provider_config
        FROM user_companies uc
        JOIN companies c ON c.id = uc.company_id
        WHERE uc.user_id = %s AND uc.canonical_source_key = %s
        """,
        (user_id, source_key),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def find_public_company_for_candidate(
    conn: Connection,
    *,
    ats: str,
    board_token: str,
    provider_config: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """The ENABLED public company that IS this board, or None (the P2 dedupe).

    One SELECT against the ~130 ``visibility='public'`` rows, run on the add path
    before anything is created. A hit means the user pasted a board we already
    publish to everybody — Spotify's Lever board, Netflix's Eightfold tenant — and
    the right answer is to point at that page rather than scrape a private second
    copy of it.

    Returns ``{id, display_name}``. Both are already public, unauthenticated data
    (``GET /api/companies`` serves every enabled row's id and display name), so a
    hit discloses nothing the caller could not already read.

    **Matching is per-ATS, and a naive ``(ats, board_token)`` equality would be
    wrong for two of the six.** Checked against the 129 public rows:

    * **Workday** — ``board_token`` on a public row is OUR internal company id
      (``gm``, ``slack``), not the tenant the resolver emits (``generalmotors``,
      ``salesforce``). All 11 rows would miss. The identity lives in
      ``provider_config``, so match ``tenant_slug`` AND ``career_site_slug``:
      ``salesforce`` hosts both ``/Slack`` and other career sites, and matching on
      the tenant alone would answer a Salesforce URL with "we already track Slack".
    * **Ashby** — 8 public rows store a mixed-case token (``Sierra``, ``Linear``,
      ``GigaML``) while the resolver lowercases every Ashby token, so those 8 would
      miss on ``=``. ``lower()`` on both sides fixes it and is a no-op for the
      Greenhouse / Lever / Gem rows, which are all lowercase already — no two
      public boards differ only by case, so it cannot create a false hit.
    * **Eightfold** — matched on ``provider_config->>'domain'``, which is the
      actual tenant key. ``board_token`` there is the domain's first label and is
      documented as cosmetic; comparing the real key costs the same SELECT.

    ``ats='script'`` (Amazon, Apple, Google, Microsoft, TikTok) is deliberately
    unreachable here: the resolver never emits it, so those five can never be
    deduped this way. :func:`find_public_company_for_careers_url` is the other
    half that catches them, by host.
    """
    if ats == "workday":
        tenant_slug = provider_config.get("tenant_slug")
        career_site_slug = provider_config.get("career_site_slug")
        if not tenant_slug or not career_site_slug:
            # A Workday candidate always carries both. Without them there is no
            # identity to compare, and guessing one is how a user gets pointed at
            # a different company's chart.
            return None
        predicate = (
            "provider_config->>'tenant_slug' = %s "
            "AND provider_config->>'career_site_slug' = %s"
        )
        params: tuple[Any, ...] = (tenant_slug, career_site_slug)
    elif ats == "eightfold":
        domain = provider_config.get("domain")
        if not domain:
            return None
        predicate = "provider_config->>'domain' = %s"
        params = (domain,)
    else:
        predicate = "lower(board_token) = lower(%s)"
        params = (board_token,)

    cursor = conn.cursor()
    cursor.execute(
        # ``enabled`` is part of the match, not an afterthought: a disabled public
        # row is a board we have STOPPED reading, and sending someone to a chart
        # that no longer updates is worse than letting them track their own copy.
        #
        # ``predicate`` is a literal from the branches above — never user input —
        # and every compared VALUE is still a bound parameter.
        f"""
        SELECT id, display_name
        FROM companies
        WHERE visibility = 'public' AND enabled AND ats = %s AND {predicate}
        LIMIT 1
        """,
        (ats,) + params,
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def find_public_company_for_careers_url(
    conn: Connection, *urls: Optional[str]
) -> Optional[dict[str, Any]]:
    """The ENABLED public company whose careers board these URLs are, or None.

    The other half of the dedupe, and the half that closes the gap the owner hit.
    :func:`find_public_company_for_candidate` keys on the ``(ats, board_token)``
    pair the ATS resolver emits; the five ``ats='script'`` boards — Amazon, Apple,
    Google, Microsoft, TikTok — have no such pair, so pasting
    ``jobs.careers.microsoft.com`` used to reach one-time discovery and build a
    private duplicate of a board we already publish. This matches the HOST instead.

    Two arguments in the split, deliberately. :mod:`api.services.careers_host_match`
    is a PURE table lookup and answers with a company **id**; this function is the
    only part that touches the database, and it asks the same two questions unit 9
    asks — ``visibility = 'public'`` and ``enabled``. Neither is decoration:

    * ``visibility``, because a private row must never be offered as the answer to
      another user (unit 9 has a test for exactly that leak), and
    * ``enabled``, because a disabled public row is a board we have STOPPED reading
      and pointing somebody at a chart that no longer updates is worse than letting
      them track their own copy.

    Deliberately NOT filtered on ``ats = 'script'``. The declared table maps a host
    to a company, and a company that later migrates off its bespoke scraper onto a
    real ATS is still the company that host belongs to — an ``ats`` filter would
    silently stop matching on the deploy that moved it.

    Returns ``{id, display_name}``, the same shape unit 9 returns, so the caller and
    the ``AlreadyPublicResponse`` it builds do not care which half answered. Both
    fields are already public, unauthenticated data (``GET /api/companies`` serves
    every enabled row's id and display name), so a hit discloses nothing.
    """
    company_id = match_any_careers_url(*urls)
    if company_id is None:
        return None

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, display_name
        FROM companies
        WHERE id = %s AND visibility = 'public' AND enabled
        """,
        (company_id,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def find_public_company_by_name(
    conn: Connection, *urls: Optional[str]
) -> Optional[dict[str, Any]]:
    """The ENABLED public company these URLs' domain appears to NAME, or None.

    The third rung of the dedupe ladder, and the only one that is a guess. The two
    above it answer with an exact identifier — a resolved ``(ats, board_token)`` pair
    and a declared careers host — and between them they still let ``lifeatspotify.com``
    through to a full one-time discovery, because Spotify's own site is neither. The
    string ``spotify`` was in the domain the whole time.

    Same two-part split the careers-host check uses, for the same reason:
    :mod:`api.services.company_name_match` is PURE (no IO, exhaustively testable) and
    answers with a company **id**; this function is the only part that touches the
    database. It asks the same two questions both rungs above ask —
    ``visibility = 'public'`` and ``enabled`` — and neither is decoration:

    * ``visibility``, because a private row must never be offered as the answer to
      another user, and
    * ``enabled``, because a disabled public row is a board we have STOPPED reading,
      and pointing somebody at a chart that no longer updates is worse than letting
      them track their own copy.

    The SELECT is the whole published fleet (~133 rows, both columns already served
    unauthenticated by ``GET /api/companies``), because the match runs against the
    NAMES rather than a key an index could serve: there is no ``WHERE`` clause that
    expresses "the domain label is one of these strings wearing a careers affix". At
    this size that is a sub-millisecond scan of a table the add path already reads, and
    it buys a matcher that is one pure function instead of a chunk of generated SQL.

    Returns ``{id, display_name}`` — the same shape both other rungs return, so
    ``AlreadyPublicResponse`` does not care which one answered. The CALLER is
    responsible for saying that this one guessed: see ``match_kind='name'``.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, display_name
        FROM companies
        WHERE visibility = 'public' AND enabled
        """
    )
    rows = [dict(row) for row in cursor.fetchall()]
    index = build_name_index(
        (str(row["id"]), str(row["display_name"] or "")) for row in rows
    )
    company_id = match_name_in_any_url(urls, index)
    if company_id is None:
        return None
    for row in rows:
        if row["id"] == company_id:
            return {"id": row["id"], "display_name": row["display_name"]}
    return None


def record_add_attempt(
    conn: Connection,
    *,
    user_id: str,
    submitted_url: str,
    normalized_url: Optional[str],
    outcome: str,
    error_detail: Optional[str] = None,
    resolved_ats: Optional[str] = None,
    board_token: Optional[str] = None,
    company_id: Optional[str] = None,
) -> None:
    """Append one ``company_add_attempts`` audit row and commit.

    Committed on its own so a refused/unsupported attempt is durably audited
    even though nothing else is written on that path.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO company_add_attempts (
                user_id, submitted_url, normalized_url, outcome, error_detail,
                resolved_ats, board_token, company_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id, submitted_url, normalized_url, outcome, error_detail,
                resolved_ats, board_token, company_id,
            ),
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise


# Rows in ``company_add_attempts`` that the REQUEST path did NOT write, and which
# therefore must not consume a slot of the caller's monthly add quota.
#
# THIS IS THE ONE THING THE APPROVED PLAN GOT WRONG, so it is spelled out here rather
# than inlined. The plan said "company_add_attempts, straight row count". A straight
# count double-charges every discovered board, because ONE user submission of a
# non-ATS URL produces TWO rows:
#
#   1. ``outcome='discovery_pending'`` written synchronously by the ADD REQUEST
#      (``add_discovering_placeholder``, or the idempotent re-add branch); then
#   2. ``outcome='added'`` (``add_discovered_company``) or ``outcome='refused'``
#      (``record_discovery_refusal``) written MINUTES LATER BY THE WORKER, when the
#      one-time capture finishes.
#
# The owner's rule is "20 URLs entered", so the worker's terminal row is the SAME
# submission reaching its verdict — not a second URL. Counting it would silently make
# the cap 10 discovered boards instead of 20.
#
# The discriminator: every worker-written row has ``resolved_ats='discovered'`` AND an
# outcome other than ``'discovery_pending'``; every request-written row is either not
# ``'discovered'`` at all (the six ATS providers, ``'script'``, ``'name_guess'``,
# ``'already_tracked'``, NULL) or is exactly ``'discovery_pending'``. Written as an
# EXCLUSION so a future terminal outcome on the discovery path (say ``'partial'``) is
# excluded automatically rather than quietly starting to bill users for it.
#
# ``'already_tracked'`` earns its place in that list rather than reusing
# ``'discovered'``: the idempotent re-add branch in ``routers/user_companies`` writes a
# TERMINAL row (``added``/``refused``) from the REQUEST — see
# ``_readd_attempt_fields`` — and with ``resolved_ats='discovered'`` it would be
# indistinguishable from the worker's own terminal row and would stop being billed.
_QUOTA_COUNTED_PREDICATE = (
    "(resolved_ats IS DISTINCT FROM 'discovered' OR outcome = 'discovery_pending')"
)


def count_add_attempts_since(
    conn: Connection, user_id: str, since: datetime
) -> int:
    """How many URLs ``user_id`` has SUBMITTED to the add endpoint since ``since``.

    Exactly one row per ``POST /api/users/companies`` that got as far as being
    recorded — success, refusal, already-published board, all of them — which is what
    makes this a count of *URLs entered* rather than of boards created. Deletes cannot
    reduce it: the purge in :func:`remove_owned_company` deliberately leaves
    ``company_add_attempts`` alone, so a slot spent stays spent.

    ``since`` must be timezone-aware; ``created_at`` is ``TIMESTAMP WITH TIME ZONE``,
    so a naive bound would be compared in the server's timezone and shift the month
    boundary off UTC.

    Reads, and never writes — safe to call on the list endpoint.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT count(*) AS n FROM company_add_attempts "
        "WHERE user_id = %s AND created_at >= %s AND " + _QUOTA_COUNTED_PREDICATE,
        (user_id, since),
    )
    row = cursor.fetchone()
    return int(row["n"]) if row else 0


def add_custom_company(
    conn: Connection,
    *,
    user_id: str,
    ats: str,
    board_token: str,
    provider_config: dict[str, Any],
    display_name: str,
    submitted_url: str,
    normalized_url: Optional[str],
) -> dict[str, Any]:
    """Create the four rows for a new custom company in ONE transaction.

    ``companies`` (visibility='user', health_state='unverified', cadence_hours,
    next_run_at=now(), enabled=true) + ``user_companies`` ownership +
    ``company_scripts`` (the one-primitive ats_client script, oracle_kind='none')
    + a ``company_add_attempts`` audit row (outcome='added'). All-or-nothing.

    Idempotency is the CALLER's responsibility (check
    ``find_owned_company_by_source_key`` first); as a race backstop this catches
    the ``UNIQUE(user_id, canonical_source_key)`` violation and returns the
    existing row instead of erroring.

    The returned dict carries ``created``: True only when this call INSERTED the row.
    The router reads it to decide whether to kick off the first harvest, because the
    race backstop resolves to a company someone else just created — and whoever created
    it already started its harvest. Without the flag the two indistinguishable return
    shapes would make a double-add fire two harvests at one board.
    """
    source_key = canonical_source_key(ats, board_token)
    script = {"kind": "ats_client", "provider": ats, "token": board_token}
    # Store the real oracle for the resolved ATS (DECISION D2). This is
    # book-keeping only — the gate derives the effective oracle from the provider
    # at gate time, so a row left at 'none' (a Phase-1 add) still graduates. New
    # adds record it so a reader can see it without re-deriving.
    from .harvest_verification import effective_oracle_kind

    oracle_kind = effective_oracle_kind(ats)

    last_error: Optional[psycopg2.Error] = None
    for _ in range(_ID_GENERATION_ATTEMPTS):
        company_id = new_custom_company_id()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO companies (
                    id, display_name, ats, board_token, enabled, provider_config,
                    visibility, cadence_hours, next_run_at, health_state,
                    consecutive_failures
                ) VALUES (
                    %s, %s, %s, %s, TRUE, %s::jsonb,
                    'user', %s, now(), 'unverified', 0
                )
                """,
                (
                    company_id, display_name, ats, board_token,
                    json.dumps(provider_config), DEFAULT_CADENCE_HOURS,
                ),
            )
            cursor.execute(
                """
                INSERT INTO user_companies (user_id, company_id, canonical_source_key)
                VALUES (%s, %s, %s)
                """,
                (user_id, company_id, source_key),
            )
            cursor.execute(
                """
                INSERT INTO company_scripts (
                    company_id, script, script_version, transport, oracle_kind
                ) VALUES (%s, %s::jsonb, 1, 'ats_client', %s)
                """,
                (company_id, json.dumps(script), oracle_kind),
            )
            cursor.execute(
                """
                INSERT INTO company_add_attempts (
                    user_id, submitted_url, normalized_url, outcome,
                    resolved_ats, board_token, company_id
                ) VALUES (%s, %s, %s, 'added', %s, %s, %s)
                """,
                (
                    user_id, submitted_url, normalized_url, ats, board_token,
                    company_id,
                ),
            )
            conn.commit()
            return {
                "id": company_id,
                "display_name": display_name,
                "ats": ats,
                "board_token": board_token,
                "health_state": "unverified",
                "last_success_at": None,
                "tracking_started_at": None,
                "source_id": custom(company_id),
                "open_job_count": 0,
                "created": True,
            }
        except psycopg2.errors.UniqueViolation as exc:
            conn.rollback()
            # Two shapes: (a) a companies.id PK collision — regenerate and retry;
            # (b) the (user_id, canonical_source_key) race backstop — the company
            # already exists for this user, so resolve to it idempotently.
            existing = find_owned_company_by_source_key(conn, user_id, source_key)
            if existing is not None:
                existing["source_id"] = custom(existing["id"])
                existing["open_job_count"] = count_open_jobs(conn, existing["id"])
                existing["created"] = False
                return existing
            last_error = exc
            continue
        except psycopg2.Error as exc:
            conn.rollback()
            last_error = exc
            raise

    raise RuntimeError(
        "failed to generate a unique custom company id after "
        f"{_ID_GENERATION_ATTEMPTS} attempts"
    ) from last_error


# A discovered (non-ATS) company has no ATS provider/token; these label the
# ``companies.ats`` / ``board_token`` columns (NOT NULL) so a reader can tell a
# discovered board from an ATS one. The transport + oracle live on company_scripts.
_DISCOVERED_ATS = "discovered"


def discovered_source_key(normalized_url: str) -> str:
    """Idempotency key for a discovered company — there is no ``ats:token``, so the
    normalized final URL identifies the board (``UNIQUE(user_id, canonical_source_key)``)."""
    return f"discovered:{normalized_url}"


def discovery_queueing_lock(user_id: str, normalized_url: str) -> str:
    """The Procrastinate queueing lock a ``discover_custom_company`` job is deferred under.

    Keyed PER USER on purpose (a URL-only lock made a second user's add raise
    ``AlreadyEnqueued``). It lives here, next to the source key it mirrors, because it
    is now read by three places that must agree to the byte: the router that defers the
    job, ``remove_owned_company`` when it cancels one, and the reconciler that asks
    whether a wedged row still has a job behind it. A second copy of this f-string is
    how "cancel the queued discovery" silently cancels nothing.
    """
    return f"discover:{user_id}:{normalized_url}"


def harvest_queueing_lock(company_id: str) -> str:
    """The per-company lock every ``fetch_custom_company`` defer is made under.

    Same reason as :func:`discovery_queueing_lock`: the claim tick, the add-time first
    harvest and the removal path all name it, and they must name the same string.
    """
    return f"custom:{company_id}"


def add_discovering_placeholder(
    conn: Connection,
    *,
    user_id: str,
    submitted_url: str,
    normalized_url: str,
    display_name: str,
) -> dict[str, Any]:
    """Insert a PROVISIONAL ``health_state='discovering'`` row on the 202 add path (§7).

    So ``getUserCompanies`` returns the board IMMEDIATELY (rendered as "Setting up…")
    while the async ``discover_custom_company`` task runs — the fix for the owner's
    "the list stays idle until a hard refresh" bug. The row is DISABLED
    (``enabled=FALSE``, ``next_run_at=NULL``, NO ``company_scripts`` row) so NOTHING
    is ever scraped until discovery flips it to tracked
    (:func:`add_discovered_company`) or ``refused`` (:func:`record_discovery_refusal`).

    Idempotent per ``UNIQUE(user_id, canonical_source_key)`` — a re-add resolves to
    the existing row (whatever state discovery has since moved it to). Returns the row
    dict for the response/list.

    It also seeds the 4-step discovery checklist into ``provider_config['discovery']``
    with step 1 already in progress. Without that seed the row renders a bare "Setting
    up…" badge for as long as the queue takes to pick the job up — i.e. exactly the
    spinner the checklist exists to delete — and a queue that never picks it up would
    show nothing at all rather than "opening the careers page".
    """
    source_key = discovered_source_key(normalized_url)
    existing = find_owned_company_by_source_key(conn, user_id, source_key)
    if existing is not None:
        existing["source_id"] = custom(existing["id"])
        existing["open_job_count"] = count_open_jobs(conn, existing["id"])
        return existing

    # Minted ONCE so the row we write and the dict we return carry the same
    # ``updated_at`` — two calls would stamp two different times for one event.
    seeded_progress = initial_snapshot()

    last_error: Optional[psycopg2.Error] = None
    for _ in range(_ID_GENERATION_ATTEMPTS):
        company_id = new_custom_company_id()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO companies (
                    id, display_name, ats, board_token, enabled, provider_config,
                    visibility, cadence_hours, next_run_at, health_state,
                    consecutive_failures
                ) VALUES (
                    %s, %s, %s, %s, FALSE, %s::jsonb,
                    'user', %s, NULL, 'discovering', 0
                )
                """,
                (company_id, display_name, _DISCOVERED_ATS, normalized_url,
                 json.dumps({"discovery": seeded_progress}),
                 DEFAULT_CADENCE_HOURS),
            )
            cursor.execute(
                """
                INSERT INTO user_companies (user_id, company_id, canonical_source_key)
                VALUES (%s, %s, %s)
                """,
                (user_id, company_id, source_key),
            )
            cursor.execute(
                """
                INSERT INTO company_add_attempts (
                    user_id, submitted_url, normalized_url, outcome,
                    resolved_ats, company_id
                ) VALUES (%s, %s, %s, 'discovery_pending', %s, %s)
                """,
                (user_id, submitted_url, normalized_url, _DISCOVERED_ATS, company_id),
            )
            conn.commit()
            return {
                "id": company_id,
                "display_name": display_name,
                "ats": _DISCOVERED_ATS,
                "board_token": normalized_url,
                "health_state": "discovering",
                "last_success_at": None,
                "tracking_started_at": None,
                "source_id": custom(company_id),
                "open_job_count": 0,
                "provider_config": {"discovery": seeded_progress},
            }
        except psycopg2.errors.UniqueViolation as exc:
            conn.rollback()
            existing = find_owned_company_by_source_key(conn, user_id, source_key)
            if existing is not None:
                existing["source_id"] = custom(existing["id"])
                existing["open_job_count"] = count_open_jobs(conn, existing["id"])
                return existing
            last_error = exc
            continue
        except psycopg2.Error:
            conn.rollback()
            raise

    raise RuntimeError(
        "failed to create a discovering placeholder after "
        f"{_ID_GENERATION_ATTEMPTS} attempts"
    ) from last_error


def record_discovery_progress(
    conn: Connection,
    *,
    user_id: str,
    normalized_url: str,
    progress: dict[str, Any],
) -> bool:
    """Publish ONE live discovery-checklist update onto the provisional row.

    The narration channel behind the 4-step UI: the discovery task calls this as each
    step lands, the 202-added row carries the blob, and the existing
    ``getUserCompanies`` poll picks it up — no second polling channel (DECISION D2).

    ``health_state = 'discovering'`` in the WHERE clause is the load-bearing part. This
    write races the terminal one: a step update already in flight when the run finishes
    would otherwise land AFTER the row was flipped to tracked/refused and resurrect
    "still working" on a settled board. Gating on the provisional state makes a
    straggler a no-op instead. ``jsonb_set`` (not a whole-column write) for the same
    class of reason — it must never clobber a sibling key some later feature adds.

    Returns whether a row was actually updated; a False is normal and uninteresting
    (the run already finished), so callers log at most, never raise. Commits on its own
    — the caller holds a short-lived connection of its own precisely so no pool
    connection is held across a 240-second browser session.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE companies
            SET provider_config = jsonb_set(
                provider_config, '{discovery}', %s::jsonb, true
            )
            WHERE id = (
                SELECT company_id FROM user_companies
                WHERE user_id = %s AND canonical_source_key = %s
            )
              AND visibility = 'user'
              AND health_state = 'discovering'
            """,
            (json.dumps(progress), user_id, discovered_source_key(normalized_url)),
        )
        updated = cursor.rowcount
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise
    return bool(updated)


def record_first_scan(
    conn: Connection, company_id: str, *, ok: bool, detail: str
) -> bool:
    """Settle the FIRST-SCAN rung on a discovered company's checklist. Returns written.

    The harvest task's one write into a blob discovery owns, and the reason the
    checklist can now be honest about "0 open jobs": discovery leaves this rung OPEN
    when it accepts a board, and the run that actually stores jobs is what ticks it.

    READ-MODIFY-WRITE under ``FOR UPDATE`` rather than a clever ``jsonb_set`` path
    expression, because the rung's position in the steps array is not fixed (a row
    written before this rung existed has no entry for it at all) and
    :func:`~api.services.discovery.progress.with_first_scan` is where that
    normalization already lives. The lock costs one row for the length of one UPDATE;
    the discovery writer has long since finished by the time any harvest runs, so it
    exists only to make a concurrent re-discovery a serialization rather than a
    lost update.

    ``False`` — no discovery blob on this row (every ATS custom company, and any
    pre-discovery row) — is the normal, uninteresting case: write nothing. Callers
    treat ANY failure here as cosmetic and never let it fail a harvest; this blob is
    display-only and can never make us scrape, close or refuse anything.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT provider_config FROM companies WHERE id = %s AND visibility = 'user' "
            "FOR UPDATE",
            (company_id,),
        )
        row = cursor.fetchone()
        if row is None:
            conn.rollback()
            return False
        updated = with_first_scan(row["provider_config"], ok=ok, detail=detail)
        if updated is None:
            conn.rollback()
            return False
        cursor.execute(
            """
            UPDATE companies
            SET provider_config = jsonb_set(
                provider_config, '{discovery}', %s::jsonb, true
            )
            WHERE id = %s AND visibility = 'user'
            """,
            (json.dumps(updated), company_id),
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise
    return True


def _progress_param(progress: Optional[dict[str, Any]]) -> Optional[str]:
    """The single bind value for the terminal ``provider_config`` write.

    Every terminal writer uses the same one-parameter SQL::

        provider_config = COALESCE(
            jsonb_set(provider_config, '{discovery}', %s::jsonb, true),
            provider_config
        )

    ``jsonb_set`` returns NULL when ANY argument is NULL, so a NULL bind falls through
    the COALESCE and leaves the column exactly as it was — no dynamic SQL, no second
    parameter to keep in sync, and the whole thing is still one statement with the
    state flip beside it.

    LEAVING IT is the right None case, not clearing it. The one place that hits it in
    production is the discovery TIMEOUT, where there is no outcome to carry a
    checklist — and there the last LIVE snapshot ("opened careers.acme.example ✓ ·
    finding the jobs feed…") is precisely the useful thing: it tells the user how far
    we got before we ran out of time. The frontend frames the row from ``health_state``
    rather than from the blob's own ``outcome``, so a ``running`` blob on a ``refused``
    row still reads as a refusal.
    """
    return json.dumps(progress) if progress is not None else None


def _promote_to_tracked(
    conn: Connection,
    *,
    user_id: str,
    company_id: str,
    submitted_url: str,
    normalized_url: str,
    display_name: str,
    script: dict[str, Any],
    script_version: int,
    transport: str,
    oracle_kind: str,
    progress: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Flip an existing (usually provisional ``discovering``) row to tracked and write
    its script. The 202-placeholder → tracked transition (§7): the discovery task
    accepted, so enable scraping (``health_state='unverified'``, ``enabled=TRUE``,
    ``next_run_at=now()``) and upsert the ``company_scripts`` row (``ON CONFLICT`` so a
    re-discovery replaces the script). Commits all-or-nothing, then records an
    ``added`` attempt.

    ``progress`` is the terminal checklist (all four steps ticked + the job preview),
    written in the SAME statement as the flip so the two can never disagree — see
    :func:`_progress_param` for what ``None`` means.

    ``None`` when the UPDATE matched no row: the caller read the placeholder a moment
    ago and the user has REMOVED it since. That window is small but it is the one a
    person actually hits — the row sits on screen saying "Setting up…" for up to four
    minutes with a Remove button beside it. Without the rowcount check the flip would
    quietly write no company and then INSERT a ``company_scripts`` row and an ``added``
    audit row for a company id that no longer exists."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE companies
            SET health_state = 'unverified', enabled = TRUE, next_run_at = now(),
                display_name = %s, board_token = %s,
                provider_config = COALESCE(
                    jsonb_set(provider_config, '{discovery}', %s::jsonb, true),
                    provider_config
                )
            WHERE id = %s AND visibility = 'user'
            """,
            (display_name, normalized_url, _progress_param(progress), company_id),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            logger.info(
                "discovery accepted %s but its company row is gone — removed mid-run; "
                "writing nothing", normalized_url,
            )
            return None
        cursor.execute(
            """
            INSERT INTO company_scripts (
                company_id, script, script_version, transport, oracle_kind
            ) VALUES (%s, %s::jsonb, %s, %s, %s)
            ON CONFLICT (company_id) DO UPDATE
            SET script = EXCLUDED.script,
                script_version = EXCLUDED.script_version,
                transport = EXCLUDED.transport,
                oracle_kind = EXCLUDED.oracle_kind,
                updated_at = now()
            """,
            (company_id, json.dumps(script), script_version, transport, oracle_kind),
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise
    record_add_attempt(
        conn, user_id=user_id, submitted_url=submitted_url,
        normalized_url=normalized_url, outcome="added",
        resolved_ats=_DISCOVERED_ATS, board_token=normalized_url,
        company_id=company_id,
    )
    return {
        "id": company_id,
        "display_name": display_name,
        "ats": _DISCOVERED_ATS,
        "board_token": normalized_url,
        "health_state": "unverified",
        "last_success_at": None,
        "tracking_started_at": None,
        "source_id": custom(company_id),
        "open_job_count": count_open_jobs(conn, company_id),
        "provider_config": {"discovery": progress} if progress is not None else {},
    }


def add_discovered_company(
    conn: Connection,
    *,
    user_id: str,
    submitted_url: str,
    normalized_url: str,
    display_name: str,
    script: dict[str, Any],
    transport: str,
    oracle_kind: str,
    progress: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Finish a DISCOVERED (non-ATS) custom company by tracking it — E7 Phase 3b.

    The Phase-3 analog of :func:`add_custom_company`: the ``company_scripts`` row
    stores the discovery-proven script with ``transport in {'http_json','http_html',
    'browser_fetch'}`` and the REAL ``oracle_kind`` (facet_sum/header/sitemap/
    self_consistent) — not ``'ats_client'``/``'none'``.

    IT PROMOTES; IT NEVER CREATES. The add path (``routers/user_companies.add_company``)
    inserts a PROVISIONAL ``health_state='discovering'`` row before it defers the
    discovery job (§7), so by the time discovery accepts, the row it is finishing
    already exists. :func:`_promote_to_tracked` flips it to tracked and writes the
    script; ``ON CONFLICT`` on ``company_scripts`` makes a re-discovery replace the
    recipe rather than fail.

    **A MISSING PLACEHOLDER MEANS DELIBERATE REMOVAL, NOT A FIRST INSERT** — the bug
    this contract closes. This used to INSERT a fresh ``companies`` +
    ``user_companies`` + ``company_scripts`` trio when it found no owned row, on the
    reasoning that a task-direct call had no placeholder to promote. But the only way
    production reaches this function without a placeholder is that the user pressed
    Remove while their board was still being set up: ``remove_owned_company`` purges
    the row, the queued job survives, and the INSERT brought the deleted board back —
    tracked, enabled, and harvesting jobs the user never asked for again. There is no
    second caller that legitimately wants a create here, so "the row is gone" now
    returns ``None`` and writes nothing at all. Cancelling the queued job on removal
    (see :func:`remove_owned_company`) removes the cause; this is the guarantee, and it
    is the only half that also covers a removal that lands while the job is RUNNING.

    Returns the tracked company, or ``None`` when the board was removed mid-discovery.
    """
    source_key = discovered_source_key(normalized_url)
    script_version = int(script.get("script_version") or 1)

    existing = find_owned_company_by_source_key(conn, user_id, source_key)
    if existing is None:
        logger.info(
            "add_discovered_company: no owned row for %s (user=%s) — the board was "
            "removed while discovery ran; creating nothing",
            normalized_url, user_id,
        )
        return None

    return _promote_to_tracked(
        conn, user_id=user_id, company_id=existing["id"],
        submitted_url=submitted_url, normalized_url=normalized_url,
        display_name=display_name, script=script, script_version=script_version,
        transport=transport, oracle_kind=oracle_kind, progress=progress,
    )


def record_discovery_refusal(
    conn: Connection,
    *,
    user_id: str,
    submitted_url: str,
    normalized_url: str,
    display_name: str,
    reason: str,
    progress: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Record a loud, terminal discovery REFUSAL (E7 Phase 3b, invariant 6).

    Flips the caller's existing (provisional ``discovering``) row to a DISABLED,
    script-less ``health_state='refused'`` and appends a ``company_add_attempts`` row
    with ``outcome='refused'``, so the user SEES "we can't reliably track this site" as
    a badge in their list while nothing is ever scraped: ``enabled=FALSE``,
    ``next_run_at=NULL``, and no ``company_scripts`` row (so the leaf task no-ops even
    if it were ever reached).

    RECONCILIATION NOTE (deliberate): PHASE-3-PLAN §7 says "no company" on refuse
    while the §0.1 non-negotiable invariant says "set health_state='refused'".
    ``health_state`` is a ``companies`` column, so surfacing the refusal as a badge
    requires a row — a disabled, script-less one is the coherent terminal state
    that honors the invariant without ever harvesting. Returns the company id.

    LIKE :func:`add_discovered_company`, IT NO LONGER CREATES. A refusal for a board
    whose row is gone would put a "Not trackable" chip back in the list of a user who
    had deleted that board — the same resurrection as the accept path, just wearing a
    red badge instead of a green one. ``None`` means the row was removed mid-run and
    nothing was written; the caller logs it and stops.

    ``progress`` is the terminal checklist carrying the NAMED STEP that failed, written
    in the SAME statement as the flip to ``refused``. That is what turns a bare "Not
    trackable" badge into "we found the feed, but couldn't confirm the results match" —
    the difference between a dead end and a next action. ``reason`` still goes to the
    append-only ``company_add_attempts`` audit, which no endpoint reads back.
    """
    source_key = discovered_source_key(normalized_url)
    existing = find_owned_company_by_source_key(conn, user_id, source_key)
    if existing is None:
        logger.info(
            "record_discovery_refusal: no owned row for %s (user=%s) — the board was "
            "removed while discovery ran; creating nothing",
            normalized_url, user_id,
        )
        return None

    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE companies
            SET health_state = 'refused', enabled = FALSE, next_run_at = NULL,
                provider_config = COALESCE(
                    jsonb_set(provider_config, '{discovery}', %s::jsonb, true),
                    provider_config
                )
            WHERE id = %s AND visibility = 'user'
            """,
            (_progress_param(progress), existing["id"]),
        )
        if cursor.rowcount == 0:
            # Removed between the read above and this write. Same reasoning as
            # ``_promote_to_tracked``: write nothing rather than leave an audit row
            # pointing at a company that no longer exists.
            conn.rollback()
            return None
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise
    record_add_attempt(
        conn, user_id=user_id, submitted_url=submitted_url,
        normalized_url=normalized_url, outcome="refused", error_detail=reason,
        resolved_ats=_DISCOVERED_ATS, company_id=existing["id"],
    )
    return str(existing["id"])


def count_open_jobs(conn: Connection, company_id: str) -> int:
    """OPEN job_listings for a custom company (scoped by its own source_id)."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT count(*) AS n FROM job_listings "
        "WHERE company = %s AND source_id = %s AND status = 'OPEN'",
        (company_id, custom(company_id)),
    )
    row = cursor.fetchone()
    return int(row["n"]) if row else 0


def list_owned_companies(conn: Connection, user_id: str) -> list[dict[str, Any]]:
    """The caller's custom companies + health, open-job count, last-success.

    ``open_job_count`` is computed inline against the per-company source_id
    (``'custom:'||c.id``) so a single round-trip returns everything the list
    view needs.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            c.id, c.display_name, c.ats, c.board_token, c.health_state,
            c.last_success_at, c.tracking_started_at, c.enabled, c.created_at,
            -- Carries the discovery checklist for an ats='discovered' row (see
            -- ``discovery.progress``). For an ATS company it holds that provider's
            -- config instead, which ``read_progress`` ignores (no 'discovery' key)
            -- rather than leaking into the response.
            c.provider_config,
            (
                SELECT count(*) FROM job_listings j
                WHERE j.company = c.id
                  AND j.source_id = 'custom:' || c.id
                  AND j.status = 'OPEN'
            ) AS open_job_count
        FROM user_companies uc
        JOIN companies c ON c.id = uc.company_id
        WHERE uc.user_id = %s
        ORDER BY c.created_at DESC, c.id
        """,
        (user_id,),
    )
    rows = cursor.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["source_id"] = custom(d["id"])
        out.append(d)
    return out


def list_owned_source_ids(conn: Connection, user_id: str) -> list[str]:
    """The ``custom:<id>`` namespaces the caller owns — the authorization input for
    the cross-company jobs read.

    Deliberately returns SOURCE IDs, not company ids: ``custom:<id>`` is the
    namespace the job rows actually carry, so the caller's feed query filters on
    the same key the database keys the data by, with no id->namespace translation
    left for a caller to get wrong. Derived from ``user_companies``, so the set
    can only ever be what this user owns.

    The ``visibility = 'user'`` filter is defense-in-depth: a contrived ownership
    row pointing at a public company must not smuggle that company into a private
    read path (the mirror of the guard in :func:`remove_owned_company`).
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.id
        FROM user_companies uc
        JOIN companies c ON c.id = uc.company_id
        WHERE uc.user_id = %s AND c.visibility = 'user'
        """,
        (user_id,),
    )
    return [custom(row["id"]) for row in cursor.fetchall()]


def get_company_if_owner(
    conn: Connection, user_id: str, company_id: str
) -> Optional[dict[str, Any]]:
    """The company row IF ``user_id`` owns ``company_id``, else None (→ 403)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.id, c.display_name, c.ats, c.board_token, c.health_state,
               c.last_success_at, c.tracking_started_at, c.enabled, c.created_at
        FROM user_companies uc
        JOIN companies c ON c.id = uc.company_id
        WHERE uc.user_id = %s AND c.id = %s
        """,
        (user_id, company_id),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def purge_custom_company(
    cursor: Any,
    *,
    company_id: str,
    board_token: Optional[str],
    owner_user_id: Optional[str],
) -> bool:
    """Delete everything ONE private company owns, in the single order that works.

    EXTRACTED, NOT INVENTED. ``custom_company_integrity``'s docstring says any
    reaper written later "must reuse ``remove_owned_company``'s purge ORDER …
    never invent a second one", so the order now lives here and both callers name
    it: :func:`remove_owned_company` (the user pressed Remove) and
    ``api.tasks.reap_ownerless_companies`` (nobody is left to press it). A second
    copy of this sequence is how a purge starts stranding rows in one of the two
    paths only.

    ORDER matters, and the reasons are load-bearing:

    * the queued work is cancelled FIRST, before the rows it would run against are
      gone — otherwise a worker picks the job up minutes later and harvests, or
      re-creates, a board that no longer exists;
    * ``job_locations`` has NO foreign key and is keyed by ``job_listing_id``
      alone, so it must be cleared while the listings it derives from still exist,
      and the ``NOT EXISTS`` narrows it to ids used ONLY by this source (a public
      listing that happens to share an id keeps its location tags);
    * ``job_tags`` / ``job_enrichment`` / ``job_listings`` are keyed by
      ``source_id``, and ``custom:<id>`` is a namespace no other company can write,
      so the source_id predicate alone scopes them exactly;
    * ``job_freshness`` is NOT listed because it does not need to be — it carries a
      composite FK ``ON DELETE CASCADE`` onto ``job_listings``.

    NEVER-WRONG-CLOSE: every statement here is a DELETE. Nothing sets
    ``status='CLOSED'``, nothing writes ``closed_on``, and nothing touches
    ``job_freshness.consecutive_misses``. A purge REMOVES a board's history; it
    never decides that a job went away, which is the only thing a close means.

    ``company_add_attempts`` is deliberately left behind — see
    :func:`remove_owned_company`.

    CONNECTION CONTRACT: takes a CURSOR, never a connection, and NEVER commits.
    The caller owns the transaction, because a partial purge strands exactly the
    rows this exists to remove.

    ``owner_user_id`` is optional because an OWNERLESS row has no user to
    reconstruct ``discover:{user}:{url}`` from; the harvest lock is keyed by the
    company id alone and is always cancelled. A discovery job that therefore
    survives is harmless: ``add_discovered_company`` and
    ``record_discovery_refusal`` both create nothing when the owned row is gone.

    Returns ``False`` — having cancelled the queued work but deleted nothing —
    when ``company_id`` is not an id we could have minted, so its ``custom:<id>``
    namespace cannot contain anything.
    """
    locks = [harvest_queueing_lock(company_id)]
    if owner_user_id and board_token:
        locks.append(discovery_queueing_lock(owner_user_id, str(board_token)))
    cancel_queued_jobs(cursor, locks)

    try:
        source_id = custom(company_id)
    except ValueError:
        logger.warning(
            "purge_custom_company: skipped the purge of %s — the id is not one we "
            "could have minted", company_id,
        )
        return False

    cursor.execute(
        """
        DELETE FROM job_locations jl
        WHERE jl.job_listing_id IN (
                SELECT id FROM job_listings WHERE source_id = %s
            )
          AND NOT EXISTS (
                SELECT 1 FROM job_listings o
                WHERE o.id = jl.job_listing_id AND o.source_id <> %s
            )
        """,
        (source_id, source_id),
    )
    cursor.execute("DELETE FROM job_tags WHERE source_id = %s", (source_id,))
    cursor.execute("DELETE FROM job_enrichment WHERE source_id = %s", (source_id,))
    cursor.execute("DELETE FROM job_listings WHERE source_id = %s", (source_id,))

    # Per-company operational state. Deleted, not kept: none of it is reachable
    # once the company is gone (no UI joins it, and a re-add mints a new id), and a
    # leftover scrape_runs row for a company that no longer exists is a false signal
    # to the health watchdog. ``scrape_runs`` is scoped by ``company`` rather than
    # source_id so a row written before source_id was populated still goes; a custom
    # company id is globally unique, so this cannot reach a public board's runs.
    cursor.execute("DELETE FROM company_harvests WHERE company_id = %s", (company_id,))
    cursor.execute("DELETE FROM scrape_runs WHERE company = %s", (company_id,))
    cursor.execute("DELETE FROM company_scripts WHERE company_id = %s", (company_id,))
    # ``AND visibility = 'user'`` is the last guard: a public board's row must never
    # be destroyed through any purge path, whatever id reached this function.
    cursor.execute(
        "DELETE FROM companies WHERE id = %s AND visibility = 'user'",
        (company_id,),
    )
    return True


def remove_owned_company(conn: Connection, user_id: str, company_id: str) -> str:
    """Remove the caller's ownership AND, if that was the last owner, PURGE the
    company and every row it owns — in ONE transaction.

    The Phase-1 behaviour was ``UPDATE companies SET enabled = FALSE`` and nothing
    else. That left, per removed board, an ownerless ``companies`` row, its
    ``company_scripts`` recipe, and the whole ``custom:<id>`` job namespace
    (10,000 rows on the owner's Amazon board) alive in the database forever:
    invisible to every UI — the list joins ``user_companies``, which no longer has
    a row — and unreachable by any future re-add, because a re-add mints a NEW
    company id. "Remove" has to mean removed.

    IT ALSO CANCELS THE WORK STILL QUEUED FOR THIS BOARD, in the same transaction.
    That is the fix for a board coming BACK after it was removed: a pasted URL defers
    a ``discover_custom_company`` job keyed on ``(user, url)``, not on the company id,
    so deleting the row left that job on the broker to run four minutes later against
    a company that no longer existed — and it then created a brand-new one, tracked,
    with jobs. Cancelling here is the cause-removal (no browser session, no Claude
    call, no reserved interactive slot spent on a deleted board); the refusal inside
    :func:`add_discovered_company` is the guarantee, because a job already RUNNING
    cannot be cancelled. The queued first harvest goes the same way, for the same
    reason: nothing should read a board nobody owns.

    SHARED vs PER-USER. A ``companies`` row is never shared. Every
    ``user_companies`` INSERT in this module is paired with a fresh
    ``INSERT INTO companies`` in the same statement block
    (:func:`add_custom_company`, :func:`add_discovering_placeholder`) — nothing
    ever links a second user to an existing row — so two users who add the same
    board get two distinct companies and two distinct ``custom:<id>`` namespaces
    (see :class:`api.db_models.UserCompany`). A hard delete is therefore correct
    and cannot reach another user's data. The last-owner count below is kept
    anyway: it is the guard that makes this still safe if row sharing is ever
    introduced, and it costs one indexed count.

    ORDER matters, and it lives in :func:`purge_custom_company` — one ordering,
    two callers (this, and the ownerless reaper), never two copies. Everything
    runs on one cursor with a single terminal ``commit()`` — a partial purge would
    strand exactly the rows this function exists to remove, with no owner left to
    retry it.

    Returns:
        ``'not_owner'`` if the caller did not own it (→ router 404),
        ``'purged'`` if this removed the last owner and the company + its data
        were deleted,
        ``'unlinked'`` if only the ownership link went (another owner remains, or
        the id resolved to a company that is NOT ``visibility='user'`` — a public
        board's data must never be destroyed through this path).
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM user_companies WHERE user_id = %s AND company_id = %s",
            (user_id, company_id),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            return "not_owner"

        cursor.execute(
            "SELECT count(*) AS n FROM user_companies WHERE company_id = %s",
            (company_id,),
        )
        remaining = cursor.fetchone()
        if remaining and int(remaining["n"]) > 0:
            conn.commit()
            return "unlinked"

        # ``FOR UPDATE`` pins the row for the rest of the transaction so a
        # concurrent claim tick cannot flip it to running between this read and
        # the DELETE below. A missing row (already purged, or an ownership row
        # that outlived its company) still purges the ``custom:<id>`` namespace —
        # that namespace is derived from the id we just proved the caller owned,
        # so orphaned jobs under it are exactly what we came to collect.
        cursor.execute(
            "SELECT visibility, board_token FROM companies WHERE id = %s FOR UPDATE",
            (company_id,),
        )
        company_row = cursor.fetchone()
        if company_row is not None and company_row["visibility"] != "user":
            # Defense-in-depth, same intent as the old ``AND visibility='user'``
            # guard: a public company id reaching this path (a contrived
            # ownership row, a future caller bug) must lose only the link. Purging
            # here would take a curated board's jobs off the public site.
            conn.commit()
            return "unlinked"

        # THE PURGE ORDER lives in :func:`purge_custom_company`, which the ownerless
        # reaper also calls — so there is exactly one delete ordering in the codebase.
        # ``board_token`` is read from the row we just locked rather than from
        # anything the caller passed: it IS the normalized URL the discovery job was
        # deferred under (``add_discovering_placeholder`` writes exactly that), so the
        # lock string cancelled is the one the router minted. A row that has already
        # gone (``company_row is None``) has no discovery lock to reconstruct.
        #
        # ``False`` means ``custom()`` rejected the id, which is resolved THERE and
        # not at the top of this function on purpose: ``company_id`` arrives straight
        # off the URL path, and up front a rejection turned "DELETE an id that isn't
        # yours" — any 404, and any hand-inserted ownership row — into an unhandled
        # 500. By this point the caller has been proven to own a ``visibility='user'``
        # row, so a rejection means an id we never minted and therefore a
        # ``custom:<id>`` namespace that cannot contain anything: drop the link and
        # stop, rather than failing a cleanup.
        purged = purge_custom_company(
            cursor,
            company_id=company_id,
            board_token=(
                str(company_row["board_token"])
                if company_row is not None and company_row["board_token"]
                else None
            ),
            owner_user_id=user_id,
        )
        if not purged:
            logger.warning(
                "remove_owned_company: unlinked %s but skipped the purge — the id "
                "is not one we could have minted", company_id,
            )
            conn.commit()
            return "unlinked"

        # DELIBERATELY KEPT: ``company_add_attempts``. It is the append-only audit
        # of what the user pasted and what happened to it (see
        # :class:`api.db_models.CompanyAddAttempt` — "a fact about what happened,
        # not a piece of the user's profile"), it is the only record that an add
        # ever occurred, and it is what a support question about a board that
        # never worked is answered from. Its ``company_id`` is a soft link with no
        # FK, so the now-dangling id is a historical reference, not an orphan.
        conn.commit()
        return "purged"
    except psycopg2.Error:
        conn.rollback()
        raise


# --- Worker-facing --------------------------------------------------------


def load_custom_company_for_run(
    conn: Connection, company_id: str
) -> Optional[dict[str, Any]]:
    """The company + its stored script, everything the leaf task needs to run.

    Returns None if the company or its script row is missing (the leaf task
    treats that as nothing to do). ``provider_config`` and ``script`` come back
    as dicts (psycopg2 deserializes JSONB).
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.ats, c.board_token, c.provider_config, c.enabled, c.visibility,
               c.cadence_hours, c.tracking_started_at,
               s.script, s.oracle_kind, s.transport, s.script_version
        FROM companies c
        JOIN company_scripts s ON s.company_id = c.id
        WHERE c.id = %s
        """,
        (company_id,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def mark_last_success(conn: Connection, company_id: str) -> None:
    """Stamp ``companies.last_success_at = now()`` after a successful harvest.

    Called on every SUCCESSFUL (non-FAILED) custom-company run — i.e. wherever
    ``scrape_runs.success = true`` is written. In Phase 1 every run is UNVERIFIED,
    so this is the ONLY thing that ever moves ``last_success_at`` off NULL; gating
    it on VERIFIED would leave the "last checked" UI reading "Not yet checked"
    forever for every custom company.

    Deliberately does NOT touch ``health_state`` (stays 'unverified' in Phase 1 —
    no oracle exists) or ``tracking_started_at`` (§2: set only on the first
    VERIFIED harvest, so it stays NULL until Phase 2). Commits on its own,
    mirroring ``record_scrape_run`` / ``record_company_harvest``.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE companies SET last_success_at = now() WHERE id = %s",
            (company_id,),
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise


def mark_verified(conn: Connection, company_id: str, *, set_tracking: bool) -> None:
    """Flip a custom company to ``health_state='healthy'`` after a VERIFIED run.

    Called on every VERIFIED harvest (the run PROVED it saw the whole board, so
    the company is healthy regardless of whether it closed anything this run).
    On the FIRST VERIFIED run (``set_tracking=True``) it also stamps
    ``tracking_started_at`` — but only if still NULL, via ``COALESCE``, so a
    retry or a later run can never move the tracking origin. Commits on its own,
    mirroring ``mark_last_success`` / ``record_company_harvest``.
    """
    cursor = conn.cursor()
    try:
        if set_tracking:
            cursor.execute(
                "UPDATE companies SET health_state = 'healthy', "
                "tracking_started_at = COALESCE(tracking_started_at, now()) "
                "WHERE id = %s",
                (company_id,),
            )
        else:
            cursor.execute(
                "UPDATE companies SET health_state = 'healthy' WHERE id = %s",
                (company_id,),
            )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise


def consecutive_verified(conn: Connection, company_id: str, *, limit: int = 10) -> int:
    """Count the company's trailing run of VERIFIED harvests (E7 §Task D.3).

    Reads ``company_harvests`` most-recent-first and counts the leading run of
    ``verdict='VERIFIED'`` rows until the first non-VERIFIED (or NULL) row stops
    the count — mirroring ``count_consecutive_partial_skips``. Gates
    ``self_consistent`` closes: a company may only close once THIS run makes its
    consecutive-VERIFIED streak reach 3.

    NOTE: the current run's ``company_harvests`` row is written in the leaf task's
    ``finally`` — AFTER this is read — so the returned count is the PRIOR streak,
    excluding the run in flight.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT verdict FROM company_harvests
            WHERE company_id = %s
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (company_id, max(1, limit)),
        )
        rows = cursor.fetchall()
    finally:
        # SELECT-only — never leave the caller's connection idle-in-transaction.
        conn.rollback()

    streak = 0
    for row in rows:
        if row["verdict"] != "VERIFIED":
            break
        streak += 1
    return streak


def script_changed_since_last(conn: Connection, company_id: str) -> bool:
    """True iff the stored script changed since the last VERIFIED harvest (D.2).

    ``company_scripts.updated_at > max(completed_at of prior VERIFIED
    company_harvests)`` — uses the existing ``updated_at`` (no new column). "The
    first run after any script/baseline change closes nothing" is enforced by
    this returning True on that first run.

    In Phase 2 scripts never change (repair is Phase 5), so ``updated_at`` is the
    creation time, which predates every harvest → this is always False and the
    branch is a forward seam. Returns False when there are no prior VERIFIED
    harvests (that day-one case is covered by the first-VERIFIED-run branch,
    which has precedence).
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT s.updated_at AS script_updated_at,
                   (
                       SELECT max(h.completed_at)
                       FROM company_harvests h
                       WHERE h.company_id = %s AND h.verdict = 'VERIFIED'
                   ) AS last_verified_at
            FROM company_scripts s
            WHERE s.company_id = %s
            """,
            (company_id, company_id),
        )
        row = cursor.fetchone()
    finally:
        conn.rollback()

    if row is None or row["last_verified_at"] is None:
        return False
    updated_at = row["script_updated_at"]
    if updated_at is None:
        return False
    return bool(updated_at > row["last_verified_at"])


def fleet_breaker_tripped(
    conn: Connection,
    *,
    window_hours: float = 24.0,
    min_sample: int = 5,
    fail_fraction: float = 0.20,
) -> bool:
    """Fleet circuit breaker (§4.3): did > 20% of the night's custom runs FAIL?

    If so, NO custom company closes that night — the check that would have made
    the 2026-03-29 mass closure a non-event. Computed as a night-scoped aggregate
    over ``scrape_runs`` (there is no barrier where "the night's companies" all
    finish, so each leaf task reads this right before its close step):

        tripped iff total >= min_sample AND failed / total > fail_fraction

    Global across ALL custom companies on purpose — a systemic failure (a shared
    client bug now, a Browserbase outage in Phase 4) is exactly the class this
    generalizes. It never touches another user's DATA (source_id isolation
    holds); it only SUPPRESSES this company's close.

    ``scrape_runs.started_at`` is ISO-8601 Text, so the cutoff is a Python-
    computed ISO string compared lexicographically (correct for zero-padded UTC).

    KNOWN LIMITATIONS (review Finding 2 — deferred to the fleet-hardening pass in
    STACK-ORCHESTRATION.md): this is a point-in-time aggregate over a full 24h
    window, read independently by each leaf task, so it is intentionally
    approximate:
      (a) a company that finishes EARLY may read a breaker that does not yet
          reflect not-yet-committed FAILED siblings from the same night, and
      (b) with same-time daily clustering the PRIOR night's successes (still
          inside the 24h window) dilute tonight's failure fraction.
    Both err toward NOT tripping (a close may slip through on a genuinely bad
    night). Safe-ish because every OTHER close gate still applies; the breaker is
    a fleet-wide backstop, not the only guard. TODO: scope to the current claim
    batch / a shorter night window and count only ``completed_at``-set runs.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=window_hours)
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE success IS FALSE) AS failed
            FROM scrape_runs
            WHERE source_id LIKE 'custom:%%' AND started_at >= %s
            """,
            (cutoff,),
        )
        row = cursor.fetchone()
    finally:
        conn.rollback()

    if row is None:
        return False
    total = int(row["total"] or 0)
    failed = int(row["failed"] or 0)
    if total < min_sample:
        return False
    return (failed / total) > fail_fraction


def record_company_harvest(
    conn: Connection,
    *,
    company_id: str,
    run_id: str,
    started_at: str,
    completed_at: str,
    verdict: str,
    verdict_reason: Optional[str],
    records_harvested: int,
    oracle_kind: str,
    id_dedup_dropped: int = 0,
    declared_total: Optional[int] = None,
    oracle_total: Optional[int] = None,
    cap_hit: bool = False,
    page_advance_ok: Optional[bool] = None,
    tolerance_used: float = 0.0,
) -> None:
    """Append one ``company_harvests`` evidence row and commit (autonomous).

    Committed on its own — mirroring ``record_scrape_run`` — so the per-run
    evidence lands even if written from the leaf task's ``finally`` after an
    error.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO company_harvests (
                company_id, run_id, started_at, completed_at, verdict,
                verdict_reason, records_harvested, declared_total, oracle_total,
                oracle_kind, cap_hit, page_advance_ok, id_dedup_dropped,
                tolerance_used
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                company_id, run_id, started_at, completed_at, verdict,
                verdict_reason, records_harvested, declared_total, oracle_total,
                oracle_kind, cap_hit, page_advance_ok, id_dedup_dropped,
                tolerance_used,
            ),
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise
