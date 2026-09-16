"""ENR-PAR-2 — the CROSS-REPO taxonomy parity guard.

Every other guard in this epic is intra-repo: SCHEMA-5/SCHEMA-9 assert JVN
migration <-> JVN API, ENR-PAR-1 asserts frozenset <-> two markdown files <->
ollama enum <-> live prompt, FE-CT-2 asserts frontend arity. NOTHING compares
ACROSS the repos, which is precisely how the current 6-vs-7 category drift
survived — and this plan widens that surface from 6 slugs to 23.

TWO HALVES.

(a) PR-blocking, no network — compare the VENDORED snapshot at
    `golden/taxonomy-parity/jvn_facets.json`. That file is JVN's
    `src/backend/taxonomy.json` (SCHEMA-15's artifact) copied verbatim, plus a
    recorded sha256. It is DELIBERATELY not re-derived here: re-typing a slug
    list in this repo is exactly the seam SCHEMA-15 exists to close.

(b) Scheduled, live — `cli parity-check --base-url <JVN>`, run daily by
    launchd (`scripts/com.bp.jvn-taxonomy-parity.plist`), which texts on
    divergence. `@pytest.mark.network` here, skipped unless JVN_BASE_URL is set
    AND PARITY_CHECK=1, so it never breaks the offline unit suite.

The pure comparison function is covered by canned-payload unit tests below, so
the checker itself is tested without a network in either case.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from job_enricher import cli
from job_enricher import taxonomy as tax

SNAPSHOT = cli.TAXONOMY_PARITY_SNAPSHOT
SNAPSHOT_SHA_FILE = SNAPSHOT.with_suffix(".sha256")


def _canonical_payload() -> dict:
    """A payload matching the contract exactly — the fixture the negative cases
    are perturbed from. This is a TEST FIXTURE for the comparator, not a
    substitute for the vendored snapshot."""
    return {
        "categories": [{"slug": c} for c in sorted(tax.CATEGORIES)],
        "subcategories": [
            {
                "slug": slug,
                "label": label,
                "sortOrder": sort_order,
                "parentSlug": "software_engineering",
            }
            for sort_order, slug, label in cli.CANONICAL_SUBCATEGORY_TABLE
        ],
        "subcategory_sources": sorted(tax.SUBCATEGORY_SOURCES),
    }


# ---- (a) the vendored snapshot --------------------------------------------
# These two tests used to `pytest.skip()` when the snapshot was absent. That
# made half (a) — the PR-BLOCKING, no-network half — report success while
# asserting nothing: the cross-repo drift surface stayed wide open and green.
# The snapshot is now vendored, so its ABSENCE is a hard failure. Never turn
# these back into skips; a missing snapshot IS the defect.
_MISSING = (
    f"{SNAPSHOT} is MISSING. This is half (a) of ENR-PAR-2 — the PR-blocking, "
    "no-network cross-repo guard — and without the file it asserts NOTHING. "
    "The file is JVN's `src/backend/taxonomy.json` (SCHEMA-15's artifact) "
    "copied VERBATIM; never re-derive the slug list here. Restore both files "
    "together with the commands in golden/taxonomy-parity/README.md."
)


def test_vendored_snapshot_matches_the_enricher_taxonomy():
    assert SNAPSHOT.exists(), _MISSING
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    problems = cli.compare_taxonomy_snapshot(snap)
    assert problems == [], problems


def test_vendored_snapshot_sha256_is_recorded_and_matches():
    """A recorded sha means a hand-edit of the vendored copy is caught. If the
    snapshot legitimately changed, refresh BOTH files together."""
    assert SNAPSHOT.exists(), _MISSING
    assert SNAPSHOT_SHA_FILE.exists(), f"{SNAPSHOT_SHA_FILE} is MISSING. " + _MISSING
    recorded = SNAPSHOT_SHA_FILE.read_text(encoding="utf-8").split()[0].strip()
    actual = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    assert actual == recorded


def test_the_vendored_snapshot_is_the_jvn_artifact_not_a_rederived_list():
    """The snapshot must be JVN's whole `taxonomy.json`, not a slug list typed
    (or `--write-snapshot`-normalised) in THIS repo. The generator emits
    `levels` too and this repo never writes that key, so its presence is a cheap
    proof the file came from the other side of the seam."""
    assert SNAPSHOT.exists(), _MISSING
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert "levels" in snap, (
        "vendored snapshot has no `levels` key — it looks re-derived in this "
        "repo rather than copied from JVN's src/backend/taxonomy.json"
    )
    assert {lv["slug"] for lv in snap["levels"]} == set(tax.LEVELS)


# ---- the comparator itself, against canned payloads ------------------------
def test_the_exact_seventeen_pass():
    assert cli.compare_taxonomy_snapshot(
        cli.normalize_facets_payload(_canonical_payload())
    ) == []


def test_a_sixteen_slug_payload_fails():
    payload = _canonical_payload()
    payload["subcategories"] = payload["subcategories"][:-1]
    problems = cli.compare_taxonomy_snapshot(cli.normalize_facets_payload(payload))
    assert any("enricher-only" in p for p in problems)


def test_an_eighteen_slug_payload_fails():
    payload = _canonical_payload()
    payload["subcategories"].append(
        {"slug": "blockchain", "label": "Blockchain", "sortOrder": 17,
         "parentSlug": "software_engineering"}
    )
    problems = cli.compare_taxonomy_snapshot(cli.normalize_facets_payload(payload))
    assert any("JVN-only ['blockchain']" in p for p in problems)


def test_a_renamed_slug_fails_both_directions():
    payload = _canonical_payload()
    next(s for s in payload["subcategories"]
         if s["slug"] == "backend")["slug"] = "back_end"
    problems = cli.compare_taxonomy_snapshot(cli.normalize_facets_payload(payload))
    assert any("JVN-only" in p for p in problems)
    assert any("enricher-only" in p for p in problems)


def test_a_wrong_label_fails():
    """⚠ Addressed BY SLUG, not by index. Inserting `growth_engineering` and
    `product_engineering` mid-list moved `quantitative` from index 12 to 14 —
    an index literal here would have gone on passing while testing a different
    row."""
    payload = _canonical_payload()
    row = next(s for s in payload["subcategories"] if s["slug"] == "quantitative")
    row["label"] = "Quantitative & Trading"
    problems = cli.compare_taxonomy_snapshot(cli.normalize_facets_payload(payload))
    assert any("quantitative: label" in p for p in problems)


def test_a_wrong_sort_order_fails():
    payload = _canonical_payload()
    payload["subcategories"][0]["sortOrder"] = 99
    problems = cli.compare_taxonomy_snapshot(cli.normalize_facets_payload(payload))
    assert any("sort_order" in p for p in problems)


def test_a_wrong_parent_slug_fails():
    payload = _canonical_payload()
    next(s for s in payload["subcategories"]
         if s["slug"] == "devops_sre")["parentSlug"] = "devops"
    problems = cli.compare_taxonomy_snapshot(cli.normalize_facets_payload(payload))
    assert any("parent_slug" in p for p in problems)


def test_a_seventh_category_fails_and_names_project_manager():
    """The drift that is live TODAY: JVN's job_categories still carries
    `project_manager` while taxonomy.CATEGORIES has six."""
    payload = _canonical_payload()
    payload["categories"].append({"slug": "project_manager"})
    problems = cli.compare_taxonomy_snapshot(cli.normalize_facets_payload(payload))
    assert any("project_manager" in p for p in problems)


def test_wrong_subcategory_sources_fails():
    payload = _canonical_payload()
    payload["subcategory_sources"] = ["classify", "backfill", "human"]
    problems = cli.compare_taxonomy_snapshot(cli.normalize_facets_payload(payload))
    assert any("subcategory_sources" in p for p in problems)


def test_allow_empty_subcategories_gates_only_the_subcategory_half():
    """The Phase-1 window: before SCHEMA-7 seeds the rows JVN reports none, and
    this check must not be red for the whole window — but CATEGORY parity is
    still enforced."""
    payload = _canonical_payload()
    payload["subcategories"] = []
    payload.pop("subcategory_sources")
    snap = cli.normalize_facets_payload(payload)
    assert cli.compare_taxonomy_snapshot(snap, allow_empty_subcategories=True) == []
    assert cli.compare_taxonomy_snapshot(snap, allow_empty_subcategories=False) != []

    payload["categories"].append({"slug": "project_manager"})
    snap = cli.normalize_facets_payload(payload)
    problems = cli.compare_taxonomy_snapshot(snap, allow_empty_subcategories=True)
    assert any("project_manager" in p for p in problems)


# ---- `--write-snapshot`: the watchdog must not erase its own evidence -------
#
# ⚠ `scripts/check_taxonomy_parity.sh` ALWAYS passes `--write-snapshot`, and the
# launchd job runs it daily. The write used to happen BEFORE the `if problems`
# return, so a genuine divergence overwrote the vendored "verbatim JVN copy" with
# the drifted live data — destroying half (a)'s only reference, reddening the two
# vendored-snapshot tests, and leaving a dirty TRACKED file that aborts
# `deploy.sh` step 3 on every prod deploy afterwards.

def _payload_with_levels():
    payload = _canonical_payload()
    payload["levels"] = [
        {"slug": lv, "label": lv.replace("_", " ").title(), "sortOrder": i,
         "parentSlug": None}
        for i, lv in enumerate(sorted(tax.LEVELS))
    ]
    return payload


def _point_snapshot_at(monkeypatch, tmp_path):
    snap_path = tmp_path / "jvn_facets.json"
    monkeypatch.setattr(cli, "TAXONOMY_PARITY_SNAPSHOT", snap_path)
    monkeypatch.setattr(cli, "TAXONOMY_PARITY_SHA", snap_path.with_suffix(".sha256"))
    return snap_path


def _run_parity_check(monkeypatch, payload, **overrides):
    import argparse

    import httpx

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _Resp())
    args = argparse.Namespace(
        base_url="http://jvn.test", timeout=5.0, write_snapshot=True,
        allow_empty_subcategories=False, text_on_divergence=False,
    )
    for k, v in overrides.items():
        setattr(args, k, v)
    return cli._cmd_parity_check(args)


def test_a_divergent_payload_NEVER_overwrites_the_vendored_snapshot(
    monkeypatch, tmp_path, capsys
):
    snap_path = _point_snapshot_at(monkeypatch, tmp_path)
    snap_path.write_text('{"the": "vendored JVN artifact"}\n', encoding="utf-8")
    payload = _payload_with_levels()
    payload["subcategories"] = payload["subcategories"][:-1]   # a real divergence

    rc = _run_parity_check(monkeypatch, payload)

    assert rc == 1
    assert snap_path.read_text(encoding="utf-8") == '{"the": "vendored JVN artifact"}\n'
    assert "snapshot NOT refreshed" in capsys.readouterr().err


def test_a_clean_payload_refreshes_the_snapshot_AND_its_recorded_sha(
    monkeypatch, tmp_path
):
    """`--write-snapshot` must leave the pair CONSISTENT. Writing the json and
    not the sha is what turns `test_vendored_snapshot_sha256_is_recorded_and_
    matches` red the next time the offline half runs."""
    import hashlib as _hashlib

    snap_path = _point_snapshot_at(monkeypatch, tmp_path)
    rc = _run_parity_check(monkeypatch, _payload_with_levels())

    assert rc == 0
    written = json.loads(snap_path.read_text(encoding="utf-8"))
    assert cli.compare_taxonomy_snapshot(written) == []
    recorded = snap_path.with_suffix(".sha256").read_text(encoding="utf-8").split()[0]
    assert recorded == _hashlib.sha256(snap_path.read_bytes()).hexdigest()


def test_the_written_snapshot_still_looks_like_the_JVN_artifact(monkeypatch, tmp_path):
    """The same assertion `test_the_vendored_snapshot_is_the_jvn_artifact_not_a_
    rederived_list` makes, applied to what `--write-snapshot` produces: the
    normalizer dropped `levels`, so every refresh degraded the vendored artifact
    into a list re-derived in this repo."""
    snap_path = _point_snapshot_at(monkeypatch, tmp_path)
    _run_parity_check(monkeypatch, _payload_with_levels())
    written = json.loads(snap_path.read_text(encoding="utf-8"))
    assert "levels" in written
    assert {lv["slug"] for lv in written["levels"]} == set(tax.LEVELS)


def test_a_payload_without_levels_is_refused_rather_than_written(
    monkeypatch, tmp_path, capsys
):
    snap_path = _point_snapshot_at(monkeypatch, tmp_path)
    rc = _run_parity_check(monkeypatch, _canonical_payload())   # parity OK, no levels

    assert rc == 0                       # parity itself passed
    assert not snap_path.exists()        # ...but the artifact was not degraded
    assert "no `levels`" in capsys.readouterr().out


def test_an_unchanged_snapshot_is_not_rewritten(monkeypatch, tmp_path, capsys):
    """The watchdog runs DAILY with `--write-snapshot`. Re-serializing an
    identical file still churns its bytes (the vendored copy carries the
    generator's formatting, not ours) and dirties a tracked file every day."""
    snap_path = _point_snapshot_at(monkeypatch, tmp_path)
    payload = _payload_with_levels()
    _run_parity_check(monkeypatch, payload)
    first = snap_path.read_bytes()
    capsys.readouterr()

    _run_parity_check(monkeypatch, payload)

    assert snap_path.read_bytes() == first
    assert "already up to date" in capsys.readouterr().out


# ---- the divergence text is an ALARM, so its failure cannot be silent -------
def _fake_home_with_send_sh(monkeypatch, tmp_path):
    home = tmp_path / "home"
    send = home / ".claude" / "skills" / "message-brendan" / "send.sh"
    send.parent.mkdir(parents=True)
    send.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    return send


def test_a_failed_divergence_text_is_logged_loudly(monkeypatch, tmp_path, caplog):
    """⚠ `subprocess.run(..., check=False)` with the result DISCARDED meant a
    failed SMS produced no exception and no log line at all — on the one channel
    whose own docstring says a log line nobody reads is the wrong shape."""
    import logging
    import subprocess

    _fake_home_with_send_sh(monkeypatch, tmp_path)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 1, "", "sendblue 401"),
    )
    with caplog.at_level(logging.ERROR, logger="job_enricher.cli"):
        cli._text_brendan("JVN taxonomy parity FAILED: boom")
    assert "DID NOT SEND" in caplog.text
    assert "sendblue 401" in caplog.text


def test_a_successful_divergence_text_logs_nothing(monkeypatch, tmp_path, caplog):
    import logging
    import subprocess

    _fake_home_with_send_sh(monkeypatch, tmp_path)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "sent", ""),
    )
    with caplog.at_level(logging.WARNING, logger="job_enricher.cli"):
        cli._text_brendan("JVN taxonomy parity FAILED: boom")
    assert caplog.text == ""


# ---- (b) the LIVE check ----------------------------------------------------
@pytest.mark.network
@pytest.mark.skipif(
    not (os.environ.get("JVN_BASE_URL") and os.environ.get("PARITY_CHECK") == "1"),
    reason="live parity check: set JVN_BASE_URL and PARITY_CHECK=1",
)
def test_live_jvn_facets_match_the_enricher_taxonomy():
    import httpx

    base = os.environ["JVN_BASE_URL"].rstrip("/")
    payload = httpx.get(f"{base}/api/jobs/facets", timeout=30.0).json()
    problems = cli.compare_taxonomy_snapshot(
        cli.normalize_facets_payload(payload),
        allow_empty_subcategories=os.environ.get("ALLOW_EMPTY_SUBCATEGORIES") == "1",
    )
    assert problems == [], problems
