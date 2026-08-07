"""Unit tests for deterministic ATS detection."""

from __future__ import annotations

import httpx
import pytest

from api.services import ats_detector
from api.services.ats_detector import (
    _candidate_from_url,
    _workday_config_from,
    detect_ats,
)
from urllib.parse import urlsplit



class TestCandidateFromUrl:
    def test_greenhouse(self):
        assert _candidate_from_url("https://boards.greenhouse.io/acme") == (
            "greenhouse", "acme", {},
        )

    def test_ashby(self):
        assert _candidate_from_url("https://jobs.ashbyhq.com/notion/x") == (
            "ashby", "notion", {},
        )

    def test_ashby_api(self):
        got = _candidate_from_url(
            "https://api.ashbyhq.com/posting-api/job-board/notion"
        )
        assert got == ("ashby", "notion", {})

    def test_lever(self):
        assert _candidate_from_url("https://jobs.lever.co/brex")[:2] == ("lever", "brex")

    def test_workday(self):
        ats, token, cfg = _candidate_from_url(
            "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"
        )
        assert ats == "workday"
        assert token == "nvidia"
        assert cfg["career_site_slug"] == "NVIDIAExternalCareerSite"
        assert cfg["base_url"] == "https://nvidia.wd5.myworkdayjobs.com"

    def test_unknown_returns_none(self):
        assert _candidate_from_url("https://careers.example.com/jobs") is None

    def test_workday_strips_locale(self):
        cfg = _workday_config_from(
            urlsplit("https://acme.wd1.myworkdayjobs.com/en-US/CareerSite")
        )
        assert cfg["career_site_slug"] == "CareerSite"


@pytest.mark.asyncio
class TestDetectAts:
    async def test_greenhouse_confirmed_by_probe(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "boards-api.greenhouse.io" in request.url.host
            return httpx.Response(200, json={"jobs": [{"id": 1, "title": "SWE"}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            det = await detect_ats("https://boards.greenhouse.io/acme", client)
        assert det is not None
        assert det.ats == "greenhouse"
        assert det.company_id == "acme"
        assert det.job_count == 1

    async def test_probe_404_means_no_match(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "not found"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            det = await detect_ats("https://boards.greenhouse.io/ghost", client)
        assert det is None

    async def test_empty_board_still_detected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"jobs": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            det = await detect_ats("https://boards.greenhouse.io/newco", client)
        assert det is not None and det.job_count == 0

    async def test_html_marker_fallback(self, monkeypatch):
        # Bypass DNS for the company domain fetch.
        monkeypatch.setattr(ats_detector.url_guard, "validate_public_url", lambda u: None)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "careers.acme.com":
                return httpx.Response(
                    200,
                    text='<script src="https://boards.greenhouse.io/embed/job_board?for=acmeco"></script>',
                )
            if "boards-api.greenhouse.io" in request.url.host:
                return httpx.Response(200, json={"jobs": [{"id": 9, "title": "X"}]})
            return httpx.Response(404)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            det = await detect_ats("https://careers.acme.com/jobs", client)
        assert det is not None
        assert det.ats == "greenhouse"
        assert det.company_id == "acmeco"

    async def test_unknown_site_returns_none(self, monkeypatch):
        monkeypatch.setattr(ats_detector.url_guard, "validate_public_url", lambda u: None)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>no ats here</html>")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            det = await detect_ats("https://careers.acme.com/jobs", client)
        assert det is None
