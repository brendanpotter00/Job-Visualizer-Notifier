"""Free ATS board check against the public APIs (all mocked)."""

from launch_radar.ats import ats_check, pr_ready, safe_http_url, safe_token

from tests.unit.launch_radar_fakes import ats_transport

ASHBY = "https://api.ashbyhq.com/posting-api/job-board/Raindrop"
GH = "https://boards-api.greenhouse.io/v1/boards/ghost/jobs"
LEVER = "https://api.lever.co/v0/postings/acme?mode=json"


def test_ashby_verified_with_jobs():
    t = ats_transport({ASHBY: (200, {"jobs": [{"title": f"j{i}"} for i in range(9)]})})
    ats = ats_check("ashby", "Raindrop", "https://raindrop.ai/careers", None, transport=t)
    assert ats == {"provider": "ashby", "board_token": "Raindrop", "board_url": "https://jobs.ashbyhq.com/Raindrop",
                   "verified": True, "job_count": 9, "checked_url": ASHBY}
    assert pr_ready(ats)


def test_board_from_careers_url_when_token_missing():
    t = ats_transport({GH: (200, {"jobs": [{"title": "eng"}]})})
    ats = ats_check("other", None, "https://job-boards.greenhouse.io/ghost", None, transport=t)
    assert ats["provider"] == "greenhouse" and ats["board_token"] == "ghost" and ats["job_count"] == 1
    assert pr_ready(ats)


def test_lever_list_response_and_brief_board_url_kept():
    t = ats_transport({LEVER: (200, [{"text": "a"}, {"text": "b"}])})
    ats = ats_check("lever", "acme", None, "https://jobs.lever.co/acme", transport=t)
    assert ats["verified"] and ats["job_count"] == 2 and ats["board_url"] == "https://jobs.lever.co/acme"


def test_not_found_is_unverified_and_not_pr_ready():
    ats = ats_check("ashby", "Missing", None, None, transport=ats_transport({}))
    assert ats["verified"] is False and ats["job_count"] is None and ats["checked_url"] is None
    assert not pr_ready(ats)


def test_empty_board_is_verified_but_not_pr_ready():
    t = ats_transport({GH: (200, {"jobs": []})})
    ats = ats_check("greenhouse", "ghost", None, None, transport=t)
    assert ats["verified"] is True and ats["job_count"] == 0
    assert not pr_ready(ats)


def test_gem_and_workday_are_never_called():
    calls = []

    def handler(request):
        calls.append(request)
        raise AssertionError("no request expected")

    import httpx

    ats = ats_check("workday", "nvidia", "https://nvidia.wd5.myworkdayjobs.com/x", "https://nvidia.wd5.myworkdayjobs.com/x",
                    transport=httpx.MockTransport(handler))
    assert calls == []
    assert ats["provider"] == "workday" and not ats["verified"] and not pr_ready(ats)
    assert ats["board_url"] == "https://nvidia.wd5.myworkdayjobs.com/x"


def test_untrusted_token_and_urls_are_sanitized():
    assert safe_token("../../etc") is None
    assert safe_token("good-token_1") == "good-token_1"
    assert safe_http_url("javascript:alert(1)") is None
    assert safe_http_url("https://ok.example.com/x") == "https://ok.example.com/x"
    ats = ats_check("ashby", "a/b?c", None, "javascript:alert(1)", transport=ats_transport({}))
    assert ats["board_token"] is None and ats["board_url"] is None


def test_unknown_provider_maps_to_other_and_missing_to_none():
    assert ats_check("bamboohr", None, None, transport=ats_transport({}))["provider"] == "other"
    assert ats_check(None, None, None, transport=ats_transport({}))["provider"] == "none"
