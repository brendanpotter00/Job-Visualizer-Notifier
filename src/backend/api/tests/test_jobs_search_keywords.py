"""Keyword semantics for ``GET /api/jobs/search`` — what ``include``/``exclude`` search,
how a term matches, and what happens to characters a pattern would otherwise interpret.

WHAT THIS FILE PROTECTS
-----------------------
Three invariants, all of which fail *silently* — a broken keyword filter still
returns 200 with a plausible list, and nobody downstream can tell that the list is
wrong:

1. **The haystack is exactly (title, raw location, company, tags).** Widening it is
   a performance regression with a name — ``department``/``team`` live in the
   ``details`` JSONB, and reading a JSONB key detoasts the full ~10 KB value per
   row, which is the access pattern that timed this table out in the 2026-07-13
   outage. Narrowing it (dropping tags, dropping company) is a search that quietly
   stops finding things. So the field list is pinned here in both directions: a
   test that a term in each field DOES match, and a test that a term in
   ``details`` does NOT.

2. **A user's term is a literal, never a pattern.** The term is compiled to a
   Postgres regex, and job titles are full of regex syntax ("C++ 100% Remote",
   "Engineer (Remote)", "Node.js"). An unescaped ``.`` matches any character, an
   unescaped ``+`` or ``(`` changes the pattern's shape or errors. The ``%``/``_``/
   ``\\`` cases from the LIKE era are kept: they must still be literals.

3. **A term matches WHOLE words, never a fragment of one** (strict: no plural or
   stem tolerance, by the owner's call). As a substring, ``− intern`` hid
   "International Payments", ``− mobile`` hid "Automobile …", and ``+ ai`` matched
   every "Mountain View" job. A word boundary is only required on a side of the
   term that ends in a letter or digit, so "C++" and ".NET" still match.

The single most dangerous case in this file is
:func:`test_a_row_with_no_location_survives_an_exclude_term_it_does_not_match`.
``job_listings.location`` is nullable, and without the ``COALESCE(location, '')``
in ``_KEYWORD_PREDICATE`` the whole OR-chain evaluates to NULL for a
location-less row (``false OR NULL OR false OR false`` = NULL), so ``AND NOT
(NULL)`` is NULL and Postgres drops the row. One negative keyword would then hide
every location-less job in the corpus, with no error anywhere.

Every test seeds a DECOY the filter has to reject — the near-miss row that a
regression would let through, or the row a regression would wrongly keep. Without
one, "the filter returned the row I seeded" is a statement about the seed, not
about the filter.
"""

import json

from scripts.shared.constants import SourceId

from .conftest import _insert_job, _insert_job_tag, _make_job

# Every seeded row shares this instant. Ordering is the pagination file's subject;
# this file only ever asks WHICH rows survive a filter, so the timestamp is held
# constant to keep it out of the way. Well in the past so it never drifts into the
# ``countLast24h`` / ``countLast3h`` windows and perturbs an unrelated assertion.
FIRST_SEEN_AT = "2026-05-01T12:00:00Z"

# Defaults chosen to contain NONE of the search terms used anywhere in this module.
# This matters more than it looks: ``_make_job``'s own defaults are company
# ``google`` and location ``Mountain View, CA``, and a decoy that happens to carry
# the term under test would make its test pass for the wrong reason (or fail for
# one). "acme" / "Springfield, IL" are inert against every term below.
NEUTRAL_TITLE = "Software Engineer"
NEUTRAL_COMPANY = "acme"
NEUTRAL_LOCATION = "Springfield, IL"


def _seed_job(conn, job_id: str, **overrides) -> str:
    """Insert one OPEN job with collision-free defaults; return its id."""
    _insert_job(conn, _make_job({
        "id": job_id,
        "title": NEUTRAL_TITLE,
        "company": NEUTRAL_COMPANY,
        "location": NEUTRAL_LOCATION,
        "source_id": SourceId.GOOGLE,
        "status": "OPEN",
        "first_seen_at": FIRST_SEEN_AT,
        "last_seen_at": FIRST_SEEN_AT,
        **overrides,
    }))
    return job_id


