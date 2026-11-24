"""ENR-PAR-2 — taxonomy parity between the enricher and the JVN backend.

ENR-PAR-1 (tests/test_taxonomy.py) checks the enricher's own copies of the
slugs against each other. This file compares them with the backend's.

TWO HALVES.

(a) PR-blocking, no network — compare the backend's generated artifact,
    `src/backend/taxonomy.json` (SCHEMA-15), read straight from this monorepo.
    It is DELIBERATELY not re-derived here: re-typing a slug list in the
    enricher is exactly the seam SCHEMA-15 exists to close.

(b) Scheduled, live — `cli parity-check --base-url <JVN>`, run daily by
    launchd (`scripts/com.bp.jvn-taxonomy-parity.plist`), which texts on
    divergence. `@pytest.mark.network` here, skipped unless JVN_BASE_URL is set
    AND PARITY_CHECK=1, so it never breaks the offline unit suite.

The pure comparison function is covered by canned-payload unit tests below, so
the checker itself is tested without a network in either case.
"""

from __future__ import annotations

import json
import os

import pytest

from job_enricher import cli
from job_enricher import taxonomy as tax

ARTIFACT = cli.JVN_TAXONOMY_ARTIFACT


def _canonical_payload() -> dict:
    """A payload matching the contract exactly — the fixture the negative cases
    are perturbed from. This is a TEST FIXTURE for the comparator, not a
    substitute for the backend artifact."""
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


# ---- (a) the backend's artifact, in-tree -----------------------------------
# A missing artifact is a hard FAILURE, never a skip: a skip would let half (a)
# report success while asserting nothing.
_MISSING = (
    f"{ARTIFACT} is MISSING. Half (a) of ENR-PAR-2 reads the JVN backend's "
    "generated taxonomy artifact from this monorepo (it expects src/enricher at "
    f"<JVN>/src/enricher). Regenerate it with {cli.JVN_TAXONOMY_GENERATOR}; "
    "never re-derive the slug list in the enricher."
)


def _artifact() -> dict:
    assert ARTIFACT.exists(), _MISSING
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_the_backend_artifact_matches_the_enricher_taxonomy():
    problems = cli.compare_taxonomy_snapshot(_artifact())
    assert problems == [], problems


def test_the_backend_artifact_levels_match_the_enricher_levels():
    """The generator emits `levels` too. Checking it keeps the level slugs in
    parity, and its presence shows the file is the generator's output rather
    than a list typed by hand."""
    snap = _artifact()
    assert "levels" in snap, (
        f"{ARTIFACT} has no `levels` key — it does not look like "
        f"{cli.JVN_TAXONOMY_GENERATOR}'s output"
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


# ---- the live command, with the network stubbed ----------------------------
def _payload_with_levels():
    payload = _canonical_payload()
    payload["levels"] = [
        {"slug": lv, "label": lv.replace("_", " ").title(), "sortOrder": i,
         "parentSlug": None}
        for i, lv in enumerate(sorted(tax.LEVELS))
    ]
    return payload


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
        base_url="http://jvn.test", timeout=5.0,
        allow_empty_subcategories=False, text_on_divergence=False,
    )
    for k, v in overrides.items():
        setattr(args, k, v)
    return cli._cmd_parity_check(args)


def test_a_clean_live_payload_passes(monkeypatch, capsys):
    assert _run_parity_check(monkeypatch, _payload_with_levels()) == 0
    assert "17/17 match" in capsys.readouterr().out


def test_a_divergent_live_payload_exits_1(monkeypatch, capsys):
    payload = _payload_with_levels()
    payload["subcategories"] = payload["subcategories"][:-1]
    assert _run_parity_check(monkeypatch, payload) == 1
    assert "enricher-only" in capsys.readouterr().err


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
