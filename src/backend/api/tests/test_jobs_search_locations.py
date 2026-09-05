"""Hierarchical location matching on ``GET /api/jobs/search``.

WHAT THIS FILE PROTECTS
-----------------------
Location is the only filter dimension on this endpoint that is not a literal
comparison. Every other dimension asks "is this value one of the ones the caller
listed?"; a location asks "is this job's place *inside* the place the caller
picked?" — a country has to reach the regions and cities under it, a region has
to reach its cities, and neither may reach a remote listing that merely happens
to carry the same country code.

That containment logic is a clause-for-clause port of the client's
``matchesLocation``, and every way it can break is SILENT. A predicate that is a
shade too loose returns a 200 full of jobs on the wrong continent; one that is a
shade too tight returns a 200 that is simply missing every city row under the
selected state. Neither raises, and from the UI both are indistinguishable from
"there is nothing there right now" — which is a perfectly ordinary thing for a
job board to say.

So no test here is content to assert that the intended job came back. Each one
seeds a DECOY sitting exactly one field away from matching — the same city name
in a different state, the same two-letter region code in a different country, the
same country code on a remote tag, a NULL where the selection wants a value — and
asserts the decoy is absent. Assertions on the intended row alone would pass
against a filter that returned the entire corpus; the decoys are what make these
tests fail when the containment logic regresses.

Two structural details drive the seeding style below:

* A selection is a canonical NAME, resolved against the ``locations`` catalog at
  request time (see ``resolve_location_selections``). So "the row that resolves
  the selection" and "the row a job is tagged with" are deliberately kept as
  SEPARATE rows wherever the test is about structural containment — if they were
  the same row the selection would match through the exact-canonical-name branch
  and prove nothing about the hierarchy.
* Three of the pickable options ("United States", "<State>, US", and anything the
  catalog does not know) have no ordinary catalog row behind them, so each gets
  its own test of the fallback that resolves it.
"""

from datetime import datetime, timezone

from .conftest import _insert_job, _insert_location, _link_job_location, _make_job

# One fixed instant for every seeded job. These tests compare SETS of ids, never
# order, so a shared timestamp keeps the fixtures readable — ordering is the
# subject of test_jobs_keyset_pagination.py, not of this file.
_BASE_TIME = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat()


def _place(conn, canonical_name: str, **fields) -> int:
    """Insert one ``locations`` row and return its id.

    ``kind`` defaults to ``city`` because that is what the normalizer emits for
    the overwhelming majority of tags; every other tier is spelled out at the call
    site, where the tier IS the point of the test.
    """
    return _insert_location(
        conn,
        canonical_name=canonical_name,
        kind=fields.pop("kind", "city"),
        **fields,
    )


def _job(conn, job_id: str, *place_ids: int, **overrides) -> str:
    """Seed one OPEN job and attach zero or more canonical location tags."""
    _insert_job(
        conn,
        _make_job(
            {
                "id": job_id,
                "first_seen_at": _BASE_TIME,
                "last_seen_at": _BASE_TIME,
                **overrides,
            }
        ),
    )
    for place_id in place_ids:
        _link_job_location(conn, job_id, place_id)
    return job_id