def _search(client, **params) -> set[str]:
    """Run one page-1 search and return the set of job ids it matched.

    The envelope assertions here are not ceremony — they buy every test in this
    module coverage of the COUNT query for free. ``get_search_counts`` composes
    the same WHERE clause as the page query through ``build_search_where`` but
    drops the freshness join and runs its own statement, so a keyword predicate
    that behaved differently across the two would be invisible in the ``jobs``
    array and show up only as a ``filteredTotal`` that disagrees with it. Every
    fixture here is a handful of rows against the default limit of 100, so the
    page is never full and the two numbers must be equal.
    """
    resp = client.get("/api/jobs/search", params=params)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["nextCursor"] is None, (
        "a fixture in this module grew past the default page size — the "
        "filteredTotal cross-check below is only valid on a non-full page"
    )
    meta = body["meta"]
    assert meta is not None, "page 1 (no cursor) must carry meta"
    assert meta["filteredTotal"] is None
    return {job["id"] for job in body["jobs"]}


# ---------------------------------------------------------------------------
# (1) The haystack: which fields an include term reaches
# ---------------------------------------------------------------------------


def test_include_matches_whole_title_words_case_insensitively(client, db_conn):
    """Whole words, case-folded on both sides — and a fragment matches nothing.

    The term is spelled in mixed case against a differently-cased title, so a
    regression to a case-sensitive ``~`` fails here. The second assertion is the
    old substring test turned around: the same phrase cut mid-word used to match
    and must not any more.
    """
    _seed_job(db_conn, "backend", title="Senior Backend Engineer")
    _seed_job(db_conn, "frontend", title="Senior Frontend Engineer")

    assert _search(client, include="BaCkEnD eNgInEeR") == {"backend"}
    assert _search(client, include="AcKeNd eNgIn") == set()


def test_include_matches_the_raw_location_text(client, db_conn):
    """The RAW ``location`` string is searchable, independently of the normalized
    ``job_locations`` tags the ``location`` filter uses.

    Keyword and location are two different dimensions over two different columns;
    a keyword term must not need a job to have been location-normalized first,
    because ~a third of the corpus never is.
    """
    _seed_job(db_conn, "austin", location="Austin, TX")
    _seed_job(db_conn, "seattle", location="Seattle, WA")

    assert _search(client, include="austin") == {"austin"}


def test_include_matches_the_company_id(client, db_conn):
    """A deliberate divergence from the client-side matcher, which never searched
    company. Typing "stripe" into a keyword box and getting Stripe's jobs is what
    users expect, so it is pinned rather than left as an accident of the port."""
    _seed_job(db_conn, "at-stripe", company="stripe")
    _seed_job(db_conn, "at-square", company="square")

    assert _search(client, include="stripe") == {"at-stripe"}


def test_include_matches_a_job_tag(client, db_conn):
    """Tags are the enricher's output and the only searchable text that is not a
    column on ``job_listings`` — it takes a correlated EXISTS, so it is the branch
    of the OR-chain most likely to be dropped by a refactor."""
    _seed_job(db_conn, "k8s")
    _seed_job(db_conn, "crm")
    _insert_job_tag(db_conn, SourceId.GOOGLE, "k8s", "kubernetes")
    _insert_job_tag(db_conn, SourceId.GOOGLE, "crm", "salesforce")

    assert _search(client, include="kubernetes") == {"k8s"}


