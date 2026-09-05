"""Perf Wave 2 denormalizations — ``primary_country`` (C2) + ``search_text`` (C3).

WHAT THIS FILE PROTECTS
-----------------------
The two hot predicates in ``services/job_search.py`` were rewritten to SEEK on two
denormalized columns instead of the cross-table ``EXISTS`` / 4-way ``OR`` they used
to run:

* country-tier location →
  ``primary_country = %s OR (primary_country IS NULL AND <country-tier EXISTS>)``
* keyword →
  ``(search_text IS NOT NULL AND search_text ILIKE %s) OR (search_text IS NULL AND <4-way OR>)``

Both columns are **nullable and lazily populated** (write path + a bounded
post-deploy backfill), so at any instant an arbitrary subset of rows is
backfilled and the rest are NULL. The one non-negotiable property is that this
must NEVER change the result set: a fast (backfilled) answer must equal the
fallback (NULL) answer exactly, for every population state in between.

The rest of the suite only ever sees these columns NULL — ``conftest._insert_job``
writes ``job_listings`` with a raw INSERT, so ``test_jobs_search_locations`` and
``test_server_results_match_client_filter_oracle`` already lock the FALLBACK path
as correct. This file is the other half: it populates the columns with the EXACT
production expressions (``recompute_primary_country_for`` /
``recompute_search_text_for`` from ``scripts/shared/database.py``, the same
helpers the scraper / enrichment / normalization write paths call) and asserts the
fast path agrees with the fallback — fully backfilled AND partially backfilled.

The pattern is deliberately relative: the all-NULL result is taken as GROUND TRUTH
(the sibling files prove it correct against the client oracle), and the populated
/ partially-populated results are asserted equal to it. A rewrite that dropped or
added a row under partial population is exactly what fails here. A handful of
absolute expectations are pinned too, so the test is not purely circular.
"""

from datetime import datetime, timezone

from scripts.shared.constants import SourceId
from scripts.shared.database import (
    recompute_primary_country_for,
    recompute_search_text_for,
)

from .conftest import (
    _insert_job,
    _insert_job_tag,
    _insert_location,
    _link_job_location,
    _make_job,
)

_BASE_TIME = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat()


def _place(conn, canonical_name, **fields):
    return _insert_location(
        conn, canonical_name=canonical_name, kind=fields.pop("kind", "city"), **fields
    )


def _job(conn, job_id, *, tags=(), locations=(), source_id=SourceId.GOOGLE, **overrides):
    """Seed one OPEN job with raw location text, tags and location tags.

    Columns ``primary_country`` / ``search_text`` are left NULL (raw INSERT) — the
    backfill helpers below populate them exactly as production does.
    """
    _insert_job(
        conn,
        _make_job(
            {
                "id": job_id,
                "source_id": source_id,
                "first_seen_at": _BASE_TIME,
                "last_seen_at": _BASE_TIME,
                **overrides,
            }
        ),
    )
    for location_id in locations:
        _link_job_location(conn, job_id, location_id)
    for tag in tags:
        _insert_job_tag(conn, source_id, job_id, tag)
    return job_id


