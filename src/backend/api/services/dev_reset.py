"""LOCAL-DEVELOPMENT-ONLY reset of the user-added (custom) company tables.

WHY THIS EXISTS. The add-a-company flow is not idempotent by design: once a board
has been added, ``POST /api/users/companies`` answers "you already track this" (the
``uq_user_companies_source_key`` idempotent re-add) or "we already publish this"
(the published-board match), and the monthly quota has burned a slot. A developer
testing the flow therefore gets exactly ONE run of the real code path per board.
This module puts the database back to the state where that board was never added.

THE DELETE IS THE EASY PART; THE GUARDS ARE THE FEATURE. A "delete every user-added
company" route reachable in production would be unrecoverable, so there are four
independent layers and this module owns the two that matter most:

1. ``settings.dev_reset_enabled`` (default False) — with it off ``main.py`` never
   calls ``include_router``, so the path 404s like any path that does not exist.
2. :func:`assert_local_database` — re-derived at CALL time from
   ``settings.database_url``, INDEPENDENT of the flag, and FAIL-CLOSED: anything it
   cannot parse, or that does not resolve to a loopback host, refuses. This is the
   layer that survives ``DEV_RESET_ENABLED=true`` being set on the wrong machine.
   It parses with libpq's own ``parse_dsn``, because a DSN's ``host=`` / ``hostaddr=``
   query parameters OVERRIDE the authority in the URL and ``urlsplit`` cannot see
   that: ``…@localhost/db?host=prod.railway.internal`` reads as "localhost" and
   connects to production.
3. :func:`assert_local_connection` — the same question asked of the CONNECTION the
   DELETEs will travel down (libpq's own ``conn.info.host``, plus
   ``SELECT inet_server_addr()``). The static check judges a config string; the pool
   is built from an augmented copy of it and the tests from a different variable
   entirely, so proving the setting is local proves nothing about the socket.
4. Never proxied — no ``api/*.ts`` allowlists it; pinned by
   ``api/tests/test_proxy_path_allowlists.py``'s ``NOT_PROXIED``.
5. ``?scope=all`` — which deletes every USER's rows, not just the caller's —
   additionally requires an ``admins`` grant (``routers/dev_reset.py``).
6. Every delete is scoped to ``visibility='user'``. A published company's row, and
   every job under a published source_id, is unreachable from here.

THE PURGE ORDER IS NOT REINVENTED. ``custom_companies_service.purge_custom_company``
is the single ordering in the codebase (its docstring says any later reaper "must
reuse ``remove_owned_company``'s purge ORDER … never invent a second one"), and this
is a third caller of it, not a second copy. That is also why ``job_freshness`` is
absent from every statement below: it carries a composite FK ``ON DELETE CASCADE``
onto ``job_listings``, so it goes with the listings and is only COUNTED here.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extensions import connection as Connection, parse_dsn

from scripts.shared.constants import CUSTOM_SOURCE_PREFIX, custom

from .custom_companies_service import purge_custom_company

logger = logging.getLogger(__name__)

# The only hostname spelling accepted that is not already an IP literal. Compared
# with ``==`` against the parsed hostname, never with ``in`` — a substring test
# would accept ``localhost.evil.example`` and ``db-localhost.prod.internal``.
_LOOPBACK_HOSTNAME = "localhost"

# ``postgresql://``, ``postgres://`` and the SQLAlchemy driver spellings
# (``postgresql+psycopg2://``). Anything else is a URL we do not understand, and a
# URL we do not understand is refused rather than guessed at.
_POSTGRES_SCHEME_PREFIX = "postgres"

SCOPE_MINE = "mine"
SCOPE_ALL = "all"


class NonLocalDatabaseError(RuntimeError):
    """``database_url`` is not provably a loopback database — refuse to delete.

    Raised for BOTH "this points somewhere else" and "this could not be parsed".
    They are the same answer on purpose: the guard's contract is *proof* of
    localhost, so absence of proof is refusal.
    """


def _strip_sqlalchemy_driver(database_url: str) -> str:
    """``postgresql+psycopg2://…`` → ``postgresql://…``, everything else untouched.

    libpq has never heard of SQLAlchemy's ``+driver`` spelling and ``parse_dsn``
    refuses the whole string when it sees one. Only the scheme is rewritten; the
    query parameters this guard exists to read are left exactly as they are.
    """
    scheme, separator, rest = database_url.partition("://")
    if not separator or "+" not in scheme:
        return database_url
    return f"{scheme.split('+', 1)[0]}{separator}{rest}"


def _assert_loopback(value: str, *, source: str) -> None:
    """Raise unless ``value`` is the literal ``localhost`` or a loopback IP.

    Loopback is decided by :mod:`ipaddress`, not by an equality test against
    ``127.0.0.1``: the whole ``127.0.0.0/8`` block and IPv6 ``::1`` are loopback, and
    hard-coding one spelling would refuse a developer whose DSN says ``127.0.0.2``.
    """
    host = value.strip().lower()
    if not host:
        raise NonLocalDatabaseError(
            f"refusing the dev reset: {source} is empty, so it cannot be proven to "
            f"be a local database"
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host != _LOOPBACK_HOSTNAME:
            raise NonLocalDatabaseError(
                f"refusing the dev reset: {source} is {host!r}, which is not "
                f"localhost. This endpoint only ever runs against a loopback "
                f"database."
            ) from None
        return
    if not address.is_loopback:
        raise NonLocalDatabaseError(
            f"refusing the dev reset: {source} is {host!r}, which is not a loopback "
            f"address. This endpoint only ever runs against a loopback database."
        )


def assert_local_database(database_url: str) -> str:
    """Return the loopback host libpq would DIAL, or raise :class:`NonLocalDatabaseError`.

    PARSED, NEVER SUBSTRING-MATCHED. ``'localhost' in url`` is true for
    ``postgresql://u:p@prod.example/db?options=--search_path%3Dlocalhost`` and for
    ``postgresql://localhost@evil.example/db`` — whose real host is ``evil.example``,
    because a userinfo section ends at the LAST ``@``.

    AND PARSED THE WAY LIBPQ PARSES IT, which ``urlsplit`` alone is not. A Postgres
    DSN may carry ``host=`` / ``hostaddr=`` **as query parameters**, and when it does
    they WIN — the authority in the URL is then just decoration. ``dependencies.py``
    hands the DSN to psycopg2 through ``augment_db_url``, which preserves the query
    string, so both of these connected to production while this function said
    "localhost" (measured 2026-09-04):

    ==================================================  ============  ==================
    DSN                                                 urlsplit says libpq dials
    ==================================================  ============  ==================
    ``…@localhost:5432/db?host=prod.railway.internal``  localhost     prod.railway.internal
    ``…@localhost:5432/db?hostaddr=10.0.0.5``           localhost     10.0.0.5
    ==================================================  ============  ==================

    So ``psycopg2.extensions.parse_dsn`` — libpq's own parser, resolving the same keys
    libpq will — decides, and EVERY host the string names (the URL authority, ``host``
    and ``hostaddr``) must independently be loopback. One of them pointing somewhere
    else is a refusal, whichever one libpq would have preferred.

    STATIC ONLY. It reads a string; it cannot know what answered. Pair it with
    :func:`assert_local_connection`, which asks the server that actually picked up.

    FAILS CLOSED at every branch: an unparseable URL, a DSN libpq cannot parse, a
    scheme that is not Postgres, a string naming no host at all (a Unix-socket DSN
    such as ``postgresql:///jobscraper``, or a ``host=/var/run/postgresql`` socket
    directory — local in practice, but not *provably* so from the string, and the
    contract here is proof), or a host that is neither ``localhost`` nor a loopback IP.
    """
    try:
        parts = urlsplit(database_url)
        scheme = parts.scheme.lower()
        url_hostname = parts.hostname
        # ACCESSING ``.port`` IS THE CHECK, not a value we need. ``.hostname`` is
        # lenient about the rest of the authority, so ``@localhost:notaport`` would
        # otherwise sail through as "localhost" — and ``parse_dsn`` accepts that port
        # too, so this is the only thing that catches it. A DSN we have not
        # understood is a DSN we refuse.
        _ = parts.port
    except ValueError as exc:  # malformed IPv6 literal, non-numeric port, …
        raise NonLocalDatabaseError(
            "refusing the dev reset: database_url could not be parsed as a URL"
        ) from exc

    if not scheme.startswith(_POSTGRES_SCHEME_PREFIX):
        raise NonLocalDatabaseError(
            f"refusing the dev reset: database_url scheme {scheme!r} is not a "
            f"PostgreSQL URL, so its host cannot be checked"
        )

    try:
        dsn = parse_dsn(_strip_sqlalchemy_driver(database_url))
    except psycopg2.Error as exc:
        raise NonLocalDatabaseError(
            "refusing the dev reset: database_url is not a DSN libpq can parse, so "
            "the host it would really connect to is unknown"
        ) from exc

    dsn_host = dsn.get("host")
    dsn_hostaddr = dsn.get("hostaddr")
    named = [
        (url_hostname, "the database_url host"),
        (dsn_host, "the DSN's host= parameter"),
        (dsn_hostaddr, "the DSN's hostaddr= parameter"),
    ]
    present = [(str(value), label) for value, label in named if value]
    if not present:
        raise NonLocalDatabaseError(
            "refusing the dev reset: database_url names no host, so it cannot be "
            "proven to be a local database"
        )
    for value, label in present:
        _assert_loopback(value, source=label)

    # What libpq would actually dial, in its own precedence order — that is the host
    # the QA panel names on the button, so it must be the one that was checked last
    # rather than the one that reads best.
    effective = dsn_hostaddr or dsn_host or url_hostname
    return str(effective).strip().lower()


def assert_local_connection(conn: Connection) -> None:
    """Check the CONNECTION we are about to delete through, not a config string.

    :func:`assert_local_database` judges ``settings.database_url``. This judges the
    live connection, which is not the same object: it comes out of a pool built from
    a DSN that was augmented on the way in (``dependencies.augment_db_url``), and in
    tests it comes from ``TEST_DATABASE_URL`` entirely. Proving the setting is local
    proves nothing about the socket the DELETEs will travel down.

    TWO QUESTIONS:

    1. **Where did libpq connect?** ``conn.info.host`` is libpq's own account of the
       host parameter it used for THIS connection — including a ``host=`` that came
       out of the query string, which is the bypass the static check now closes. It
       must be loopback, or a socket directory (a path never leaves the machine).
    2. **Where did the server answer from?** ``inet_server_addr()`` is NULL over a
       Unix socket (local by construction) and otherwise the server's own address.

    WHY (2) IS NOT REQUIRED TO BE LOOPBACK, measured rather than assumed. The setup
    this repo prescribes — ``docker compose up -d postgres``, connected as
    ``localhost:5432`` through a published port — reports **172.18.0.2** on this
    machine, because the server is inside the container's network and sees the NATed
    connection. GitHub Actions' service containers are the same shape. Demanding
    loopback there would refuse every ordinary local setup, including the one the
    owner runs, so what is refused is a **globally routable** server address: we
    dialed something local and ended up somewhere on the public internet. A private
    address is the container case and is allowed, with (1) carrying the weight.

    FAILS CLOSED on anything it cannot establish — an unreadable row, an address that
    will not parse, a query that errored. "We could not tell where this database is"
    is the same answer as "somewhere else".
    """
    host = (conn.info.host or "").strip()
    if not host:
        raise NonLocalDatabaseError(
            "refusing the dev reset: the connection does not say which host it "
            "reached, so it cannot be proven to be a local database"
        )
    if not host.startswith("/"):  # a socket DIRECTORY is local by construction
        _assert_loopback(host, source="the host libpq actually connected to")

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT inet_server_addr() AS server_addr")
        row = cursor.fetchone()
    except psycopg2.Error as exc:
        raise NonLocalDatabaseError(
            "refusing the dev reset: the database would not say where it is "
            "(SELECT inet_server_addr() failed)"
        ) from exc

    if row is None:
        raise NonLocalDatabaseError(
            "refusing the dev reset: the database did not answer where it is"
        )
    address = row["server_addr"] if isinstance(row, dict) else row[0]
    if address is None:
        return  # Unix-domain socket: it never left this machine.

    # ``inet`` may render with a prefix length (``172.18.0.2/32``) depending on the
    # cursor factory; the prefix is not part of the address.
    text = str(address).split("/")[0]
    try:
        parsed = ipaddress.ip_address(text)
    except ValueError as exc:
        raise NonLocalDatabaseError(
            f"refusing the dev reset: the database reported an address we could not "
            f"parse ({text!r})"
        ) from exc
    if parsed.is_loopback or parsed.is_private:
        return
    raise NonLocalDatabaseError(
        f"refusing the dev reset: we connected to {host!r} but the server answered "
        f"from {text!r}, a public address. Something is forwarding a local port to a "
        f"remote database."
    )


@dataclass(frozen=True)
class ResetOutcome:
    """What one reset actually removed, and what it left standing.

    ``deleted`` is keyed by table name so the WARNING log, the API response and the
    button's confirmation all read the same numbers. ``published_companies_kept`` /
    ``published_jobs_kept`` are counted AFTER the deletes and are the whole point of
    reporting them: they are the assertion "the published fleet is still there",
    made by the code that just deleted things rather than by a comment claiming it.
    """

    scope: str
    company_ids: list[str]
    deleted: dict[str, int]
    published_companies_kept: int
    published_jobs_kept: int


def _count(cursor: Any, query: str, params: tuple = ()) -> int:
    cursor.execute(query, params)
    row = cursor.fetchone()
    if row is None:
        return 0
    return int(row["n"] if isinstance(row, dict) else row[0])


def _target_companies(
    cursor: Any, user_id: Optional[str]
) -> list[dict[str, Any]]:
    """The ``visibility='user'`` rows in scope, each with ONE owner id.

    ``visibility = 'user'`` is in both branches and is the load-bearing predicate: a
    published company can never enter this list, so no later statement can reach one.

    The owner is carried because :func:`purge_custom_company` needs it to reconstruct
    the ``discover:{user}:{url}`` queueing lock and cancel a discovery job that has
    not started yet. A row with no owner (the reaper's case) yields ``None``, which
    that function accepts.
    """
    if user_id is None:
        cursor.execute(
            """
            SELECT c.id, c.board_token,
                   (SELECT uc.user_id FROM user_companies uc
                     WHERE uc.company_id = c.id LIMIT 1) AS owner_user_id
            FROM companies c
            WHERE c.visibility = 'user'
            ORDER BY c.id
            """
        )
    else:
        cursor.execute(
            """
            SELECT c.id, c.board_token, uc.user_id AS owner_user_id
            FROM companies c
            JOIN user_companies uc ON uc.company_id = c.id
            WHERE c.visibility = 'user' AND uc.user_id = %s
            ORDER BY c.id
            """,
            (user_id,),
        )
    return [dict(row) for row in cursor.fetchall()]


def reset_custom_companies(
    conn: Connection, *, user_id: Optional[str], commit: bool = True
) -> ResetOutcome:
    """Delete the custom companies in scope and everything hanging off them.

    ``user_id=None`` means EVERY custom company (``scope=all``); a user id means only
    the boards that user owns, which is the default the endpoint uses. Scoping to the
    caller is the safer default for the same reason the delete endpoint is per-user:
    it is the smallest thing that solves "let me add this board again".

    ONE TRANSACTION. A half-applied reset is the exact state this exists to leave: a
    ``companies`` row deleted but its ownership row surviving is invisible to the UI
    and unreachable by a re-add. The caller's connection is committed here or rolled
    back entirely.

    ``commit=False`` runs every statement and returns the real counts WITHOUT ending
    the transaction, so the caller can ``rollback()``. It exists for the CLI's dry
    run and is the only honest way to build one: a dry run that computed its numbers
    from a separate read path would be reporting a different query than the one that
    deletes. An exception still rolls back either way.

    THE ONLY TABLE THAT SURVIVES A DELETE ELSEWHERE BUT NOT HERE is
    ``company_add_attempts``. ``remove_owned_company`` deliberately keeps it (it is
    the append-only audit of what a user pasted). This clears it on purpose: it is
    what ``services/add_quota`` counts the 20-per-month cap off, so leaving it would
    reset the boards but not the budget to re-add them, and the second test run would
    hit the cap instead of the code path under test.
    """
    scope = SCOPE_ALL if user_id is None else SCOPE_MINE
    # THE LAST GUARD, AND THE ONLY ONE INSIDE THE FUNCTION THAT DELETES. The router
    # has already checked both, but this is also called by the CLI and by tests, and
    # a "delete every user-added company" function that trusts its caller to have
    # checked is one refactor away from being called by something that did not.
    assert_local_connection(conn)
    cursor = conn.cursor()
    try:
        targets = _target_companies(cursor, user_id)
        company_ids = [str(t["id"]) for t in targets]

        # ``custom()`` rejects an id we could not have minted. Such a row cannot own
        # a ``custom:<id>`` namespace, so it contributes nothing to the job counts —
        # it is still purged below (purge_custom_company handles and logs it).
        source_ids: list[str] = []
        for company_id in company_ids:
            try:
                source_ids.append(custom(company_id))
            except ValueError:
                logger.warning(
                    "dev_reset: company %s has an id we could not have minted; it "
                    "owns no custom:<id> namespace", company_id,
                )

        deleted = _count_before(cursor, company_ids, source_ids, user_id)

        for target in targets:
            purge_custom_company(
                cursor,
                company_id=str(target["id"]),
                board_token=(
                    str(target["board_token"]) if target["board_token"] else None
                ),
                owner_user_id=(
                    str(target["owner_user_id"]) if target["owner_user_id"] else None
                ),
            )

        # Ownership and the add audit, neither of which purge_custom_company touches.
        # ``user_companies`` exists ONLY to link a user to a custom company (see
        # :class:`api.db_models.UserCompany`), so clearing the caller's rows — or the
        # whole table under scope=all — cannot reach a published board.
        if user_id is None:
            cursor.execute("DELETE FROM user_companies")
            ownership_deleted = int(cursor.rowcount or 0)
            cursor.execute("DELETE FROM company_add_attempts")
            attempts_deleted = int(cursor.rowcount or 0)
        else:
            # ``OR company_id = ANY(...)`` is the no-orphan clause. A companies row
            # is never shared today (every INSERT mints a fresh one — see
            # :class:`api.db_models.UserCompany`), but if one ever were, deleting
            # only the caller's link would leave a second user pointing at a company
            # this just destroyed: invisible in their list and blocking their re-add
            # through ``uq_user_companies_source_key``. That is the exact broken
            # state this tool exists to clear, so it must not create one.
            cursor.execute(
                "DELETE FROM user_companies WHERE user_id = %s OR company_id = ANY(%s)",
                (user_id, company_ids),
            )
            ownership_deleted = int(cursor.rowcount or 0)
            cursor.execute(
                "DELETE FROM company_add_attempts WHERE user_id = %s", (user_id,)
            )
            attempts_deleted = int(cursor.rowcount or 0)
        # The pre-counts above are the honest "how many existed"; the rowcounts are
        # the honest "how many went". They differ only for an orphaned ownership row
        # (a link whose company row was already gone), so take the larger.
        deleted["user_companies"] = max(deleted["user_companies"], ownership_deleted)
        deleted["company_add_attempts"] = max(
            deleted["company_add_attempts"], attempts_deleted
        )

        published_companies = _count(
            cursor, "SELECT count(*) AS n FROM companies WHERE visibility <> 'user'"
        )
        published_jobs = _count(
            cursor,
            "SELECT count(*) AS n FROM job_listings WHERE source_id NOT LIKE %s",
            (CUSTOM_SOURCE_PREFIX + "%",),
        )
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise

    logger.warning(
        "DEV RESET (scope=%s, user_id=%s, committed=%s): DELETED %s across %d custom "
        "company/companies %s. Left standing: %d published companies, %d "
        "non-custom job rows.",
        scope,
        user_id,
        commit,
        deleted,
        len(company_ids),
        company_ids,
        published_companies,
        published_jobs,
    )
    return ResetOutcome(
        scope=scope,
        company_ids=company_ids,
        deleted=deleted,
        published_companies_kept=published_companies,
        published_jobs_kept=published_jobs,
    )


def _count_before(
    cursor: Any,
    company_ids: list[str],
    source_ids: list[str],
    user_id: Optional[str],
) -> dict[str, int]:
    """Row counts for everything the purge is about to remove.

    Counted BEFORE rather than summed from ``cursor.rowcount`` afterwards because
    most of these rows go by cascade or by a nested predicate inside
    ``purge_custom_company``, where no rowcount is exposed to us. ``job_freshness``
    is the clearest case: nothing deletes it directly, it cascades off
    ``job_listings``, and it is exactly the number a developer wants to see.
    """
    ids = list(company_ids)
    sources = list(source_ids)
    by_source = "SELECT count(*) AS n FROM {} WHERE source_id = ANY(%s)"
    counts = {
        "companies": len(ids),
        "job_listings": _count(cursor, by_source.format("job_listings"), (sources,)),
        "job_freshness": _count(cursor, by_source.format("job_freshness"), (sources,)),
        "job_tags": _count(cursor, by_source.format("job_tags"), (sources,)),
        "job_enrichment": _count(
            cursor, by_source.format("job_enrichment"), (sources,)
        ),
        # The same NOT EXISTS the purge uses: a location link is only removed when
        # every listing carrying that id belongs to a custom source being purged.
        "job_locations": _count(
            cursor,
            """
            SELECT count(*) AS n FROM job_locations jl
            WHERE jl.job_listing_id IN (
                    SELECT id FROM job_listings WHERE source_id = ANY(%s)
                )
              AND NOT EXISTS (
                    SELECT 1 FROM job_listings o
                    WHERE o.id = jl.job_listing_id AND o.source_id <> ALL(%s)
                )
            """,
            (sources, sources),
        ),
        "company_scripts": _count(
            cursor,
            "SELECT count(*) AS n FROM company_scripts WHERE company_id = ANY(%s)",
            (ids,),
        ),
        "company_harvests": _count(
            cursor,
            "SELECT count(*) AS n FROM company_harvests WHERE company_id = ANY(%s)",
            (ids,),
        ),
        "scrape_runs": _count(
            cursor,
            "SELECT count(*) AS n FROM scrape_runs WHERE company = ANY(%s)",
            (ids,),
        ),
    }
    if user_id is None:
        counts["user_companies"] = _count(
            cursor, "SELECT count(*) AS n FROM user_companies"
        )
        counts["company_add_attempts"] = _count(
            cursor, "SELECT count(*) AS n FROM company_add_attempts"
        )
    else:
        counts["user_companies"] = _count(
            cursor,
            "SELECT count(*) AS n FROM user_companies WHERE user_id = %s",
            (user_id,),
        )
        counts["company_add_attempts"] = _count(
            cursor,
            "SELECT count(*) AS n FROM company_add_attempts WHERE user_id = %s",
            (user_id,),
        )
    return counts
