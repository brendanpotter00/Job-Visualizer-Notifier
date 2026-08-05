"""Unit tests for the pure URL → ATS candidate resolver (L0).

Three things are being pinned here:

1. **The matcher table**, one right and one wrong URL per ATS.
2. **Prod parity** — a resolved ``provider_config`` must equal what the live
   ``companies`` row already contains, because PR 3 will use this function to
   write exactly such rows. Values captured from prod on 2026-08-05.
3. **Purity** — the whole table still passes with ``socket.getaddrinfo``
   monkeypatched to raise, and importing the module in a *fresh subprocess*
   pulls in no LLM / agent / browser package. The subprocess matters: this test
   session has ``anthropic`` loaded via ``services/llm_client.py``, so an
   in-process check would be meaningless.
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

from api.services.ats_link_resolver import AtsCandidate, resolve_ats_url

# Mirrors ``scripts/one_off/recipe_spike/replay.py:34``, plus ``playwright``
# (D8 — the browser never enters this codebase).
FORBIDDEN_MODULES = (
    "anthropic",
    "openai",
    "stagehand",
    "browserbase",
    "langchain",
    "playwright",
)

_BACKEND_DIR = Path(__file__).resolve().parents[2]     # src/backend
_REPO_ROOT = _BACKEND_DIR.parents[1]                   # repo root


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch):
    """L0 is IO-free. Any DNS lookup at all fails the test."""

    def boom(*args, **kwargs):
        raise AssertionError("resolve_ats_url must never touch the network")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "create_connection", boom)


# ----------------------------------------------------------------------------
# The matcher table — one right URL per ATS
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected_ats,expected_token",
    [
        # greenhouse: both public board hosts, trailing slash, deep path, www.
        ("https://boards.greenhouse.io/acme", "greenhouse", "acme"),
        ("https://boards.greenhouse.io/acme/", "greenhouse", "acme"),
        ("https://job-boards.greenhouse.io/acme/jobs/123", "greenhouse", "acme"),
        ("https://www.boards.greenhouse.io/acme", "greenhouse", "acme"),
        ("https://BOARDS.GREENHOUSE.IO/acme?gh_src=x", "greenhouse", "acme"),
        # ashby: token lowercased (upstream is case-insensitive; verified live)
        ("https://jobs.ashbyhq.com/Sierra", "ashby", "sierra"),
        ("https://jobs.ashbyhq.com/sierra/", "ashby", "sierra"),
        ("https://jobs.ashbyhq.com/GigaML?utm_source=x", "ashby", "gigaml"),
        # lever
        ("https://jobs.lever.co/zoox", "lever", "zoox"),
        ("https://jobs.lever.co/zoox/abc-123", "lever", "zoox"),
        # gem — public host form confirmed live 2026-08-05 (jobs.gem.com/<token>
        # returns the board and api.gem.com/job_board/v0/<token>/job_posts/ backs it)
        ("https://jobs.gem.com/nominal", "gem", "nominal"),
        ("https://jobs.gem.com/nominal/37c9854b-f1ea-4da6-a3f5-51e64923ae08", "gem", "nominal"),
        # workday: tenant comes from the HOST
        ("https://blueorigin.wd5.myworkdayjobs.com/BlueOrigin", "workday", "blueorigin"),
        # eightfold: only with an explicit ?domain= (see the module docstring)
        (
            "https://explore.jobs.netflix.net/careers?domain=netflix.com",
            "eightfold",
            "netflix",
        ),
        ("https://acme.eightfold.ai/careers?domain=acme.com", "eightfold", "acme"),
    ],
)
def test_matcher_hits(url: str, expected_ats: str, expected_token: str) -> None:
    candidate = resolve_ats_url(url)
    assert candidate is not None, url
    assert candidate.ats == expected_ats
    assert candidate.board_token == expected_token
    assert candidate.source_url == url


@pytest.mark.parametrize(
    "url",
    [
        # bare board hosts name no board
        "https://boards.greenhouse.io/",
        "https://job-boards.greenhouse.io",
        "https://jobs.ashbyhq.com/",
        "https://jobs.lever.co",
        "https://jobs.gem.com/",
        "https://intel.wd1.myworkdayjobs.com/",
        # lookalike hosts
        "https://boards.greenhouse.io.evil.tld/acme",
        "https://jobs.ashbyhq.com.evil.tld/acme",
        "https://jobs.lever.co.evil.tld/acme",
        "https://jobs.gem.com.evil.tld/acme",
        "https://intel.wd1.myworkdayjobs.com.evil.tld/External",
        # eightfold on a non-allowlisted host, even with a domain param
        "https://explore.jobs.example.net/careers?domain=example.com",
        "https://eightfold.ai.evil.tld/careers?domain=acme.com",
        # eightfold on an allowlisted host but with no derivable tenant key
        "https://explore.jobs.netflix.net/careers",
        "https://explore.jobs.netflix.net/careers?domain=",
        # not an ATS at all
        "https://www.tesla.com/careers",
        "https://www.amazon.jobs",
        "https://www.metacareers.com/jobs",
        "https://jobs.intel.com",
        "https://jobs.cisco.com",
        # not even a fetchable URL
        "file:///etc/passwd",
        "",
        "   ",
        "not a url",
    ],
)
def test_matcher_misses(url: str) -> None:
    assert resolve_ats_url(url) is None


# ----------------------------------------------------------------------------
# Workday — the verified rule (PLAN §1.3)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,tenant,slug",
    [
        ("https://blueorigin.wd5.myworkdayjobs.com/BlueOrigin", "blueorigin", "BlueOrigin"),
        ("https://capitalone.wd12.myworkdayjobs.com/Capital_One", "capitalone", "Capital_One"),
        (
            "https://adobe.wd5.myworkdayjobs.com/external_experienced",
            "adobe",
            "external_experienced",
        ),
        ("https://disney.wd5.myworkdayjobs.com/disneycareer", "disney", "disneycareer"),
        # tenant != company id
        ("https://generalmotors.wd5.myworkdayjobs.com/Careers_GM", "generalmotors", "Careers_GM"),
        ("https://salesforce.wd12.myworkdayjobs.com/Slack", "salesforce", "Slack"),
        # the D11 acceptance target: slug is the FIRST segment, trailing
        # segments are ignored
        (
            "https://intel.wd1.myworkdayjobs.com/External/page/6042070b79e01001f04fa9b468070000",
            "intel",
            "External",
        ),
        ("https://cisco.wd5.myworkdayjobs.com/Cisco_Careers", "cisco", "Cisco_Careers"),
        # optional locale prefix is stripped
        ("https://blueorigin.wd5.myworkdayjobs.com/en-US/BlueOrigin", "blueorigin", "BlueOrigin"),
        ("https://blueorigin.wd5.myworkdayjobs.com/en/BlueOrigin", "blueorigin", "BlueOrigin"),
        # trailing junk of every shape is ignored
        ("https://intel.wd1.myworkdayjobs.com/External/job/US-Oregon/x_JR123", "intel", "External"),
        ("https://intel.wd1.myworkdayjobs.com/External/login", "intel", "External"),
        ("https://intel.wd1.myworkdayjobs.com/External/?q=engineer", "intel", "External"),
        # host is lowercased, uppercase input still resolves
        ("https://INTEL.WD1.MYWORKDAYJOBS.COM/External", "intel", "External"),
    ],
)
def test_workday_rule(url: str, tenant: str, slug: str) -> None:
    candidate = resolve_ats_url(url)
    assert candidate is not None, url
    assert candidate.ats == "workday"
    assert candidate.provider_config == {
        "base_url": f"https://{tenant}.wd{_wd_number(url)}.myworkdayjobs.com",
        "tenant_slug": tenant,
        "career_site_slug": slug,
    }
    # board_token is the tenant, from the host — never the path.
    assert candidate.board_token == tenant


def _wd_number(url: str) -> str:
    import re

    match = re.search(r"\.wd([0-9]+)\.myworkdayjobs\.com", url, re.IGNORECASE)
    assert match is not None
    return match.group(1)


def test_workday_slug_case_is_never_altered() -> None:
    """``BlueOrigin`` is not ``blueorigin``; the CXS endpoint is case-sensitive."""
    assert _slug("https://blueorigin.wd5.myworkdayjobs.com/BlueOrigin") == "BlueOrigin"
    assert _slug("https://capitalone.wd12.myworkdayjobs.com/Capital_One") == "Capital_One"
    assert (
        _slug("https://adobe.wd5.myworkdayjobs.com/external_experienced")
        == "external_experienced"
    )


def _slug(url: str) -> str:
    candidate = resolve_ats_url(url)
    assert candidate is not None
    return candidate.provider_config["career_site_slug"]


# ----------------------------------------------------------------------------
# Prod parity
# ----------------------------------------------------------------------------

# Captured live from prod on 2026-08-05:
#   SELECT id, ats, board_token, provider_config FROM companies
#    WHERE id IN ('blueorigin','capitalone','adobe','disney','gm','slack','netflix');
#
# Two documented departures from a literal byte-for-byte comparison, both
# because the prod value is NOT derivable from any URL:
#
#  * Workday ``board_token``. Prod stores the internal company id (``gm``,
#    ``slack``); the URL only spells the tenant (``generalmotors``,
#    ``salesforce``). ``workday_client.fetch_jobs`` never reads board_token, so
#    the field is cosmetic. Asserted for the non-Workday rows only.
#  * Adobe's ``default_facets``. A hand-tuned narrowing of the population
#    (``workday_client`` docstring: "NVIDIA and Adobe use this to narrow"),
#    with no representation anywhere in the URL. The three derivable keys are
#    compared instead.
PROD_ROWS: dict[str, dict] = {
    "blueorigin": {
        "url": "https://blueorigin.wd5.myworkdayjobs.com/BlueOrigin",
        "ats": "workday",
        "board_token": "blueorigin",
        "provider_config": {
            "base_url": "https://blueorigin.wd5.myworkdayjobs.com",
            "tenant_slug": "blueorigin",
            "career_site_slug": "BlueOrigin",
        },
    },
    "capitalone": {
        "url": "https://capitalone.wd12.myworkdayjobs.com/Capital_One",
        "ats": "workday",
        "board_token": "capitalone",
        "provider_config": {
            "base_url": "https://capitalone.wd12.myworkdayjobs.com",
            "tenant_slug": "capitalone",
            "career_site_slug": "Capital_One",
        },
    },
    "adobe": {
        "url": "https://adobe.wd5.myworkdayjobs.com/external_experienced",
        "ats": "workday",
        "board_token": "adobe",
        "provider_config": {
            "base_url": "https://adobe.wd5.myworkdayjobs.com",
            "tenant_slug": "adobe",
            "career_site_slug": "external_experienced",
        },
    },
    "disney": {
        "url": "https://disney.wd5.myworkdayjobs.com/disneycareer",
        "ats": "workday",
        "board_token": "disney",
        "provider_config": {
            "base_url": "https://disney.wd5.myworkdayjobs.com",
            "tenant_slug": "disney",
            "career_site_slug": "disneycareer",
        },
    },
    "gm": {
        "url": "https://generalmotors.wd5.myworkdayjobs.com/Careers_GM",
        "ats": "workday",
        "board_token": "gm",              # NOT derivable — see the note above
        "provider_config": {
            "base_url": "https://generalmotors.wd5.myworkdayjobs.com",
            "tenant_slug": "generalmotors",
            "career_site_slug": "Careers_GM",
        },
    },
    "slack": {
        "url": "https://salesforce.wd12.myworkdayjobs.com/Slack",
        "ats": "workday",
        "board_token": "slack",           # NOT derivable — see the note above
        "provider_config": {
            "base_url": "https://salesforce.wd12.myworkdayjobs.com",
            "tenant_slug": "salesforce",
            "career_site_slug": "Slack",
        },
    },
    "netflix": {
        "url": "https://explore.jobs.netflix.net/careers?domain=netflix.com",
        "ats": "eightfold",
        "board_token": "netflix",
        "provider_config": {
            "domain": "netflix.com",
            "tenant_host": "explore.jobs.netflix.net",
        },
    },
}

# Keys of a prod provider_config that the resolver cannot and should not invent.
_NON_DERIVABLE_KEYS = {"default_facets"}


@pytest.mark.parametrize("company_id", sorted(PROD_ROWS))
def test_provider_config_matches_prod(company_id: str) -> None:
    row = PROD_ROWS[company_id]
    candidate = resolve_ats_url(row["url"])
    assert candidate is not None, row["url"]
    assert candidate.ats == row["ats"]

    expected = {
        k: v for k, v in row["provider_config"].items() if k not in _NON_DERIVABLE_KEYS
    }
    assert candidate.provider_config == expected


@pytest.mark.parametrize(
    "company_id",
    [cid for cid, row in PROD_ROWS.items() if row["ats"] != "workday"],
)
def test_board_token_matches_prod_for_non_workday(company_id: str) -> None:
    row = PROD_ROWS[company_id]
    candidate = resolve_ats_url(row["url"])
    assert candidate is not None
    assert candidate.board_token == row["board_token"]


def test_candidate_is_frozen() -> None:
    candidate = resolve_ats_url("https://jobs.lever.co/zoox")
    assert isinstance(candidate, AtsCandidate)
    with pytest.raises(Exception):
        candidate.board_token = "hacked"    # type: ignore[misc]


# ----------------------------------------------------------------------------
# Import guard — subprocess, not in-process
# ----------------------------------------------------------------------------


def _import_in_subprocess(module: str) -> set[str]:
    """Import ``module`` in a clean interpreter; return which forbidden modules loaded."""
    script = (
        "import sys, json\n"
        f"import {module}\n"
        f"print(json.dumps(sorted(m for m in {FORBIDDEN_MODULES!r} if m in sys.modules)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(_BACKEND_DIR),
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONPATH": f"{_BACKEND_DIR}:{_REPO_ROOT}",
            "HOME": str(Path.home()),
        },
        timeout=120,
    )
    assert result.returncode == 0, (
        f"importing {module} failed:\n{result.stdout}\n{result.stderr}"
    )
    import json

    return set(json.loads(result.stdout.strip().splitlines()[-1]))


@pytest.mark.parametrize(
    "module",
    [
        "api.services.ats_link_resolver",
        "api.services.url_guard",
        "api.services.ats_discovery",
    ],
)
def test_no_agent_or_browser_imports(module: str) -> None:
    """No LLM / agent / browser package may be reachable from the resolve path.

    Run in a subprocess on purpose: the pytest session already has ``anthropic``
    loaded via ``services/llm_client.py``, so an in-process ``sys.modules``
    check would pass no matter what this module imported.
    """
    leaked = _import_in_subprocess(module)
    assert leaked == set(), f"{module} pulled in forbidden modules: {sorted(leaked)}"


def test_import_guard_would_actually_catch_a_leak() -> None:
    """Negative control: the guard must fail when a forbidden module IS loaded."""
    leaked = _import_in_subprocess("json, anthropic")
    assert "anthropic" in leaked
