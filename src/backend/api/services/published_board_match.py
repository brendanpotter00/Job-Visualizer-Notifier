"""PUBLISHED-BOARD MATCH — "this looks like Spotify, which we already track" (E7 unit 10).

The case that actually bit: somebody pastes ``lifeatspotify.com``, we discover it, and
they end up with a private second copy of a board we have published for months. The
public row has the history; the private one starts at zero. Nobody wanted two.

**Why this module has to exist at all.** The cheap dedupe (``find_public_company_for_
candidate``) matches a pasted URL to ``(ats, board_token)`` and it provably cannot catch
this one: ``lifeatspotify.com`` resolves to no ATS, and the endpoint capture picks up is a
different feed from ``lever:spotify``. Neither the URL nor the captured request links the
two. The only remaining signal is the JOB SET — and comparing job sets is what this does.

**What it does.** After a discovered board's first UNTRUNCATED harvest: take its OPEN title
set, normalize it (:func:`normalize_title`), and intersect it against the OPEN title set of
every ``visibility='public'`` company. ~130 set intersections against rows we already hold,
once per new board. It fetches NOTHING — see the SSRF note below.

**Why "untruncated" and not "VERIFIED", which is what this originally said.** VERIFIED was
the wrong trigger for the exact case the module exists for, and it made the whole unit
unreachable for it. ``lifeatspotify.com`` returns its entire catalogue in ONE request, so
discovery stores it with ``oracle_kind='none'`` — and ``verify_harvest`` answers
``UNVERIFIED, "no_oracle"`` for that unconditionally, by design and correctly: a single
response holding 79 jobs is indistinguishable from page one of a 400-job board that never
published its length. Such a board can never verify, so it could never reach this
comparison. Measured on the live row: ``tracking_started_at`` NULL, no suggestion stored,
every harvest ``UNVERIFIED no_oracle`` — while calling :func:`find_published_match` by hand
returns ``spotify``, 70 of 79 titles, ratio 0.875, qualifying. (Re-run a day later, after
both boards moved: 69 of 79 against 82 public titles, ratio 0.841. Still 14+ points clear of
the bar, which is the point of putting the bar 50 points above the worst false pair.) Every
board in that class is affected — lifeatspotify, Atlassian, Jane Street, SpaceX, Rockstar.

The fix does NOT widen VERIFIED. VERIFIED is what licences the close sweep, and widening it
would widen what may delete a user's jobs — the guardrail around this codebase's worst
incident (a scraper returned ``[]`` and a whole board closed). Those boards stay UNVERIFIED
and still close nothing, forever. What moved is the trigger: a SUGGESTION is read-only, its
only write is one ``jsonb_set`` on the private row, and it closes nothing, so it does not
need the guarantee that gates closing. It needs a weaker and different one — that the title
set in front of it is the board's whole OPEN set — and that is
:func:`~api.services.harvest_verification.read_untruncated`: no cap hit, a clean
termination, no page-advance failure, and a verdict that is either VERIFIED or UNVERIFIED
for the one reason that means "no proof was available" rather than "the read stopped early".

**Why a partial read still must not reach here.** An UNVERIFIED harvest MAY be a partial
read, and a partial read is a wrong set: it shrinks the candidate side while the public side
stays whole. Under the old ``shared/min`` denominator that produced a spurious 100% against
any superset; under ``shared/max`` it produces the opposite error, silently missing a true
match — and because this runs ONCE, a miss is permanent. So every UNVERIFIED reason that is
or may be a short read (``cap_hit``, ``page_advance_failed``, ``not_terminated_cleanly``,
``count_mismatch``, ``delta_anomaly``, ``over_harvest``, ``zero_unproven``) is excluded from
the trigger, and so is any run the leaf task recorded FAILED — including one that failed
*after* its rows landed, which is why the task ANDs the predicate with ``success``.

**ONCE, and what now enforces it.** The old latch was implicit and free: the trigger was
"first VERIFIED harvest", and ``companies.tracking_started_at`` is stamped by that same run,
so the condition could never be true twice. A board that is never allowed to verify has no
such stamp, so the latch has to be explicit — :data:`CHECKED_KEY`, an ISO timestamp written
beside the suggestion in the same sidecar column, on the same private row, under the same
``visibility='user'`` clause. It is written ONLY when there is no match; a stored
``public_match`` is its own latch. That keeps the matching path exactly the one-key
``jsonb_set`` it already was, and it confines the new write to the case that previously
wrote nothing.

That case previously wrote nothing on purpose ("a board that stops looking like Spotify does
not need a tombstone"), and the reasoning behind it is unchanged and still enforced: this
module never writes, moves or erases the ``public_match`` key on a no-match run, so a
suggestion the user has already dealt with can neither be resurrected nor deleted by a later
run finding nothing. :data:`CHECKED_KEY` is not a tombstone for the suggestion; it is a
record that the comparison happened, and it is the only thing standing between "runs once"
and "runs a fleet-wide seq scan every night for every board forever".

**What it must never do: MERGE.** (DECISION D6, and the reason the thresholds below are
set where they are.) There is no un-merge path in this codebase, no merge audit, and no way
to reconstruct which rows came from which board — so a false merge is permanent and silent,
while a false suggestion is one dismissible banner. The asymmetry is total, so the answer is
too: two identical captured endpoints may link AT ADD TIME with the user watching; anything
this module concludes is a SUGGESTION, and the only write it is allowed to make is the
suggestion blob itself (:func:`store_suggestion`). It writes no ``job_listings`` row ever,
and touches no identity, ownership or visibility column on ``companies``.

**The thresholds.** ≥70% of the LARGER title set, with both sets ≥20 titles and ≥20 titles
actually shared. "Of the larger set" is the same statement as "of BOTH sets": ``shared/max``
is the weaker of the two containments, so clearing it means each board covers at least 70%
of the other. That two-sidedness is the whole of the point below.

**Why it is the larger set and not the smaller one — containment is not equivalence.**
``shared/min`` cannot tell the two apart. A 25-title regional or business-unit board whose
titles all appear on its 1,742-title parent scored **1.00** under it — the maximum, clearing
every rail including the shared-count one. That board is not a duplicate of its parent, it
is a SLICE of it, and "you already track this" is the wrong answer: the user asked to watch
one BU and the parent's chart is not that BU's chart. Constructed against real production
rows (25 of ``andurilindustries``' 1,742 OPEN titles): **1.0000 under ``shared/min``, 0.0144
under ``shared/max``.** The original calibration could not see this class at all — it scored
public boards only against other public boards, and production holds no parent/BU pair.

**The measurement, re-run against production under both denominators.** All 8,778 pairs of
the 133 enabled companies that have OPEN titles (25,600 distinct company×title pairs), scored
exactly the way this module scores. Over the ≥20-title floor (5,671 pairs):

* worst false pair: **20.0%** under ``shared/min``, **14.7%** under ``shared/max`` —
  ``linear`` × ``reducto``, 5 shared titles, the worst under both,
* mean 1.09% → 0.37%; p99 9.52% → 4.00%,
* **zero** pairs reach 70% under either — nothing real moves across the bar in either
  direction, so the change costs nothing measured and closes the constructed subset case,
* the most titles ANY two genuinely different companies share is **18** — below the
  absolute floor on its own.

And the true pair is untouched: Spotify is 70 shared of 81 vs 81, and when the two sets are
the same size ``min`` and ``max`` ARE the same number — **0.864 before, 0.864 after**. So 70%
is still not a knife-edge: it sits 50 points above the worst observed false pair and 16
points below the true one. The instruction the data was gathered under was "if the false
pairs cluster above 70%, raise the bar; do not lower it" — they now cluster around 0.4%, so
70% stands unchanged. See the unit-10 report for the queries.

**Why the ≥20 floors are not decoration.** Drop the set-size floor and the worst false pair
in production becomes 50.0% — ``appliedintuition`` × ``gem``, which is 2 titles out of a
4-title board. Small sets are where generic titles ("software engineer") dominate, and a
2-of-4 coincidence is exactly the shape of a suggestion nobody would trust. The floor on the
SHARED count is the second, independent rail: 18 is the most any real pair shares, so a
suggestion carrying at least 20 shared titles cannot be produced by anything we have
measured, whatever the ratio says. What neither floor catches is the subset case — the
constructed 25-of-1,742 pair shares 25 titles and clears both comfortably. Only the
denominator catches that one, which is why it is the denominator that changed.

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

#: Fraction of the LARGER title set that must match — equivalently, of BOTH sets. 70%: the
#: measured true pair sits at 86%, the worst measured false pair at 14.7%.
OVERLAP_THRESHOLD = 0.70

#: Both title sets must have at least this many distinct titles. Without it the worst
#: production false pair is a 2-of-4 coincidence at 50%.
MIN_TITLE_SET = 20

#: And at least this many titles must actually be shared. An independent rail: 18 is the
#: most any two genuinely different production companies share.
MIN_SHARED_TITLES = 20

#: The ``provider_config`` key the suggestion is stored under.
SUGGESTION_KEY = "public_match"

#: The ``provider_config`` key that records "this board has already been compared", set
#: to an ISO timestamp. It exists ONLY to make :func:`suggest_published_board` run once
#: per board — see the ONCE section of the module docstring for why the old latch
#: (``companies.tracking_started_at``, stamped on the first VERIFIED harvest) cannot
#: serve a board that is never allowed to verify. Written on the NO-MATCH path only:
#: a stored ``public_match`` is its own latch, so the matching path is byte-for-byte
#: the single ``jsonb_set`` it always was.
CHECKED_KEY = "public_match_checked_at"

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

    ``ratio`` is the intersection over the LARGER of the two sets, which is the same thing as
    the WEAKER of the two containments: ``ratio >= t`` iff each set is at least ``t`` covered
    by the other. That symmetry is the whole point. Over the smaller set (what this used to
    be) a 25-title BU board sitting entirely inside its 1,742-title parent scores a perfect
    1.00, because one-sided containment is indistinguishable from equivalence — and a slice
    of a board is not that board. Over the larger set the same pair scores 0.014, while the
    measured Spotify pair (81 vs 81) is unchanged at 0.864, because the two denominators
    coincide exactly when the sets are the same size.

    Not Jaccard, which would put Spotify at 0.761 — only 6 points over the bar, close enough
    to a knife-edge that a few titles' scrape drift decides the banner. ``shared/max`` gets
    the same two-sidedness while leaving the calibrated bar where the evidence put it.

    The three EVIDENCE counts are kept separate from the score and are what the banner's
    sentence is built from: "70 of 81 roles on this board match" is ``shared`` over
    ``candidate_titles``, an honestly one-sided sentence about the board the user is looking
    at. The score is what decides whether that sentence is shown at all.
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
    larger = max(len(candidate), len(other))
    return BoardOverlap(
        company_id=company_id,
        display_name=display_name,
        shared=shared,
        candidate_titles=len(candidate),
        matched_titles=len(other),
        # LARGER, not smaller — see ``BoardOverlap``. A zero-length set can only produce a
        # zero-length intersection; 0/0 is 0.0 here, and the MIN_TITLE_SET rail rejects it
        # anyway.
        ratio=(shared / larger) if larger else 0.0,
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

    A stored suggestion is also its own ONCE-latch (see :func:`_already_compared`), which is
    why this still writes exactly one key and did not have to grow a second.
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


def _already_compared(conn: Connection, company_id: str) -> bool:
    """Has this board already been compared against the boards we publish? **READ-ONLY.**

    The ONCE-latch, in one PK lookup. Two keys satisfy it, and the order matters:

    * :data:`SUGGESTION_KEY` — we already told this user something. Re-running could only
      overwrite that with a fresh ``detected_at``, or replace it with a different company,
      neither of which the user asked for.
    * :data:`CHECKED_KEY` — we compared and found nothing.

    A row with NEITHER has never been compared, which includes every board that graduated
    before this latch existed. Those get exactly one comparison on their next untruncated
    harvest and are then latched like everything else — a one-time backfill, self-limiting,
    and the safe direction (the alternative is boards that can never be compared at all).

    ``visibility = 'user'`` is on the read for the same reason it is on the write: this
    module has business only with private rows, and a contrived id must not be able to make
    it read (or later write) a published company's config.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT provider_config
        FROM companies
        WHERE id = %s AND visibility = 'user'
        """,
        (company_id,),
    )
    row = cursor.fetchone()
    if row is None:
        # Not a private row (or gone). Nothing here may write to it either, so refusing to
        # compare is both the safe answer and the honest one.
        return True
    config = row["provider_config"]
    if not isinstance(config, Mapping):
        return False
    return SUGGESTION_KEY in config or CHECKED_KEY in config


def _mark_compared(conn: Connection, company_id: str) -> bool:
    """Latch a NO-MATCH comparison so it never runs again. Returns whether it landed.

    Deliberately the same shape as :func:`store_suggestion` — one ``jsonb_set`` of one key
    on one row, ``WHERE id = %s AND visibility = 'user'``, no other column touched, no
    INSERT, no DELETE, and nothing written to ``job_listings``. It differs in exactly one
    respect: the key it sets is :data:`CHECKED_KEY`, never :data:`SUGGESTION_KEY`, so a
    run that finds nothing cannot resurrect, overwrite or erase a suggestion the user has
    already dealt with. That property is what the no-tombstone rule was actually protecting,
    and it is preserved here rather than traded away.
    """
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
            (
                "{" + CHECKED_KEY + "}",
                json.dumps(datetime.now(timezone.utc).isoformat()),
                company_id,
            ),
        )
        updated = cursor.rowcount
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise
    return bool(updated)


def suggest_published_board(conn: Connection, company_id: str) -> Optional[BoardOverlap]:
    """Compare, and store the suggestion if there is one. The harvest task's single entry.

    Called after a board's first UNTRUNCATED harvest — the first run whose OPEN set is the
    board's whole OPEN set, which is the only kind of set worth comparing. NOT the first
    VERIFIED harvest: a board that returns its whole catalogue in one request can never
    verify, and gating on VERIFIED made this unreachable for exactly the case the module was
    written for. The trigger and the reasoning are argued in full in the module docstring;
    :func:`~api.services.harvest_verification.read_untruncated` is the predicate, and the
    caller (``fetch_custom_company``) is where it is evaluated.

    **ONCE**, and this function owns it. It returns ``None`` without so much as scoring if
    the board has already been compared, so the caller may hand it every untruncated run
    without the comparison ever repeating. The two guards are independent on purpose: the
    caller decides whether a run is COMPARABLE, this decides whether the board has already
    BEEN compared, and neither can be defeated by getting the other wrong.

    Returns the match for the caller to log. A no-match writes only the :data:`CHECKED_KEY`
    latch: never the suggestion key, so a suggestion that was already stored and dismissed
    can neither be resurrected nor erased by a later run finding nothing.
    """
    if _already_compared(conn, company_id):
        logger.debug(
            "published_board_match: %s has already been compared; skipping", company_id
        )
        return None
    match = find_published_match(conn, company_id)
    if match is None:
        _mark_compared(conn, company_id)
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