def _all_keys(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT source_id, id FROM job_listings")
        return [(r["source_id"], r["id"]) for r in cur.fetchall()]


def _backfill(conn, keys):
    """Populate both denormalized columns for ``keys`` the way the write path does."""
    with conn.cursor() as cur:
        for source_id, job_id in keys:
            recompute_primary_country_for(cur, job_id)
            recompute_search_text_for(cur, source_id, job_id)
    conn.commit()


def _null_all(conn):
    with conn.cursor() as cur:
        cur.execute("UPDATE job_listings SET primary_country = NULL, search_text = NULL")
    conn.commit()


def _ids(client, **params):
    resp = client.get("/api/jobs/search", params={**params, "limit": 500})
    assert resp.status_code == 200, resp.text
    return {job["id"] for job in resp.json()["jobs"]}


# ---------------------------------------------------------------------------
# A corpus that exercises every branch of the country fast path + the keyword
# haystack. Seeded once; each test drives it through the three population states.
# ---------------------------------------------------------------------------


def _seed_corpus(conn):
    austin = _place(conn, "Austin, TX, US", city="Austin", region="TX", country="US")
    berlin = _place(conn, "Berlin, BE, DE", city="Berlin", region="BE", country="DE")
    toronto = _place(conn, "Toronto, ON, CA", city="Toronto", region="ON", country="CA")
    remote_us = _place(conn, "Remote (US)", kind="remote", remote_scope="US", country="US")
    # Resolution targets for the "Germany" selection (a country row) — attached to
    # no job, so a match must come from the country TIER, not the exact name.
    _place(conn, "Germany", kind="country", country="DE")

    _job(conn, "us-single", title="Backend Engineer", company="google",
         location="Austin, TX", locations=(austin,), tags=("python",))
    # Two distinct non-remote countries -> primary_country stays NULL (multi) ->
    # must route through the fallback for BOTH "United States" and "Germany".
    _job(conn, "us-multi", title="Data Scientist", company="stripe",
         location="Multiple", locations=(austin, berlin))
    _job(conn, "de-single", title="ML Engineer", company="sap",
         location="Berlin", locations=(berlin,))
    _job(conn, "remote-us", title="Product Manager", company="gitlab",
         location="Anywhere", locations=(remote_us,))
    _job(conn, "ca-single", title="Frontend Engineer", company="shopify",
         location="Toronto", locations=(toronto,))
    # No location tag at all, raw location merely SAYS United States — must match
    # no active location filter (an untagged job is not "everywhere").
    _job(conn, "untagged", title="Growth Lead", company="brex",
         location="Remote - United States")


# The filters walked in every population state. Chosen to hit the country fast
# path (US/DE), single/multi/remote/untagged rows, and each keyword haystack
# field (title / raw location / company / tag) plus the exclude NULL-safety path.
_FILTER_SETS = [
    {"location": "United States"},
    {"location": "Germany"},
    {"location": ["United States", "Germany"]},
    {"include": "python"},          # tag
    {"include": "engineer"},        # title
    {"include": "austin"},          # raw location
    {"include": "sap"},             # company
    {"include": ["python", "sap"]},
    {"exclude": "engineer"},
    {"location": "United States", "exclude": "python"},
]


def test_populated_columns_match_the_null_fallback_exactly(client, db_conn):
    """The fast (backfilled) path returns byte-identical result sets to the NULL
    fallback, for every filter — fully backfilled AND half backfilled.

    This is the migration's correctness contract: a not-yet-backfilled value is a
    slower answer, never a wrong one. The all-NULL result is ground truth (the
    sibling files prove it against the client oracle); populated and partial must
    equal it.
    """
    _seed_corpus(db_conn)

    # (1) Ground truth: columns all NULL -> both predicates run their fallback.
    ground_truth = {
        _fs_key(fs): _ids(client, **fs) for fs in _FILTER_SETS
    }

    # (2) Fully backfilled -> both predicates run their fast branch.
    keys = _all_keys(db_conn)
    _backfill(db_conn, keys)
    for fs in _FILTER_SETS:
        assert _ids(client, **fs) == ground_truth[_fs_key(fs)], (
            f"fully-backfilled result diverged from the NULL fallback for {fs!r}"
        )

    # (3) Partially backfilled -> every row hits a DIFFERENT branch than its
    # neighbour, which is the state the endpoint actually serves during a backfill.
    _null_all(db_conn)
    _backfill(db_conn, keys[::2])  # every other row
    for fs in _FILTER_SETS:
        assert _ids(client, **fs) == ground_truth[_fs_key(fs)], (
            f"partially-backfilled result diverged from the NULL fallback for {fs!r}"
        )


def test_absolute_expectations_hold_when_backfilled(client, db_conn):
    """Pin the actual answers (not just self-consistency) once the columns are
    populated, so the whole comparison above cannot pass vacuously on a fallback
    that silently regressed too."""
    _seed_corpus(db_conn)
    _backfill(db_conn, _all_keys(db_conn))

    # Country tier: remote-US is opt-out of a country selection; the multi-country
    # row (primary_country NULL) still matches via the fallback EXISTS; untagged
    # and the wrong-country rows stay out.
    assert _ids(client, location="United States") == {"us-single", "us-multi"}
    assert _ids(client, location="Germany") == {"de-single", "us-multi"}
    assert _ids(client, location=["United States", "Germany"]) == {
        "us-single", "us-multi", "de-single",
    }

    # Keyword haystack, one assertion per field.
    assert _ids(client, include="python") == {"us-single"}          # tag
    assert _ids(client, include="sap") == {"de-single"}             # company
    assert _ids(client, include="austin") == {"us-single"}         # raw location
    assert _ids(client, include="engineer") == {
        "us-single", "de-single", "ca-single",                      # title
    }


def test_backfilled_null_search_text_row_survives_a_non_matching_exclude(client, db_conn):
    """The exclude-path NULL hazard, one level up from the ``COALESCE(location)``
    guard: a row whose ``search_text`` is still NULL must not vanish under an
    ``exclude`` term it does not match, even while its neighbours are backfilled.

    A bare ``search_text ILIKE %s OR (…)`` (without the ``IS NOT NULL`` guard on
    the fast branch) evaluates to NULL for such a row, and ``NOT (NULL)`` drops it.
    """
    austin = _place(db_conn, "Austin, TX, US", city="Austin", region="TX", country="US")
    # This row keeps search_text NULL (never backfilled) and matches no term.
    _job(db_conn, "null-search-text", title="Data Analyst", company="acme",
         location="Springfield, IL", locations=(austin,))
    # A backfilled neighbour that DOES match the exclude term, so the term is real.
    drop = _job(db_conn, "has-term", title="Backend Engineer", company="acme",
                location="Springfield, IL")
    _backfill(db_conn, [(SourceId.GOOGLE, drop)])

    survivors = _ids(client, exclude="engineer")

    assert "null-search-text" in survivors, (
        "a NULL-search_text row that does not match the exclude term was dropped — "
        "the fast branch must be guarded by search_text IS NOT NULL so NOT(...) "
        "never sees a NULL"
    )
    assert "has-term" not in survivors


def _fs_key(fs):
    """A hashable, order-stable key for a filter dict (values may be lists)."""
    return tuple(sorted(
        (k, tuple(v) if isinstance(v, list) else v) for k, v in fs.items()
    ))


# ---------------------------------------------------------------------------
# Per-field keyword parity: a MULTI-WORD term must never match ACROSS a field or
# tag boundary on the fast (``search_text``) branch — the fallback 4-way OR never
# does, so the fast branch must not either, on BOTH the include and exclude paths.
# ``search_text`` joins its fields (and its tags) with a newline, which
# ``_validate_text_list`` rejects inside a term, so a user term can never contain
# the separator and therefore can never span a boundary.
# ---------------------------------------------------------------------------


def _seed_boundary_corpus(conn):
    """Rows where a two-word term either straddles a boundary (must NOT match) or
    lives within one field/tag (must match)."""
    # title 'Backend' + raw location 'Engineer': "backend engineer" spans the
    # title→location boundary. Per-field OR: no single field holds it -> no match.
    _job(conn, "span-title-loc", title="Backend", company="acme", location="Engineer")
    # tags 'backend' and 'engineer' are two DISTINCT tags: the fallback's per-tag
    # EXISTS matches a term to ONE tag, so "backend engineer" spans them -> no match.
    _job(conn, "span-two-tags", title="Analyst", company="acme",
         location="NYC", tags=("backend", "engineer"))
    # "backend engineer" WITHIN a single title field -> matches (space preserved).
    _job(conn, "within-title", title="Backend Engineer", company="acme",
         location="Remote")
    # "machine learning" WITHIN a single tag -> matches (intra-tag space preserved
    # by the newline join, which only separates DISTINCT tags).
    _job(conn, "within-tag", title="Researcher", company="acme",
         location="Boston", tags=("machine learning",))


# Include/exclude filters that hinge on the boundary: the two multi-word terms,
# and single-word controls that must still match within a field/tag.
_BOUNDARY_FILTER_SETS = [
    {"include": "backend engineer"},
    {"include": "machine learning"},
    {"exclude": "backend engineer"},
    {"exclude": "machine learning"},
    {"include": "backend"},          # single word: title field + one tag
    {"include": "engineer"},         # single word: within-title + one tag
]


def test_multiword_term_never_spans_a_field_or_tag_boundary(client, db_conn):
    """Fast (backfilled) == fallback (NULL) for multi-word include/exclude terms,
    fully AND partially backfilled — the boundary case ``_FILTER_SETS`` above does
    not exercise (its terms are all single words)."""
    _seed_boundary_corpus(db_conn)

    ground_truth = {_fs_key(fs): _ids(client, **fs) for fs in _BOUNDARY_FILTER_SETS}

    keys = _all_keys(db_conn)
    _backfill(db_conn, keys)
    for fs in _BOUNDARY_FILTER_SETS:
        assert _ids(client, **fs) == ground_truth[_fs_key(fs)], (
            f"fully-backfilled result diverged from the NULL fallback for {fs!r} — "
            f"a multi-word term matched across a field/tag boundary on the fast path"
        )

    _null_all(db_conn)
    _backfill(db_conn, keys[::2])  # every other row on the fast path
    for fs in _BOUNDARY_FILTER_SETS:
        assert _ids(client, **fs) == ground_truth[_fs_key(fs)], (
            f"partially-backfilled result diverged from the NULL fallback for {fs!r}"
        )


def test_boundary_absolute_expectations_when_backfilled(client, db_conn):
    """Pin the actual answers so the parity check above can't pass vacuously on a
    fallback that regressed the same way."""
    _seed_boundary_corpus(db_conn)
    _backfill(db_conn, _all_keys(db_conn))

    # Multi-word terms match ONLY within a single field / tag, never across one.
    assert _ids(client, include="backend engineer") == {"within-title"}
    assert _ids(client, include="machine learning") == {"within-tag"}

    # Exclude is the mirror: it removes ONLY the row that genuinely matches, and
    # must NOT drop a boundary-straddling row (the old space-join wrongly did).
    everyone = {"span-title-loc", "span-two-tags", "within-title", "within-tag"}
    assert _ids(client, exclude="backend engineer") == everyone - {"within-title"}
    assert _ids(client, exclude="machine learning") == everyone - {"within-tag"}

    # Single-word controls still match within a field and within a tag.
    # ``backend`` hits the title of span-title-loc + within-title and the ``backend``
    # tag of span-two-tags. ``engineer`` hits span-title-loc's RAW LOCATION
    # ("Engineer"), within-title's title, and span-two-tags' ``engineer`` tag.
    assert _ids(client, include="backend") == {"span-title-loc", "span-two-tags",
                                               "within-title"}
    assert _ids(client, include="engineer") == {"span-title-loc", "span-two-tags",
                                                "within-title"}
