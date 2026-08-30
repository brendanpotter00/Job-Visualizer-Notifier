"""AC-13 / AC-13a — the company-name dedupe, the third rung of the ladder.

THE CASE, in the owner's words: he watched ``lifeatspotify.com`` run a full one-time
discovery — headless Chromium plus a Claude call — and only *then* get told "this looks
like Spotify, which we already track", from the job-title overlap that can only run once
a discovery has finished.

    "The point of deduping things is to catch it before we do the expensive stuff...
    all those URLs are gonna have like Cisco in them, or in this case all of them are
    gonna have Spotify in them."

**AC-13** (fast: one HTTP resolve, no browser, no LLM) is the end-to-end assertion that
it now answers first: 200 ``already_public`` with ``matchKind='name'``, no company row,
no ``user_companies`` row, and — the assertion the whole unit exists for — **no
``custom_discovery`` job**.

**AC-13a** (hermetic: no network at all) runs the production matcher against the e2e
database's REAL published fleet, which is a clone of prod's ~135 companies. That is the
part a unit test cannot buy: the rule's whole risk is false positives against the actual
set of names we publish, and here it is measured against them rather than against a
fixture chosen to make it look good. It pins the ``dropbox``/``box`` decision and the
``figma``/``gm`` collision that exists in the real table today.
"""

from __future__ import annotations

import boards
import pytest
from conftest import db, require_reachable

# Imported directly — same import root AC-06a uses (src/backend on sys.path via
# conftest.py) — so AC-13a exercises the REAL production matcher and the REAL SELECT.
from api.services.company_name_match import (  # noqa: E402
    build_name_index,
    match_name_in_url,
)
from api.services.custom_companies_service import (  # noqa: E402
    find_public_company_by_name,
)

SPOTIFY_URL = boards.SPOTIFY.url
PRIMARY_EMAIL = "e2e+add-companies@jvn.test"