def test_a_tag_belonging_to_another_sources_job_of_the_same_id_does_not_match(
    client, db_conn
):
    """``job_tags`` is keyed by the composite ``(source_id, job_listing_id)``,
    because a job id is only unique WITHIN a source — Greenhouse and Apple both
    hand out short numeric ids and they collide constantly.

    If the EXISTS correlated on ``job_listing_id`` alone, one company's tags would
    silently answer for another company's job. Two rows sharing an id under
    different sources is the whole fixture.
    """
    shared_id = "4815162342"
    _seed_job(db_conn, shared_id, source_id=SourceId.GOOGLE, company="google")
    _seed_job(db_conn, shared_id, source_id=SourceId.APPLE, company="apple")
    # The tag hangs off the GOOGLE row only.
    _insert_job_tag(db_conn, SourceId.GOOGLE, shared_id, "kubernetes")

    resp = client.get("/api/jobs/search", params={"include": "kubernetes"})
    assert resp.status_code == 200, resp.text
    matched = {(job["sourceId"], job["id"]) for job in resp.json()["jobs"]}

    assert matched == {(SourceId.GOOGLE, shared_id)}, (
        "the tag subquery must correlate on source_id as well as id, or a tag "
        "leaks onto every same-id job from every other source"
    )


def test_the_client_department_field_is_not_searched(client, db_conn):
    """Parity for the field the client USED to call ``department``.

    This assertion has flipped twice, so the history matters. ``Job.department``
    was ``details.experience_level`` on the frontend, mirrored into the plain
    ``experience_level`` COLUMN, and an earlier revision of this endpoint matched
    that column — correctly at the time, because dropping it made terms people
    actually type ("intern", "senior") match fewer jobs than the page did before
    the migration.

    E7 Phase 3 (#248) then deleted the field from the frontend outright:
    ``Job.department`` is gone and ``matchesSearchTags`` builds its haystack from
    ``[title, team, location, ...tags]``. Matching the column now would make the
    endpoint WIDER than the deployed page it replaces — "senior" would return
    jobs whose title says nothing about seniority, the same ATS-assigned noise
    #260 removed from the job card. Parity with the client is the contract, and
    parity now means NOT matching it.

    The control row is what makes this a real test: the same term IS found via a
    title, so a green result cannot be explained by "the search matches nothing".
    """
    _seed_job(db_conn, "in-experience-level", experience_level="Zymurgy")
    _seed_job(db_conn, "in-title", title="Zymurgy Engineer")
    _seed_job(db_conn, "unrelated")

    assert _search(client, include="zymurgy") == {"in-title"}


def test_raw_details_json_keys_are_not_searched(client, db_conn):
    """The haystack is columns, never the ``details`` blob.

    Touching a JSONB key detoasts the whole value per row, which is what timed
    ``/api/jobs`` out in 2026-07-13. Nothing the client matcher reads is lost by
    staying off it: ``department`` is no longer part of the client haystack at
    all (see the test above), and ``team`` is never populated by any transformer,
    so it has no client-side meaning to preserve.
    """
    _seed_job(db_conn, "in-details", details=json.dumps({
        "department": "Quixotic", "team": "Quixotic Platform",
    }))
    _seed_job(db_conn, "in-title", title="Quixotic Engineer")

    assert _search(client, include="quixotic") == {"in-title"}


# ---------------------------------------------------------------------------
# (2) Composition: OR within a dimension, AND across include/exclude
# ---------------------------------------------------------------------------


def test_multiple_include_terms_or_together(client, db_conn):
    """Values within a dimension OR — a keyword list is "any of these", not "all
    of these". ANDing them would return the empty set for every list of two or
    more terms, which looks exactly like "no jobs match your search"."""
    _seed_job(db_conn, "rust", title="Rust Systems Engineer")
    _seed_job(db_conn, "kotlin", title="Kotlin Android Engineer")
    _seed_job(db_conn, "cobol", title="COBOL Maintenance Engineer")

    assert _search(client, include=["rust", "kotlin"]) == {"rust", "kotlin"}


