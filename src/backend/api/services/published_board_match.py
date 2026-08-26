"""PUBLISHED-BOARD MATCH — "this looks like Spotify, which we already track" (E7 unit 10).

The case that actually bit: somebody pastes ``lifeatspotify.com``, we discover it, and
they end up with a private second copy of a board we have published for months. The
public row has the history; the private one starts at zero. Nobody wanted two.

**Why this module has to exist at all.** The cheap dedupe (``find_public_company_for_
candidate``) matches a pasted URL to ``(ats, board_token)`` and it provably cannot catch
this one: ``lifeatspotify.com`` resolves to no ATS, and the endpoint capture picks up is a
different feed from ``lever:spotify``. Neither the URL nor the captured request links the
two. The only remaining signal is the JOB SET — and comparing job sets is what this does.

**What it does.** After a discovered board's FIRST VERIFIED harvest: take its OPEN title
set, normalize it (:func:`normalize_title`), and intersect it against the OPEN title set of
every ``visibility='public'`` company. ~130 set intersections against rows we already hold,
once per new board. It fetches NOTHING — see the SSRF note below.

**What it must never do: MERGE.** (DECISION D6, and the reason the thresholds below are
set where they are.) There is no un-merge path in this codebase, no merge audit, and no way
to reconstruct which rows came from which board — so a false merge is permanent and silent,
while a false suggestion is one dismissible banner. The asymmetry is total, so the answer is
too: two identical captured endpoints may link AT ADD TIME with the user watching; anything
this module concludes is a SUGGESTION, and the only write it is allowed to make is the
suggestion blob itself (:func:`store_suggestion`). It writes no ``job_listings`` row ever,
and touches no identity, ownership or visibility column on ``companies``.

**The thresholds, and the measurement behind them.** ≥70% of the smaller title set, with
both sets ≥20 titles and ≥20 titles actually shared. The 70% bar started life on n=1 — the
measured Spotify pair, 70 of 81 unique OPEN titles (86%) — which is not enough evidence for
a bar, so it was checked against every FALSE pair we have. All 9,045 pairs of the 135
companies in production, scored exactly the way this module scores:

* the worst false pair clearing the ≥20-title floor reaches **20.0%** (``linear`` ×
  ``reducto``, 5 shared titles),
* mean 1.08%, p99 9.52%,
* **zero** pairs reach even 30%, let alone 50 / 70 / 80,
* the most titles ANY two genuinely different companies share is **18** — below the
  absolute floor on its own.

So 70% is not a knife-edge: it sits 50 points above the worst observed false pair, and the
true positive sits 16 points above it. The instruction the data was gathered under was
"if the false pairs cluster above 70%, raise the bar; do not lower it" — they cluster around
1%, so 70% stands unchanged. See the unit-10 report for the queries.

**Why the ≥20 floors are not decoration.** Drop the set-size floor and the worst false pair
in production becomes 50.0% — ``appliedintuition`` × ``gem``, which is 2 titles out of a
4-title board. Small sets are where generic titles ("software engineer") dominate, and a
2-of-4 coincidence is exactly the shape of a suggestion nobody would trust. The floor on the
SHARED count is the second, independent rail: 18 is the most any real pair shares, so a
suggestion carrying at least 20 shared titles cannot be produced by anything we have
measured, whatever the ratio says.

**SSRF, explicitly** (it is on the invariant register): this module issues no outbound
request of any kind and imports no HTTP client. It compares rows already in our database.
The moment it fetches a public board to compare, it becomes a new outbound surface on a path
that runs unattended — so it does not.

**Where the suggestion is stored — ``companies.provider_config -> 'public_match'``, and NO
migration.** That column is ``JSONB NOT NULL DEFAULT '{}'`` and is already the established
sidecar for exactly this kind of display-only, company-scoped blob: the discovery checklist
lives beside it under ``'discovery'`` (see :mod:`api.services.discovery.progress`, which
argues the choice at length), the harvest task already writes into it once per run
(``record_first_scan``), and ``list_owned_companies`` already ships the whole column to the
frontend on the poll the My-Companies list is already running. The write is a ``jsonb_set``
of one key, so it can never clobber a sibling one.
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

import psycopg2
from psycopg2.extensions import connection as Connection

from scripts.shared.constants import custom

logger = logging.getLogger(__name__)

# --- The bar ----------------------------------------------------------------------
# Every number here is argued from the production pairwise measurement in the module
# docstring. Raising them is cheap (a suggestion nobody sees); lowering them is not.

#: Fraction of the SMALLER title set that must match. 70%: the measured true pair sits at
#: 86%, the worst measured false pair at 20%.
OVERLAP_THRESHOLD = 0.70

#: Both title sets must have at least this many distinct titles. Without it the worst
#: production false pair is a 2-of-4 coincidence at 50%.
MIN_TITLE_SET = 20

#: And at least this many titles must actually be shared. An independent rail: 18 is the
#: most any two genuinely different production companies share.
MIN_SHARED_TITLES = 20

#: The ``provider_config`` key the suggestion is stored under.
SUGGESTION_KEY = "public_match"

#: Everything that is not a letter or a digit collapses to a single space, so
#: ``Client Partner, Emerging & Scaled`` and ``Client Partner - Emerging and...`` differ
#: only where the WORDS differ. Unicode-aware (``\w`` minus ``_``) so an accented title
#: does not shred into single letters.
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def normalize_title(title: Any) -> str:
    """One job title, reduced to the form two boards can be compared on.

    HTML-unescape → casefold → non-word runs to single spaces → strip.

    **The unescape is load-bearing and it is why unit 3 was a dependency.** A discovered
    board hands us whatever its page markup carried, so 19 of Spotify's 85 titles arrive as
    ``Client Partner, Emerging &amp; Scaled``. Comparing those against a Lever board that
    spells the same title with a bare ``&`` silently misses: it measured the Spotify overlap
    at 56/81 instead of 70/81 — 14 points, enough to move a pair from over the bar to under
    it. Unit 3 fixed the STORED value going forward; this unescape is the belt to that
    braces, because the public rows were written by six different ATS clients over two years
    and nothing re-wrote them.

    ``casefold`` rather than ``lower``: it is the case-insensitive-comparison operation,
    and it costs nothing here.

    Total by contract — a non-string (a NULL title reaching us as ``None``) returns ``''``,
    which callers drop. Nothing about a job title should be able to raise on a path that
    runs unattended after every first harvest.
    """
    if not isinstance(title, str):
        return ""
    return _NON_WORD.sub(" ", html.unescape(title)).casefold().strip()


def title_set(titles: Iterable[Any]) -> frozenset[str]:
    """The distinct normalized titles in ``titles``, empties dropped.

    A SET, deliberately: 40 openings for "Software Engineer" is one title's worth of
    evidence that two boards are the same board, not forty. Counting multiplicity would let
    a single high-volume req dominate the comparison.
    """
    return frozenset(filter(None, (normalize_title(t) for t in titles)))


@dataclass(frozen=True)
class BoardOverlap:
    """A scored candidate-vs-published comparison. Carries the evidence, not just a verdict.

    ``ratio`` is the intersection over the SMALLER of the two sets — not Jaccard. A board we
    read completely and a 4,000-role megacorp that happens to contain it are the same board
    from the user's point of view, and Jaccard would score that near zero purely because one
    side is bigger. The smaller set is also the honest denominator for the sentence the user
    reads: "70 of 81 roles match".
    """

    company_id: str
    display_name: str
    shared: int
    candidate_titles: int
    matched_titles: int
    ratio: float

    @property
    def qualifies(self) -> bool:
        """Does this clear every rail? All three, ANDed — see the module docstring.

        **One honest note about the first rail.** At today's values the shared-count floor
        SUBSUMES the set-size floor: ``shared >= 20`` cannot hold unless both sets already
        have 20 titles, so no input exists that the set floor alone rejects, and there is
        therefore no test that isolates it (the mutation harness confirms it — a mutant
        that weakens it survives). It is kept anyway, deliberately: it is the rail the plan
        specifies ("≥70% of the smaller set, minimum 20 titles"), and it is the one that
        starts binding again the moment either of the other two moves — drop
        ``OVERLAP_THRESHOLD`` to 0.5 and a 30-title board at 50% is 15 shared, which the
        set floor still admits and the shared floor still refuses. Naming all three keeps
        the bar readable as three separate claims instead of one collapsed number.
        """
        return (
            min(self.candidate_titles, self.matched_titles) >= MIN_TITLE_SET
            and self.shared >= MIN_SHARED_TITLES
            and self.ratio >= OVERLAP_THRESHOLD
        )


def score_overlap(
    candidate: frozenset[str],
    other: frozenset[str],
    *,
    company_id: str,
    display_name: str,
) -> BoardOverlap:
    """Score one pair. PURE — no database, no clock, no I/O. The unit under test."""
    shared = len(candidate & other)
    smaller = min(len(candidate), len(other))
    return BoardOverlap(
        company_id=company_id,
        display_name=display_name,
        shared=shared,
        candidate_titles=len(candidate),
        matched_titles=len(other),
        # A zero-length set can only produce a zero-length intersection; 0/0 is 0.0 here,
        # and the MIN_TITLE_SET rail rejects it anyway.
        ratio=(shared / smaller) if smaller else 0.0,
    )


def _open_titles_for_custom_company(conn: Connection, company_id: str) -> frozenset[str]:
    """The discovered board's OPEN titles.

    Scoped by ``source_id = 'custom:<id>'`` as well as ``company``, matching every other
    per-company custom read: the namespace is the key the rows are actually written under,
    and ``custom()`` validates the id shape before it reaches a WHERE clause.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT title
        FROM job_listings
        WHERE company = %s AND source_id = %s AND status = 'OPEN'
        """,
        (company_id, custom(company_id)),
    )
    return title_set(row["title"] for row in cursor.fetchall())


def _open_titles_by_public_company(
    conn: Connection,
) -> dict[str, tuple[str, frozenset[str]]]:
    """``{company_id: (display_name, titles)}`` for every ENABLED public company.

    One query for all ~130 of them rather than 130 queries: the whole comparison is meant to
    cost one round-trip and a few hundred milliseconds of set arithmetic, once per new
    board, and a per-company loop would turn it into the kind of thing somebody later feels
    the need to schedule. Measured against production (135 companies, 32,031 OPEN rows,
    25,936 distinct company×title pairs): **98 ms**, a hash join over one seq scan of
    ``job_listings``. Unindexed and deliberately so — it reads a third of the table, which is
    what a seq scan is for, and it runs once in a board's lifetime.

    ``enabled`` is part of the filter for the same reason unit 9 has it: a disabled public
    row is a board we have STOPPED reading, and suggesting somebody swap their live private
    copy for a chart that no longer updates is worse than saying nothing.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT c.id, c.display_name, j.title
        FROM companies c
        JOIN job_listings j ON j.company = c.id
        WHERE c.visibility = 'public' AND c.enabled AND j.status = 'OPEN'
        """
    )
    raw: dict[str, tuple[str, set[str]]] = {}
    for row in cursor.fetchall():
        normalized = normalize_title(row["title"])
        if not normalized:
            continue
        name, titles = raw.setdefault(row["id"], (row["display_name"] or row["id"], set()))
        titles.add(normalized)
    return {cid: (name, frozenset(titles)) for cid, (name, titles) in raw.items()}


def find_published_match(conn: Connection, company_id: str) -> Optional[BoardOverlap]:
    """The published company this board looks like, or None. **READ-ONLY.**

    Two SELECTs and some set arithmetic. It writes nothing, anywhere — that is asserted by
    a test that traps every statement the connection executes, because "this function does
    not write" is the D6 guarantee and a comment is not a guarantee.

    Returns the BEST-scoring qualifying match. Best, not first: a discovered board that
    clears the bar against two public companies is a board whose titles are generic enough
    that the runner-up is noise, and showing the strongest of the two is the only defensible
    choice when we are allowed to show at most one banner.
    """
    candidate = _open_titles_for_custom_company(conn, company_id)
    if len(candidate) < MIN_TITLE_SET:
        # Cheap exit before the fleet-wide read: nothing this small can qualify.
        return None

    best: Optional[BoardOverlap] = None
    for public_id, (display_name, titles) in _open_titles_by_public_company(conn).items():
        scored = score_overlap(
            candidate, titles, company_id=public_id, display_name=display_name
        )
        if not scored.qualifies:
            continue
        if best is None or scored.ratio > best.ratio:
            best = scored
    return best


def read_suggestion(provider_config: Any) -> Optional[dict[str, Any]]:
    """The suggestion inside a ``companies.provider_config``, normalized, or None.

    TOTAL BY CONTRACT, exactly like ``discovery.progress.read_progress`` and for the same
    reason: the caller is ``GET /api/users/companies``, the one endpoint the My-Companies
    list cannot live without, and the input is a JSONB column that may hold an ATS provider
    config (no ``public_match`` key → ``None``), a blob written by an older deployment, or
    whatever an operator typed. Nothing in here raises; an unrecognised shape degrades to
    ``None`` (the row renders exactly as it did before this shipped).

    A blob missing the two fields the banner's sentence is built from — the company it
    matched and how many titles matched — is not renderable, so it reads back as ``None``
    rather than as a banner with a hole in it.
    """
    if not isinstance(provider_config, Mapping):
        return None
    raw = provider_config.get(SUGGESTION_KEY)
    if not isinstance(raw, Mapping):
        return None

    company_id = raw.get("company_id")
    display_name = raw.get("display_name")
    if not isinstance(company_id, str) or not company_id:
        return None
    if not isinstance(display_name, str) or not display_name:
        return None

    shared = _non_negative_int(raw.get("shared"))
    candidate_titles = _non_negative_int(raw.get("candidate_titles"))
    if shared is None or candidate_titles is None:
        return None

    detected_at = raw.get("detected_at")
    return {
        "company_id": company_id,
        "display_name": display_name,
        "shared": shared,
        "candidate_titles": candidate_titles,
        "detected_at": detected_at if isinstance(detected_at, str) else None,
    }


def _non_negative_int(value: Any) -> Optional[int]:
    """``value`` as a count, or None. Bools are not counts (``isinstance(True, int)``)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def store_suggestion(conn: Connection, company_id: str, match: BoardOverlap) -> bool:
    """Write the suggestion onto the discovered company's own row. Returns whether it landed.

    **The only write in this module, and the whole of D6's blast radius.** It is a
    ``jsonb_set`` of ONE key on ONE row, and everything about it is deliberately narrow:

    * ``WHERE id = %s AND visibility = 'user'`` — it can only ever touch the private row
      that was just harvested. The visibility clause means a contrived id can never point
      this write at a published company.
    * ``jsonb_set``, not a whole-column write, so it cannot clobber the ``discovery``
      checklist sitting beside it (or any key a later feature adds).
    * It sets ``provider_config`` and NOTHING else — no identity column, no ownership, no
      visibility, no ``enabled``. There is no INSERT and no DELETE anywhere in this module,
      and ``job_listings`` is never written at all.

    That is a suggestion, not a merge, and it is the difference the whole unit turns on.
    """
    payload = {
        "company_id": match.company_id,
        "display_name": match.display_name,
        "shared": match.shared,
        "candidate_titles": match.candidate_titles,
        "matched_titles": match.matched_titles,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE companies
            SET provider_config = jsonb_set(
                provider_config, %s, %s::jsonb, true
            )
            WHERE id = %s AND visibility = 'user'
            """,
            ("{" + SUGGESTION_KEY + "}", json.dumps(payload), company_id),
        )
        updated = cursor.rowcount
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise
    return bool(updated)


def suggest_published_board(conn: Connection, company_id: str) -> Optional[BoardOverlap]:
    """Compare, and store the suggestion if there is one. The harvest task's single entry.

    Called once, after a board's FIRST VERIFIED harvest — the first moment its OPEN set is
    both complete and proven complete, which is the only kind of set worth comparing. An
    UNVERIFIED harvest may be a partial read of the board, and a partial read is exactly how
    you get a spurious 100% against something it is a subset of.

    Returns the match for the caller to log. NO match writes nothing at all: a board that
    stops looking like Spotify does not need a tombstone, and a suggestion that was already
    stored and dismissed must not be resurrected by a later run finding nothing.
    """
    match = find_published_match(conn, company_id)
    if match is None:
        return None
    store_suggestion(conn, company_id, match)
    logger.info(
        "published_board_match: %s looks like public company %s "
        "(%d of %d titles, %.0f%%) — suggestion stored, NOTHING merged",
        company_id,
        match.company_id,
        match.shared,
        match.candidate_titles,
        match.ratio * 100,
    )
    return match