def _search(client, **params) -> dict:
    resp = client.get("/api/jobs/search", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ids(body: dict) -> set[str]:
    return {job["id"] for job in body["jobs"]}


def _all_ids(client) -> set[str]:
    """Every visible job, unfiltered.

    Called at the top of most tests to prove the decoys actually made it into the
    corpus — otherwise "the decoy did not come back" could just mean the fixture
    never inserted it, and the test would pass for the wrong reason.
    """
    return _ids(_search(client))


# ---------------------------------------------------------------------------
# (1) Exact canonical-name selection
# ---------------------------------------------------------------------------


def test_selecting_a_canonical_name_returns_only_jobs_tagged_with_that_place(
    client, db_conn
):
    """The base case the whole filter rests on: a selection names a place, and
    the jobs tagged with a DIFFERENT place stay out of the result."""
    austin = _place(db_conn, "Austin, TX, US", city="Austin", region="TX", country="US")
    denver = _place(db_conn, "Denver, CO, US", city="Denver", region="CO", country="US")
    _job(db_conn, "in-austin", austin)
    _job(db_conn, "in-denver", denver)

    assert _all_ids(client) == {"in-austin", "in-denver"}

    body = _search(client, location="Austin, TX, US")

    assert _ids(body) == {"in-austin"}


# ---------------------------------------------------------------------------
# (2) City tier — city, region and country must ALL agree
# ---------------------------------------------------------------------------


def test_city_selection_requires_city_region_and_country_to_all_agree(client, db_conn):
    """City names are not unique, so the city tier compares all three fields.

    The three decoys are each one field off. "Portland, ME" is the everyday case
    (two real US cities share the name). The country-only variant is synthetic but
    load-bearing: two-letter region codes are only unique WITHIN a country (see
    the Ontario test below), so dropping the country comparison here would let
    them collide. The field-less row pins that NULL is not a wildcard — a tag the
    normalizer could only pin down to "Portland" must not answer a selection that
    asked for Oregon specifically.
    """
    portland_or = _place(
        db_conn, "Portland, OR, US", city="Portland", region="OR", country="US"
    )
    portland_me = _place(
        db_conn, "Portland, ME, US", city="Portland", region="ME", country="US"
    )
    portland_elsewhere = _place(
        db_conn, "Portland, OR, CA", city="Portland", region="OR", country="CA"
    )
    portland_bare = _place(db_conn, "Portland", city="Portland")
    _job(db_conn, "oregon", portland_or)
    _job(db_conn, "maine", portland_me)
    _job(db_conn, "wrong-country", portland_elsewhere)
    _job(db_conn, "unqualified", portland_bare)

    assert _all_ids(client) == {"oregon", "maine", "wrong-country", "unqualified"}

    body = _search(client, location="Portland, OR, US")

    assert _ids(body) == {"oregon"}


def test_city_matching_ignores_the_case_of_the_stored_tag(client, db_conn):
    """The catalog is written by several producers (the Tier-1 rules, Claude, and
    manual admin aliases), so the same place can be stored with different casing.
    Matching folds case on BOTH sides, which is why the selection's row and the
    job's row here are deliberately distinct rows spelled differently.
    """
    # The row the SELECTION resolves through — attached to no job.
    _place(db_conn, "Springfield, IL, US", city="Springfield", region="IL", country="US")
    # The row the job is actually tagged with: same place, shouted and muttered.
    shouted = _place(
        db_conn, "springfield il us", city="SPRINGFIELD", region="il", country="us"
    )
    missouri = _place(
        db_conn, "Springfield, MO, US", city="Springfield", region="MO", country="US"
    )
    _job(db_conn, "illinois", shouted)
    _job(db_conn, "missouri", missouri)

    assert _all_ids(client) == {"illinois", "missouri"}

    body = _search(client, location="Springfield, IL, US")

    assert _ids(body) == {"illinois"}


# ---------------------------------------------------------------------------
# (3) Region tier — downward containment, and the country check that guards it
# ---------------------------------------------------------------------------


def test_region_selection_reaches_cities_inside_it_and_the_region_tag_itself(
    client, db_conn
):
    """Picking a state must surface both the jobs normalized to the state itself
    and the jobs normalized to a city within it — the hierarchy is the entire
    reason the filter runs in SQL rather than as a name comparison.

    The country-tag decoy pins the direction: containment runs DOWNWARD only. A
    job tagged "United States of America" is not known to be in Texas, so a Texas
    selection must not claim it.
    """
    texas = _place(db_conn, "Texas, US", kind="region", region="TX", country="US")
    austin = _place(db_conn, "Austin, TX, US", city="Austin", region="TX", country="US")
    denver = _place(db_conn, "Denver, CO, US", city="Denver", region="CO", country="US")
    usa = _place(db_conn, "United States of America", kind="country", country="US")
    _job(db_conn, "statewide", texas)
    _job(db_conn, "in-austin", austin)
    _job(db_conn, "in-denver", denver)
    _job(db_conn, "nationwide", usa)

    assert _all_ids(client) == {"statewide", "in-austin", "in-denver", "nationwide"}

    body = _search(client, location="Texas, US")

    assert _ids(body) == {"statewide", "in-austin"}


def test_a_region_code_does_not_cross_match_into_another_country(client, db_conn):
    """A two-letter region code is only unique WITHIN a country.

    'ON' is Ontario in Canada; the US-side row here is synthetic on purpose — what
    is under test is that the region predicate compares country as well, so a code
    collision between two catalogs can never leak jobs across the border. Dropping
    the country comparison would make both selections return both jobs, and that
    result would look entirely plausible in the UI.
    """
    ontario_ca = _place(db_conn, "Ontario, CA", kind="region", region="ON", country="CA")
    ontario_us = _place(db_conn, "Ontario, US", kind="region", region="ON", country="US")
    toronto = _place(
        db_conn, "Toronto, ON, CA", city="Toronto", region="ON", country="CA"
    )
    us_on_city = _place(
        db_conn, "Springfield, ON, US", city="Springfield", region="ON", country="US"
    )
    _job(db_conn, "canadian", toronto)
    _job(db_conn, "american", us_on_city)
    # The region rows themselves are tagged too, so the cross-match check covers
    # region-tag-under-region-selection as well as city-under-region.
    _job(db_conn, "canadian-wide", ontario_ca)
    _job(db_conn, "american-wide", ontario_us)

    assert _all_ids(client) == {
        "canadian",
        "american",
        "canadian-wide",
        "american-wide",
    }

    assert _ids(_search(client, location="Ontario, CA")) == {
        "canadian",
        "canadian-wide",
    }
    assert _ids(_search(client, location="Ontario, US")) == {
        "american",
        "american-wide",
    }


# ---------------------------------------------------------------------------
# (4) Country tier
# ---------------------------------------------------------------------------


def test_country_selection_reaches_city_region_and_country_tags_in_that_country(
    client, db_conn
):
    """A country selection spans all three geographic tiers beneath it.

    (The nationwide job below is tagged with the very row the selection resolves
    through, so it would also match on canonical name alone; the city and region
    jobs are the load-bearing half here, and
    ``test_united_states_meta_option_matches_every_us_tagged_job`` proves the
    country tier reaches a country tag with no name help at all.)
    """
    germany = _place(db_conn, "Germany", kind="country", country="DE")
    berlin = _place(db_conn, "Berlin, BE, DE", city="Berlin", region="BE", country="DE")
    bavaria = _place(db_conn, "Bavaria, DE", kind="region", region="BY", country="DE")
    paris = _place(db_conn, "Paris, IDF, FR", city="Paris", region="IDF", country="FR")
    _job(db_conn, "nationwide", germany)
    _job(db_conn, "in-berlin", berlin)
    _job(db_conn, "in-bavaria", bavaria)
    _job(db_conn, "in-paris", paris)

    assert _all_ids(client) == {"nationwide", "in-berlin", "in-bavaria", "in-paris"}

    body = _search(client, location="Germany")

    assert _ids(body) == {"nationwide", "in-berlin", "in-bavaria"}


# ---------------------------------------------------------------------------
# (5) Remote is opt-in on both sides
# ---------------------------------------------------------------------------


def test_a_country_selection_does_not_match_a_remote_tag_in_that_country(
    client, db_conn
):
    """Remote rows carry a country so the catalog can offer "Remote (Germany)" as
    its own option — which means a plain country selection would sweep them in for
    free unless it excludes ``kind = 'remote'`` explicitly.

    Keeping them apart is the user-visible contract: picking Germany means "I will
    be in Germany", and a remote-anywhere-in-Germany listing is a different
    question the picker asks separately.
    """
    _place(db_conn, "Germany", kind="country", country="DE")
    berlin = _place(db_conn, "Berlin, BE, DE", city="Berlin", region="BE", country="DE")
    remote_de = _place(
        db_conn, "Remote (Germany)", kind="remote", country="DE", remote_scope="DE"
    )
    _job(db_conn, "onsite", berlin)
    _job(db_conn, "remote", remote_de)

    assert _all_ids(client) == {"onsite", "remote"}

    body = _search(client, location="Germany")

    assert _ids(body) == {"onsite"}


def test_a_region_selection_does_not_match_a_remote_tag_in_that_region(
    client, db_conn
):
    """Same exclusion one tier down — a remote row may be scoped to a region too,
    and the region predicate has its own ``kind <> 'remote'`` guard that has to be
    tested separately from the country one."""
    _place(db_conn, "Texas, US", kind="region", region="TX", country="US")
    austin = _place(db_conn, "Austin, TX, US", city="Austin", region="TX", country="US")
    remote_tx = _place(
        db_conn,
        "Remote (Texas)",
        kind="remote",
        region="TX",
        country="US",
        remote_scope="US",
    )
    _job(db_conn, "onsite", austin)
    _job(db_conn, "remote", remote_tx)

    assert _all_ids(client) == {"onsite", "remote"}

    body = _search(client, location="Texas, US")

    assert _ids(body) == {"onsite"}


def test_a_scoped_remote_selection_matches_only_that_scope(client, db_conn):
    """"Remote (US)" is a narrower claim than "Remote".

    The unscoped decoy is the subtle one: a NULL ``remote_scope`` means "we do not
    know where this remote role may be worked from", which is NOT the same as
    "anywhere, including the US". Treating NULL as a match would put EU-only and
    unknown-scope roles in front of a US-based reader.
    """
    _place(db_conn, "Remote (US)", kind="remote", remote_scope="US")
    # Distinct row from the one the selection resolves through, differently cased,
    # so the match has to survive case folding rather than land on the same row.
    us_tag = _place(db_conn, "remote us", kind="remote", remote_scope="us")
    eu_tag = _place(db_conn, "Remote (EU)", kind="remote", remote_scope="EU")
    anywhere_tag = _place(db_conn, "Remote", kind="remote")
    _job(db_conn, "remote-us", us_tag)
    _job(db_conn, "remote-eu", eu_tag)
    _job(db_conn, "remote-unscoped", anywhere_tag)

    assert _all_ids(client) == {"remote-us", "remote-eu", "remote-unscoped"}

    body = _search(client, location="Remote (US)")

    assert _ids(body) == {"remote-us"}


def test_an_unscoped_remote_selection_matches_every_remote_tag(client, db_conn):
    """The mirror image: picking plain "Remote" is the broad claim, and it must
    reach every remote tag whatever its scope — including the scoped ones, which a
    naive ``remote_scope IS NULL`` equality would miss.

    The on-site decoy keeps the branch honest: "Remote" is not "everything".
    """
    _place(db_conn, "Remote", kind="remote")
    us_tag = _place(db_conn, "Remote (US)", kind="remote", remote_scope="US")
    eu_tag = _place(db_conn, "Remote (EU)", kind="remote", remote_scope="EU")
    austin = _place(db_conn, "Austin, TX, US", city="Austin", region="TX", country="US")
    _job(db_conn, "remote-us", us_tag)
    _job(db_conn, "remote-eu", eu_tag)
    _job(db_conn, "onsite", austin)

    assert _all_ids(client) == {"remote-us", "remote-eu", "onsite"}

    body = _search(client, location="Remote")

    assert _ids(body) == {"remote-us", "remote-eu"}


# ---------------------------------------------------------------------------
# (6) The two synthesized options with no catalog row behind them
# ---------------------------------------------------------------------------


def test_united_states_meta_option_matches_every_us_tagged_job(client, db_conn):
    """"United States" is a hard-coded picker entry, not a ``locations`` row.

    Nothing here is named "United States", so the exact-canonical-name branch
    cannot help: every one of these three matches has to come from the country
    tier the meta-option synthesizes. That also makes this the test that proves
    the country tier reaches a country TAG on its own.
    """
    sf = _place(
        db_conn, "San Francisco, CA, US", city="San Francisco", region="CA", country="US"
    )
    texas = _place(db_conn, "Texas, US", kind="region", region="TX", country="US")
    usa = _place(db_conn, "USA", kind="country", country="US")
    toronto = _place(
        db_conn, "Toronto, ON, CA", city="Toronto", region="ON", country="CA"
    )
    _job(db_conn, "city-tag", sf)
    _job(db_conn, "region-tag", texas)
    _job(db_conn, "country-tag", usa)
    _job(db_conn, "canadian", toronto)

    assert _all_ids(client) == {"city-tag", "region-tag", "country-tag", "canadian"}

    body = _search(client, location="United States")

    assert _ids(body) == {"city-tag", "region-tag", "country-tag"}
    # The count query composes the same predicate, so it must agree with the page.
    assert body["meta"]["filteredTotal"] is None


def test_a_state_label_with_no_catalog_row_resolves_through_the_state_name_fallback(
    client, db_conn
):
    """The picker synthesizes "<State>, US" labels, so the server must be able to
    resolve one without a catalog row to look it up in.

    The Canadian decoy is the whole point of asserting this rather than assuming
    it: the fallback has to land 'CA' in the REGION slot. Put it in the country
    slot instead — an easy thing to get backwards, since 'CA' is a valid country
    code for Canada — and this selection quietly returns Toronto.
    """
    sf = _place(
        db_conn, "San Francisco, CA, US", city="San Francisco", region="CA", country="US"
    )
    nyc = _place(
        db_conn, "New York, NY, US", city="New York", region="NY", country="US"
    )
    toronto = _place(
        db_conn, "Toronto, ON, CA", city="Toronto", region="ON", country="CA"
    )
    _job(db_conn, "californian", sf)
    _job(db_conn, "new-yorker", nyc)
    _job(db_conn, "canadian", toronto)

    assert _all_ids(client) == {"californian", "new-yorker", "canadian"}

    body = _search(client, location="California, US")

    assert _ids(body) == {"californian"}


def test_a_selection_that_resolves_to_no_structure_falls_back_to_exact_name_matching(
    client, db_conn
):
    """A catalog row can carry a canonical name and no usable structure — the
    normalizer emits these when it can label a posting but not place it.

    Such a selection has no tier to expand into, so the only thing left is exact
    name equality, and that is exactly what it must do: match the jobs carrying
    that name and nothing else. The two decoys cover the two ways this degrades —
    treating the absent city as a wildcard (which would sweep in every other
    structureless row) and matching the name as a prefix rather than in full.

    ``other_vague`` therefore carries NO structure at all, not even a country: a
    wildcard degradation emits ``upper(l.region) IS NOT DISTINCT FROM NULL AND
    upper(l.country) IS NOT DISTINCT FROM NULL``, which a row with any country
    fails on structure alone. A decoy that a broken predicate excludes for the
    wrong reason pins nothing.

    Its ``kind`` differs from ``vague``'s only because it has to: uniqueness on
    ``locations`` is the tuple ``(kind, city, region, country, remote_scope)`` and
    excludes ``canonical_name`` (``uq_locations_canonical``), so a SECOND
    all-NULL ``city`` row is not merely undesirable, it is unrepresentable. The
    city branch does not read ``kind`` at all, so the decoy is swept in by the
    degradation exactly as a same-kind row would be.
    """
    vague = _place(db_conn, "Undisclosed")
    other_vague = _place(db_conn, "Unknown", kind="region")
    suffixed = _place(db_conn, "Undisclosed, US", country="US")
    _job(db_conn, "no-place", vague)
    _job(db_conn, "other-no-place", other_vague)
    _job(db_conn, "longer-name", suffixed)

    assert _all_ids(client) == {"no-place", "other-no-place", "longer-name"}

    body = _search(client, location="Undisclosed")

    assert _ids(body) == {"no-place"}


# ---------------------------------------------------------------------------
# (7) Composition: untagged jobs, multiple selections, multiple tags
# ---------------------------------------------------------------------------


def test_a_job_with_no_location_tags_matches_no_active_location_filter(
    client, db_conn
):
    """An un-normalized job is not "everywhere".

    Roughly a fifth of OPEN rows have no ``job_locations`` entry at any moment
    (newly scraped, or a location string the pipeline could not resolve). Letting
    them fall through an active location filter would be the loudest possible
    version of this endpoint's failure mode: every filter would look broken.
    ``United States`` is checked alongside the exact name because the meta-option
    takes a different resolution path and could regress on its own.
    """
    austin = _place(db_conn, "Austin, TX, US", city="Austin", region="TX", country="US")
    _job(db_conn, "normalized", austin)
    _job(db_conn, "not-normalized")

    assert _all_ids(client) == {"normalized", "not-normalized"}

    assert _ids(_search(client, location="Austin, TX, US")) == {"normalized"}
    assert _ids(_search(client, location="United States")) == {"normalized"}


def test_multiple_location_selections_or_together_and_a_multi_tagged_job_matches_via_any(
    client, db_conn
):
    """Within a dimension, values OR; and a job carries as many location tags as
    the posting named, so ANY of them satisfying ANY selection is a match.

    The multi-tagged job is also the duplication check. Each selection compiles to
    its own EXISTS, so a job matching two of them at once must still be ONE row —
    a join-based implementation would return it twice, inflating both the page and
    ``filteredTotal`` while quietly consuming a slot in the page size.
    """
    austin = _place(db_conn, "Austin, TX, US", city="Austin", region="TX", country="US")
    berlin = _place(db_conn, "Berlin, BE, DE", city="Berlin", region="BE", country="DE")
    paris = _place(db_conn, "Paris, IDF, FR", city="Paris", region="IDF", country="FR")
    _job(db_conn, "austin-and-berlin", austin, berlin)
    _job(db_conn, "austin-only", austin)
    _job(db_conn, "berlin-only", berlin)
    _job(db_conn, "paris-only", paris)

    assert _all_ids(client) == {
        "austin-and-berlin",
        "austin-only",
        "berlin-only",
        "paris-only",
    }

    # The dual-tagged job matches through its SECOND tag, not its first.
    assert _ids(_search(client, location="Berlin, DE")) == set()
    assert _ids(_search(client, location="Berlin, BE, DE")) == {
        "austin-and-berlin",
        "berlin-only",
    }

    body = _search(client, location=["Austin, TX, US", "Berlin, BE, DE"])

    assert _ids(body) == {"austin-and-berlin", "austin-only", "berlin-only"}
    assert len(body["jobs"]) == 3, "a job matching two selections must appear once"
    assert body["meta"]["filteredTotal"] is None


def test_a_city_with_no_region_or_country_matches_a_selection_that_also_has_none(
    client, db_conn
):
    """The NULL-vs-NULL case, carried over deliberately from the client matcher.

    JavaScript's ``null === null`` is true, so a city the pipeline could only pin
    down to a bare name matches a selection pinned down no further. SQL's ``=``
    yields NULL there and the row vanishes — which is why the port uses
    ``IS NOT DISTINCT FROM``. The fully-qualified decoy holds the other side of
    the line: an absent region is not a wildcard that swallows every Springfield.
    """
    # The row the selection resolves through — attached to no job.
    _place(db_conn, "Springfield", city="Springfield")
    # Same structureless place under a different canonical name, so the match must
    # come from the NULL-tolerant field comparison and not from name equality.
    bare = _place(db_conn, "springfield (raw)", city="springfield")
    qualified = _place(
        db_conn, "Springfield, IL, US", city="Springfield", region="IL", country="US"
    )
    _job(db_conn, "unqualified", bare)
    _job(db_conn, "illinois", qualified)

    assert _all_ids(client) == {"unqualified", "illinois"}

    body = _search(client, location="Springfield")

    assert _ids(body) == {"unqualified"}


# ---------------------------------------------------------------------------
# Duplicate canonical names
# ---------------------------------------------------------------------------
#
# ``locations.canonical_name`` is NOT unique — uniqueness is on the structured
# tuple — so one display label can front several rows. In prod 48 labels do
# (e.g. "Remote (US)" spread across six different ``remote_scope`` spellings, and
# "New York, NY, US" existing as both a city and a region row).
#
# Those duplicates are inconsistently-normalized DIFFERENT places, not spellings
# of one place, so OR-ing their predicates together is a silent, large widening
# of the filter rather than a harmless superset. The frontend resolves a
# selection to exactly one descriptor; the server must too. These tests pin that.


def test_a_duplicated_remote_label_does_not_match_every_remote_tag(
    client, db_conn, seed_taxonomy
):
    """The prod shape that made this urgent.

    Two rows share the label "Remote (US)": the popular one is scoped to ``us``,
    the other has a NULL scope. A NULL wanted-scope means "any remote tag", so
    unioning the two predicates turns a US-only filter into "every remote job on
    the board" — Remote (Canada), Remote (India) and the rest all match.
    """
    us_remote = _place(db_conn, "Remote (US)", kind="remote", remote_scope="us")
    # Same label, no scope. Fewer jobs reference it, so it must lose.
    _place(db_conn, "Remote (US)", kind="remote", remote_scope=None, country="US")
    canada_remote = _place(db_conn, "Remote (Canada)", kind="remote", remote_scope="ca")

    _job(db_conn, "us-1", us_remote)
    _job(db_conn, "us-2", us_remote)
    _job(db_conn, "ca-1", canada_remote)

    assert _ids(_search(client, location="Remote (US)")) == {"us-1", "us-2"}


def test_a_duplicated_city_label_does_not_widen_to_its_whole_region(
    client, db_conn, seed_taxonomy
):
    """"New York, NY, US" exists in prod as both a city row and a region row.

    Unioned, the selection quietly returns every job anywhere in New York State.
    The city row is what the reader picked (it carries the jobs), so it wins and
    the upstate job stays out.
    """
    nyc = _place(
        db_conn, "New York, NY, US", kind="city", city="New York", region="NY", country="US"
    )
    _place(db_conn, "New York, NY, US", kind="region", region="NY", country="US")
    upstate = _place(
        db_conn, "Albany, NY, US", kind="city", city="Albany", region="NY", country="US"
    )

    _job(db_conn, "nyc-1", nyc)
    _job(db_conn, "nyc-2", nyc)
    _job(db_conn, "albany-1", upstate)

    assert _ids(_search(client, location="New York, NY, US")) == {"nyc-1", "nyc-2"}


def test_the_most_referenced_duplicate_wins_regardless_of_insert_order(
    client, db_conn, seed_taxonomy
):
    """Resolution is by job count, then lowest id — never by physical row order.

    Here the WIDER row is inserted first and would win any id-ordered tie-break,
    so this fails if the ranking silently degrades to "first row".
    """
    # Inserted first, but carries a single job.
    lonely = _place(db_conn, "Springfield", kind="region", region="XX", country="US")
    popular = _place(
        db_conn, "Springfield", kind="city", city="Springfield", region="IL", country="US"
    )
    other_in_xx = _place(
        db_conn, "Shelbyville, XX, US", kind="city", city="Shelbyville",
        region="XX", country="US",
    )

    _job(db_conn, "sf-1", popular)
    _job(db_conn, "sf-2", popular)
    _job(db_conn, "sf-3", popular)
    _job(db_conn, "lonely-1", lonely)
    _job(db_conn, "shelby-1", other_in_xx)

    # The city row wins on job count, so the region-XX sibling does not drag in
    # Shelbyville. "lonely-1" still matches by exact canonical name.
    assert _ids(_search(client, location="Springfield")) == {
        "sf-1", "sf-2", "sf-3", "lonely-1",
    }


def test_a_resolution_flip_mid_walk_invalidates_the_cursor(client, db_conn, seed_taxonomy):
    """A duplicated canonical_name whose winner flips mid-walk must 409, not drift.

    ``_RESOLVE_LOCATIONS_SQL`` ranks same-named ``locations`` rows by their live
    ``job_locations`` count, and prod carries 48 duplicated canonical names. A
    scrape that moves jobs between two same-named rows changes which descriptor
    the filter actually uses — so the reader keeps paging, every cursor still
    validates, and the filter set has silently changed underneath them.

    Fingerprinting the raw selection cannot see that, because the selection string
    never changed. Fingerprinting what it RESOLVED to can. Without the
    ``location_resolved`` key this test fails by returning 200.
    """
    loser = _place(db_conn, "Springfield", city="Springfield", region="IL", country="US")
    winner = _place(db_conn, "Springfield", city="Springfield", region="MO", country="US")

    # `winner` starts with the higher job_locations count, so it resolves first.
    for i in range(3):
        _job(db_conn, f"spring-win-{i}", winner)
    _job(db_conn, "spring-lose-0", loser)

    first = client.get("/api/jobs/search", params={"location": "Springfield", "limit": 1})
    assert first.status_code == 200
    cursor = first.json()["nextCursor"]
    assert cursor, "need a live cursor to exercise the flip"

    # Flip the ranking: `loser` now outnumbers `winner`, so a different row wins.
    for i in range(5):
        _job(db_conn, f"spring-flip-{i}", loser)

    second = client.get(
        "/api/jobs/search",
        params={"location": "Springfield", "limit": 1, "cursor": cursor},
    )
    assert second.status_code == 409, (
        "the resolution flipped between pages but the cursor was still accepted "
        f"(got {second.status_code}) — the walk silently changed filter sets"
    )