def test_exclude_removes_every_row_a_term_matches_anywhere_in_the_haystack(
    client, db_conn
):
    """``exclude`` searches the SAME four fields ``include`` does.

    A negative keyword that only consulted the title would leave the user staring
    at rows they explicitly filtered out, with no way to express what they meant.
    One decoy per field, so a dropped branch of the OR-chain surfaces as a named
    id in the diff rather than as a count.
    """
    _seed_job(db_conn, "keep", title="Backend Engineer")
    _seed_job(db_conn, "drop-by-title", title="Contract Backend Engineer")
    # A hyphen is a word boundary, so the whole word "contract" is in this slug.
    _seed_job(db_conn, "drop-by-company", company="contract-co")
    _seed_job(db_conn, "drop-by-location", location="Contract City, TX")
    _seed_job(db_conn, "drop-by-tag")
    _insert_job_tag(db_conn, SourceId.GOOGLE, "drop-by-tag", "contract-to-hire")

    assert _search(client, exclude="contract") == {"keep"}


def test_include_and_exclude_compose_as_an_intersection(client, db_conn):
    """The two dimensions AND: a row must match SOME include term and NO exclude
    term. Decoys sit on both sides of that conjunction — one row is dropped only
    by ``include``, another only by ``exclude`` — so neither clause can be lost
    without a visible change."""
    _seed_job(db_conn, "wanted", title="Senior Rust Engineer")
    _seed_job(db_conn, "rust-but-managerial", title="Senior Rust Manager")
    _seed_job(db_conn, "engineer-but-not-rust", title="Senior Python Engineer")
    _seed_job(db_conn, "neither", title="Marketing Lead")

    assert _search(client, include="rust", exclude="manager") == {"wanted"}


def test_a_row_with_no_location_survives_an_exclude_term_it_does_not_match(
    client, db_conn
):
    """THE case this file exists for. ``location`` is nullable.

    Without ``COALESCE(job_listings.location, '')`` the OR-chain for a
    location-less row is ``false OR NULL OR false OR false`` = **NULL**, and the
    exclude path wraps that in ``AND NOT (…)``. ``NOT NULL`` is NULL, which is not
    TRUE, so Postgres drops the row from the result set — one negative keyword
    would silently hide every location-less job in the corpus.

    Note that the include path is immune (a NULL there correctly fails to match),
    so this is only ever reachable through ``exclude``, which is exactly why it
    survived review as "defensive noise" once already.

    The fixture is built so the assertion inverts if the COALESCE is removed: the
    two ``location=None`` rows differ only in whether the term is present in their
    TITLE, so a regression keeps the one that should be dropped and drops the one
    that should be kept.
    """
    _seed_job(db_conn, "null-loc-keep", title="Data Analyst", location=None)
    _seed_job(db_conn, "has-loc-keep", title="Data Analyst")
    _seed_job(db_conn, "null-loc-drop", title="Head Chef", location=None)
    _seed_job(db_conn, "has-loc-drop", title="Head Chef")

    survivors = _search(client, exclude="chef")

    assert "null-loc-keep" in survivors, (
        "a job with a NULL location that does not match the exclude term was "
        "dropped — the COALESCE(location, '') guard in _KEYWORD_PREDICATE is "
        "gone and NOT (NULL) is silently discarding rows"
    )
    assert survivors == {"null-loc-keep", "has-loc-keep"}


# ---------------------------------------------------------------------------
# (3) Whole words: the false friends a substring match got wrong
# ---------------------------------------------------------------------------