class TestNameMatchStopsTheSpend:
    """AC-13 — the rung answers before anything expensive happens."""

    def test_ac13_a_vanity_careers_domain_links_instead_of_discovering(
        self, http, db_conn
    ):
        require_reachable(boards.SPOTIFY)
        before_user = db.visibility_count(db_conn, "user")
        before_attempts = db.add_attempts_count(db_conn)
        before_discovery_jobs = db.procrastinate_job_count(
            db_conn, queue_name="custom_discovery"
        )

        resp = http.post("/api/users/companies", json={"url": SPOTIFY_URL})

        assert resp.status_code == 200, (
            f"AC-13: lifeatspotify.com must resolve to already_public before any "
            f"discovery; got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("status") == "already_public", body
        assert body["companyId"] == "spotify"
        assert body["displayName"] == "Spotify"

        # AC-13 assertion 1: it must announce itself as a GUESS, not as a board match.
        # The UI keys the hedged headline and the "This isn't the same company"
        # correction off exactly this field; reporting 'board' here would make a string
        # match in a domain terminal.
        assert body.get("matchKind") == "name", (
            "AC-13 assertion 1: a name guess must be labelled 'name' so the UI can "
            f"hedge it and keep a way out; got matchKind={body.get('matchKind')!r}"
        )
        assert "looks like" in body["detail"], (
            "AC-13 assertion 1: the copy must read as a likelihood. The exact rungs say "
            f"'the same job board'; this one must not. got: {body['detail']!r}"
        )

        # AC-13 assertion 2: NOTHING WAS ENQUEUED. This is the unit.
        after_discovery_jobs = db.procrastinate_job_count(
            db_conn, queue_name="custom_discovery"
        )
        assert after_discovery_jobs == before_discovery_jobs, (
            "AC-13 assertion 2: a name match must not cost a custom_discovery job — "
            "that job is the headless Chromium session and the Claude call this whole "
            f"rung exists to avoid (was {before_discovery_jobs}, now "
            f"{after_discovery_jobs})"
        )

        # AC-13 assertion 3: NOTHING WAS CREATED.
        after_user = db.visibility_count(db_conn, "user")
        assert after_user == before_user, (
            "AC-13 assertion 3: already_public must create no companies row "
            f"(visibility='user' count was {before_user}, now {after_user})"
        )

        # AC-13 assertion 4: the audit gains exactly one row, and it names WHICH rung
        # answered — this is the only rung whose hits are worth reviewing for false
        # positives, so it must be greppable.
        after_attempts = db.add_attempts_count(db_conn)
        assert after_attempts == before_attempts + 1, (
            f"AC-13 assertion 4: expected exactly one new add attempt "
            f"(was {before_attempts}, now {after_attempts})"
        )
        user_id = db.user_id_for_email(db_conn, PRIMARY_EMAIL)
        latest = db.latest_add_attempt(db_conn, user_id=user_id)
        assert latest is not None
        assert latest["outcome"] == "already_public"
        assert latest["company_id"] == "spotify"
        assert latest["resolved_ats"] == "name_guess", (
            "AC-13 assertion 4: resolved_ats must record 'name_guess' — the audit's "
            "record of which rung answered, and the handle for reviewing this rung's "
            f"false positives. got {latest['resolved_ats']!r}"
        )

    def test_ac13_the_correction_still_creates_the_private_copy(self, http, db_conn):
        """AC-13 assertion 5 — the way out survives, and it is why this rung is
        allowed to guess at all.

        Somebody whose company merely shares a string with one of ours must not be
        hard-blocked with no way to tell us we are wrong. This is the same
        ``trackAnyway`` the UI's "This isn't the same company" button sends.
        """
        require_reachable(boards.SPOTIFY)
        before_user = db.visibility_count(db_conn, "user")

        resp = http.post(
            "/api/users/companies", json={"url": SPOTIFY_URL, "trackAnyway": True}
        )

        assert resp.status_code == 202, (
            f"AC-13 assertion 5: the correction must route to the ordinary discovery "
            f"path; got {resp.status_code}: {resp.text}"
        )
        assert resp.json()["status"] == "discovery_pending"
        assert db.visibility_count(db_conn, "user") == before_user + 1, (
            "AC-13 assertion 5: a provisional private row must exist immediately"
        )

        company_id = resp.json()["id"]

        # AC-13 assertion 6: and a re-add now resolves to THAT row, not back to the
        # public notice — the `owned is None` guard, on this rung.
        #
        # THE STATUS MIRRORS THE BOARD'S STATE, and both legal answers are asserted
        # rather than either being waved through. d27379e made the re-add body agree
        # with the row it hands back: a board still being set up answers 202
        # `discovery_pending`, a tracked one keeps its 200, and the green "Now
        # tracking" card is reserved for a row that actually is. Which of the two we
        # get here is a race against a live ~30s discovery, so the assertion pins the
        # PAIRING — status code to `status` string — rather than guessing the timing.
        # What must hold either way is this assertion's actual subject: the same
        # private row comes back, and never the name-guess notice.
        again = http.post("/api/users/companies", json={"url": SPOTIFY_URL})
        body = again.json()
        assert again.status_code in (200, 202), again.text
        if again.status_code == 202:
            assert body.get("status") == "discovery_pending", (
                "AC-13 assertion 6: a 202 re-add must say the setup is still "
                f"running; got {body}"
            )
        else:
            assert body.get("status") != "discovery_pending", (
                "AC-13 assertion 6: a 200 re-add claims the board is tracked, so it "
                f"must not also report the setup as pending; got {body}"
            )
        assert body.get("id") == company_id, (
            "AC-13 assertion 6: the re-add must resolve to the private row the "
            f"correction created ({company_id}); got {body}"
        )
        assert body.get("status") != "already_public", (
            "AC-13 assertion 6: a caller who already owns a private copy must get "
            f"their own row back, not the name-guess notice; got {body}"
        )


class TestNameMatchAgainstTheRealFleet:
    """AC-13a — the rule measured against the REAL published companies, offline.

    No network, no browser, no LLM. The e2e database carries a clone of prod's public
    ``companies`` rows, and the risk this rule actually has is false positives against
    THAT set of names — so this is the case that measures it.
    """

    def _index(self, conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, display_name FROM companies "
                "WHERE visibility = 'public' AND enabled"
            )
            rows = [(r["id"], r["display_name"] or "") for r in cur.fetchall()]
        assert len(rows) >= 100, (
            "fixture precondition: the e2e DB should carry the real published fleet "
            f"(~133 enabled public rows); found {len(rows)}"
        )
        return rows, build_name_index(rows)

    def test_ac13a_the_owners_cases_resolve_against_the_real_fleet(self, db_conn):
        rows, index = self._index(db_conn)
        assert match_name_in_url("https://www.lifeatspotify.com/jobs", index) == "spotify"
        assert match_name_in_url("https://lifeatspotify.com/", index) == "spotify"
        # And through the real DB-backed function the router actually calls.
        found = find_public_company_by_name(db_conn, "https://www.lifeatspotify.com/jobs")
        assert found is not None and found["id"] == "spotify", found

    def test_ac13a_dropbox_is_never_answered_as_box(self, db_conn):
        """The collision the rule is shaped around. ``dropbox`` contains ``box``, and a
        naive substring match tells a Dropbox user we already track their company."""
        rows, index = self._index(db_conn)
        # Against the real fleet, dropbox.com is Dropbox — and never anything shorter.
        assert match_name_in_url("https://www.dropbox.com/jobs", index) == "dropbox"
        # And with a hypothetical Box published alongside it, still Dropbox.
        with_box = build_name_index(rows + [("box", "Box")])
        assert match_name_in_url("https://www.dropbox.com/jobs", with_box) == "dropbox"
        assert match_name_in_url("https://www.box.com/careers", with_box) == "box"

    def test_ac13a_the_real_short_name_collisions_never_win(self, db_conn):
        """``gm`` (General Motors) is a substring of ``figma``, ``judgmentlabs`` and
        ``thinkingmachines`` in the published table TODAY. This is the ``box``/``dropbox``
        class as it actually exists, not as a hypothetical."""
        _, index = self._index(db_conn)
        for url in (
            "https://www.figma.com/careers",
            "https://www.thinkingmachines.ai/careers",
            "https://judgmentlabs.ai/careers",
        ):
            assert match_name_in_url(url, index) != "gm", url
        assert match_name_in_url("https://gm.com/careers", index) == "gm"

    @pytest.mark.parametrize(
        "url",
        [
            "https://boards.greenhouse.io/spotify",
            "https://job-boards.greenhouse.io/anthropic",
            "https://jobs.lever.co/spotify",
            "https://jobs.ashbyhq.com/cursor",
            "https://spotify.wd1.myworkdayjobs.com/en-US/careers",
            "https://jobs.gem.com/retool",
            "https://www.linkedin.com/company/spotify/jobs/",
        ],
    )
    def test_ac13a_an_ats_host_never_name_matches(self, db_conn, url):
        """``jobs.lever.co`` reduces to the label ``lever``, and every board token in
        the path belongs to somebody else. Rung 1 owns these URLs."""
        _, index = self._index(db_conn)
        assert match_name_in_url(url, index) is None
        assert find_public_company_by_name(db_conn, url) is None

    @pytest.mark.parametrize(
        "url",
        [
            # Real careers domains for companies we do not publish.
            "https://www.tesla.com/careers",
            "https://www.atlassian.com/company/careers/all-jobs",
            "https://www.janestreet.com/join-jane-street/open-roles/",
            "https://jobs.cisco.com/jobs/SearchJobs/",
            "https://careers.oracle.com/",
            "https://www.teamsnap.com/careers",   # 'team' + 'snap' — Snap IS published
            "https://www.blockchain.com/careers",  # 'block' + 'chain' — Block IS published
            "https://flashlight.com/careers",      # 'light' — Light IS published
        ],
    )
    def test_ac13a_an_unrelated_company_is_never_claimed(self, db_conn, url):
        """The negative control against the real fleet. The last three are the danger
        class: 46 of the 147 published name keys are ordinary English words, so a rule
        that merely CONTAINED a name would claim all of these."""
        _, index = self._index(db_conn)
        assert match_name_in_url(url, index) is None, (
            f"AC-13a: {url} must not be claimed — a false hit sends somebody to the "
            "wrong company's chart and tells them they are covered when they are not"
        )

    def test_ac13a_the_five_script_boards_are_left_to_the_exact_host_table(self, db_conn):
        """Amazon, Apple, Google, Microsoft and TikTok are excluded from the name index.

        They already have an EXACT declared careers-host table one rung up, and that
        table's refusals are judgements: ``learn.microsoft.com`` is a training site and
        ``google.com/maps`` is a map. A guess must not overturn an exact ``None``.
        """
        _, index = self._index(db_conn)
        for url in (
            "https://learn.microsoft.com/en-us/training/",
            "https://aws.amazon.com/careers/",
            "https://www.google.com/maps",
            "https://www.apple.com/careers/",
            "https://www.amazon.jobs/en/search",
        ):
            assert match_name_in_url(url, index) is None, url