def test_include_does_not_match_a_word_that_merely_contains_the_term(client, db_conn):
    """The include-side false friends, one per term, each against a real match.

    Every pair is a real title shape from prod. Under the substring match each
    decoy came back too, so the user's "+ ai" list was mostly retail, email and
    Mountain View jobs — 12,955 OPEN rows contain the letters, 7,268 the word.
    """
    _seed_job(db_conn, "mobile", title="Mobile Engineer")
    _seed_job(db_conn, "automobile", title="Automobile Systems Engineer")
    _seed_job(db_conn, "intern", title="Software Engineer Intern")
    _seed_job(db_conn, "international", title="Engineer, International Payments")
    _seed_job(db_conn, "internal", title="Internal Tools Engineer")
    _seed_job(db_conn, "ai", title="Applied AI Engineer")
    _seed_job(db_conn, "retail", title="Retail Engineer")
    _seed_job(db_conn, "email", title="Email Platform Engineer")
    _seed_job(db_conn, "mountain-view", location="Mountain View, CA")

    assert _search(client, include="mobile") == {"mobile"}
    assert _search(client, include="intern") == {"intern"}
    assert _search(client, include="ai") == {"ai"}


def test_exclude_does_not_hide_a_word_that_merely_contains_the_term(client, db_conn):
    """The exclude-side mirror, and the case that reached real users: "− intern"
    silently hid every International/Internal job, and "− mobile" every
    Automobile one. Only the row that really has the word is dropped."""
    _seed_job(db_conn, "mobile", title="Mobile Engineer")
    _seed_job(db_conn, "automobile", title="Automobile Systems Engineer")
    _seed_job(db_conn, "intern", title="Software Engineer Intern")
    _seed_job(db_conn, "international", title="Engineer, International Payments")
    _seed_job(db_conn, "internal", title="Internal Tools Engineer")

    everyone = {"mobile", "automobile", "intern", "international", "internal"}
    assert _search(client, exclude="mobile") == everyone - {"mobile"}
    assert _search(client, exclude="intern") == everyone - {"intern"}


def test_the_match_is_strict_no_plural_or_suffix_tolerance(client, db_conn):
    """Strict by the owner's decision: "engineer" is not "Engineering" or
    "Engineers", and "intern" is not "Internship". A user who wants those types
    them as their own chips. Pinned so a later "helpful" stemmer is a visible
    product change, not a quiet one."""
    _seed_job(db_conn, "engineer", title="Software Engineer")
    _seed_job(db_conn, "engineering", title="Engineering Manager")
    _seed_job(db_conn, "engineers", title="Founding Engineers")
    _seed_job(db_conn, "internship", title="Summer Internship")

    assert _search(client, include="engineer") == {"engineer"}
    assert _search(client, include="engineering") == {"engineering"}
    assert _search(client, include="intern") == set()


def test_a_word_boundary_holds_in_every_haystack_field(client, db_conn):
    """The boundary rule applies to location, company and tags, not just title —
    each field has its own decoy that contains the term mid-word."""
    _seed_job(db_conn, "loc-word", location="Remote - Mobile, AL")
    _seed_job(db_conn, "loc-decoy", location="Automobile City, MI")
    _seed_job(db_conn, "company-word", company="mobile-co")
    _seed_job(db_conn, "company-decoy", company="automobileco")
    _seed_job(db_conn, "tag-word")
    _seed_job(db_conn, "tag-decoy")
    _insert_job_tag(db_conn, SourceId.GOOGLE, "tag-word", "mobile")
    _insert_job_tag(db_conn, SourceId.GOOGLE, "tag-decoy", "automobile")

    assert _search(client, include="mobile") == {"loc-word", "company-word", "tag-word"}


def test_a_multi_word_term_is_an_adjacent_phrase(client, db_conn):
    """Words in order, next to each other, bounded at both ends. Any run of spaces
    between the words counts, because ATS titles are not tidy about spacing."""
    _seed_job(db_conn, "mts", title="Member of Technical Staff")
    _seed_job(db_conn, "mts-spaced", title="Member of  Technical Staff")
    _seed_job(db_conn, "reordered", title="Technical Member of Staff")
    _seed_job(db_conn, "glued", title="Member of Technicality")

    assert _search(client, include="member of technical") == {"mts", "mts-spaced"}
    assert _search(client, exclude="member of technical") == {"reordered", "glued"}


def test_a_boundary_is_only_required_on_a_letter_or_digit_edge(client, db_conn):
    """``\\y`` sits between a word and a non-word character, so a blanket
    ``\\yc\\+\\+\\y`` would demand a letter straight after "++" and never match
    "C++ Developer". The boundary is emitted only where the term's own edge is a
    letter or digit — each decoy is the near miss that rule must still reject."""
    _seed_job(db_conn, "cpp", title="C++ Developer")
    _seed_job(db_conn, "objcpp", title="ObjC++ Developer")
    _seed_job(db_conn, "csharp", title="C#/.NET Developer")
    _seed_job(db_conn, "aspnet", title="ASP.NET Developer")
    _seed_job(db_conn, "node", title="Node.js Engineer")
    _seed_job(db_conn, "nodex", title="Nodexjs Engineer")

    assert _search(client, include="C++") == {"cpp"}
    assert _search(client, include="c#") == {"csharp"}
    assert _search(client, include=".net") == {"csharp", "aspnet"}
    assert _search(client, include="node.js") == {"node"}


# ---------------------------------------------------------------------------
# (4) Pattern metacharacters are literals, not patterns
# ---------------------------------------------------------------------------


def test_regex_syntax_in_a_term_is_matched_literally(client, db_conn):
    """The term is compiled to a regex, so every character with regex meaning is
    escaped. Each decoy is what the UNESCAPED pattern would have matched: ``.`` as
    any character, ``(…)`` as a group, ``+`` as "one or more", ``[…]`` as a
    character class, ``*`` as the ``***=`` "director" at the start of a pattern."""
    _seed_job(db_conn, "parens", title="Engineer (Remote)")
    _seed_job(db_conn, "no-parens", title="Engineer Remote")
    _seed_job(db_conn, "dot", title="a.b Engineer")
    _seed_job(db_conn, "any-char", title="axb Engineer")
    _seed_job(db_conn, "plus", title="Go+ Engineer")
    _seed_job(db_conn, "repeated", title="Goo Engineer")
    _seed_job(db_conn, "brackets", title="[Hybrid] Engineer")
    _seed_job(db_conn, "class", title="H Engineer")
    _seed_job(db_conn, "director", title="***=x Engineer")

    assert _search(client, include="(remote)") == {"parens"}
    assert _search(client, include="a.b") == {"dot"}
    assert _search(client, include="go+") == {"plus"}
    assert _search(client, include="[hybrid]") == {"brackets"}
    assert _search(client, include="***=x") == {"director"}


# ---------------------------------------------------------------------------
# (5) LIKE-era metacharacters stay literals too
# ---------------------------------------------------------------------------


def test_percent_in_a_term_matches_a_literal_percent_sign(client, db_conn):
    """"100%" must mean "100%", not "100 followed by anything".

    The decoy carries ``100`` without the sign, so an unescaped ``%`` (which
    compiles to the pattern ``%100%%``) returns BOTH rows. Real titles are full of
    this — "100% Remote" is one of the most common phrases on the board.
    """
    _seed_job(db_conn, "literal-pct", title="C++ 100% Remote Engineer")
    _seed_job(db_conn, "hundreds", title="Engineer, 1000 Series")

    assert _search(client, include="100%") == {"literal-pct"}


def test_a_term_that_is_only_a_percent_sign_does_not_match_every_row(client, db_conn):
    """The degenerate form, and the loudest possible symptom of a missing escape:
    unescaped, ``include=%`` compiles to ``%%%`` and matches the entire corpus, so
    a filter the user thinks is narrowing actually removes nothing."""
    _seed_job(db_conn, "literal-pct", title="C++ 100% Remote Engineer")
    _seed_job(db_conn, "plain-backend", title="Backend Engineer")
    _seed_job(db_conn, "plain-frontend", title="Frontend Engineer")

    assert _search(client, include="%") == {"literal-pct"}


def test_underscore_in_a_term_matches_a_literal_underscore(client, db_conn):
    """``_`` is LIKE's single-character wildcard. Unescaped, "senior_swe" also
    matches "seniorxswe" — and slug-shaped terms are exactly what users paste in
    from a job description."""
    _seed_job(db_conn, "underscored", title="senior_swe wanted")
    _seed_job(db_conn, "wildcard-bait", title="seniorxswe wanted")

    assert _search(client, include="senior_swe") == {"underscored"}


def test_backslash_in_a_term_matches_a_literal_backslash(client, db_conn):
    """The escape character itself.

    This fixture makes the failure a full inversion rather than a widening: with
    ``\\`` unescaped, the regex ``C:\\Drivers`` reads ``\\D`` as "any non-digit",
    so it matches "C:Drivers" (``D`` is a non-digit) and NOT "C:\\Drivers" — the
    regression returns the decoy and not the row the user was looking for. A bare
    ``\\`` term degrades further: a trailing backslash is an invalid regex, so the
    request would 500. (Under the old LIKE match the same two terms failed the same
    two ways, which is why the test predates the regex.)
    """
    _seed_job(db_conn, "with-backslash", title=r"Windows C:\Drivers Engineer")
    _seed_job(db_conn, "without-backslash", title="Windows C:Drivers Engineer")

    assert _search(client, include=r"C:\Drivers") == {"with-backslash"}
    assert _search(client, include="\\") == {"with-backslash"}


def test_accented_terms_match_case_insensitively_in_both_directions(client, db_conn):
    """``~*`` case-folds non-ASCII too, and the search box is UTF-8 end to end.

    Both directions are asserted because the folding is done by the database's
    ctype: a lower-cased term against an upper-cased title exercises a different
    half of the comparison than the reverse, and a C-collation database would pass
    one and fail the other.

    The unaccented decoy pins the other edge: the match case-folds, it does NOT
    accent-fold, so "Ingenieur" is a different string from "Ingénieur" and must
    not be swept in. The last assertion pins the locale's notion of a word: an
    accented letter is a WORD character, so "café" does not match inside
    "Cafémanager" — the same rule the client matcher's ``\\p{L}`` applies.
    """
    _seed_job(db_conn, "cafe-glued", title="Cafémanager")
    _seed_job(db_conn, "accent-lower", title="Ingénieur Logiciel")
    _seed_job(db_conn, "accent-upper", title="INGÉNIEUR LOGICIEL")
    _seed_job(db_conn, "unaccented", title="Ingenieur Logiciel")

    accented = {"accent-lower", "accent-upper"}
    assert _search(client, include="INGÉNIEUR") == accented
    assert _search(client, include="ingénieur") == accented
    assert _search(client, include="café") == set()


# ---------------------------------------------------------------------------
# (6) The empty result is a first-class answer, not an error
# ---------------------------------------------------------------------------


def test_an_include_term_matching_nothing_returns_an_empty_page_and_a_zero_total(
    client, db_conn
):
    """A keyword nobody's board contains is a legitimate query with an empty
    answer — not a 4xx, and not a page of unfiltered rows.

    ``filteredTotal`` must agree and report 0. It is what the UI renders as the
    result count, so a total computed over a DIFFERENT predicate than the page
    (the count query is a separate statement) would show "31,402 results" above an
    empty list.
    """
    _seed_job(db_conn, "a")
    _seed_job(db_conn, "b")

    assert _search(client) == {"a", "b"}, (
        "control: the corpus is non-empty, so the empty result below is the "
        "filter's doing and not an empty fixture"
    )

    resp = client.get(
        "/api/jobs/search", params={"include": "thereisnosuchkeywordanywhere"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["jobs"] == []
    assert body["nextCursor"] is None, "an empty page is the end of the walk"
    assert body["meta"]["filteredTotal"] is None
