"""E7 Phase 2 Task A — ``fetch_jobs_with_meta`` surfaces total/cap/advance.

Pure client tests with a mocked ``http`` (no network). Two things every client
must guarantee: (1) ``fetch_jobs`` returns EXACTLY ``fetch_jobs_with_meta(...)[0]``
(the public crons are byte-identical), and (2) the evidence carries the trusted
total, the cap flag, and page-advance disjointness the gate reads.
"""

from __future__ import annotations

import pytest

from api.services import eightfold_client, greenhouse_client, workday_client

pytestmark = pytest.mark.asyncio


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _GetHttp:
    """Fake AsyncClient exposing ``.get`` — handler maps (url, params) → payload."""

    def __init__(self, handler):
        self._handler = handler

    async def get(self, url, params=None, headers=None, timeout=None):
        return _Resp(self._handler(url, params))


class _PostHttp:
    """Fake AsyncClient exposing ``.post`` — handler maps (url, body) → payload."""

    def __init__(self, handler):
        self._handler = handler

    async def post(self, url, json=None, headers=None, timeout=None):
        return _Resp(self._handler(url, json))


# --- Greenhouse -------------------------------------------------------------

async def test_greenhouse_captures_meta_total_and_parity():
    payload = {"jobs": [{"id": i} for i in range(65)], "meta": {"total": 65}}
    jobs, ev = await greenhouse_client.fetch_jobs_with_meta(
        "board", _GetHttp(lambda url, params: payload)
    )
    assert len(jobs) == 65
    assert ev.declared_total == 65
    assert ev.cap_hit is False
    assert ev.terminated_cleanly is True
    assert ev.page_advance_ok is None  # single-shot

    # Parity: fetch_jobs returns exactly the meta variant's first element.
    jobs_only = await greenhouse_client.fetch_jobs(
        "board", _GetHttp(lambda url, params: payload)
    )
    assert jobs_only == jobs


async def test_greenhouse_missing_meta_total_is_none_no_raise():
    payload = {"jobs": [{"id": 1}, {"id": 2}]}  # no meta at all
    jobs, ev = await greenhouse_client.fetch_jobs_with_meta(
        "board", _GetHttp(lambda url, params: payload)
    )
    assert len(jobs) == 2
    assert ev.declared_total is None


# --- Workday ----------------------------------------------------------------

_WD_CFG = {"base_url": "https://x.wd5.myworkdayjobs.com",
           "tenant_slug": "t", "career_site_slug": "s"}


def _wd_page(offset: int, count: int, *, total: int):
    """`count` distinct postings starting at `offset`, with a fixed `total`."""
    postings = [
        {"title": f"J{offset+k}", "externalPath": f"/job/{offset+k}",
         "bulletFields": [f"JR{offset+k}"]}
        for k in range(count)
    ]
    return {"jobPostings": postings, "total": total}


async def test_workday_cap_hit_when_total_unreached():
    """100 full pages that never reach total=11960 → cap_hit, terminated=False."""
    def handler(url, body):
        return _wd_page(body["offset"], 20, total=11960)

    postings, ev = await workday_client.fetch_jobs_with_meta(_WD_CFG, _PostHttp(handler))
    assert ev.cap_hit is True
    assert ev.terminated_cleanly is False
    assert ev.declared_total == 11960
    assert len(postings) == 2000  # 100 pages * 20 (the silent-partial ceiling)


async def test_workday_small_tenant_advances_cleanly():
    def handler(url, body):
        return _wd_page(body["offset"], 20, total=40)

    postings, ev = await workday_client.fetch_jobs_with_meta(_WD_CFG, _PostHttp(handler))
    assert ev.cap_hit is False
    assert ev.page_advance_ok is True
    assert ev.declared_total == 40
    assert len(postings) == 40


async def test_workday_offset_wrap_fails_page_advance():
    """Page 2 re-serves page 1's ids (Intel offset-wrap) → page_advance_ok False."""
    def handler(url, body):
        # Ignore offset: always the SAME 20 ids.
        return _wd_page(0, 20, total=40)

    _, ev = await workday_client.fetch_jobs_with_meta(_WD_CFG, _PostHttp(handler))
    assert ev.page_advance_ok is False


async def test_workday_fetch_jobs_parity():
    def handler(url, body):
        return _wd_page(body["offset"], 20, total=40)

    postings_only = await workday_client.fetch_jobs(_WD_CFG, _PostHttp(handler))
    postings_meta, _ = await workday_client.fetch_jobs_with_meta(
        _WD_CFG, _PostHttp(handler)
    )
    assert postings_only == postings_meta


# --- Eightfold --------------------------------------------------------------

_EF_HOST = "foo.eightfold.ai"


async def test_eightfold_cap_hit_records_count_as_evidence():
    """100 full pages, count never reached → cap_hit; count captured as
    declared_total (evidence only — the gate treats Eightfold self_consistent)."""
    def handler(url, params):
        start = params["start"]
        positions = [
            {"id": start + k, "name": f"J{start+k}",
             "canonicalPositionUrl": f"https://x/{start+k}"}
            for k in range(10)
        ]
        return {"positions": positions, "count": 99999}

    positions, ev = await eightfold_client.fetch_jobs_with_meta(
        _EF_HOST, "d", _GetHttp(handler)
    )
    assert ev.cap_hit is True
    assert ev.terminated_cleanly is False
    assert ev.declared_total == 99999  # evidence only
    assert len(positions) == 1000  # 100 pages * 10


async def test_eightfold_natural_terminus_and_parity():
    def handler(url, params):
        # Partial page (< 10) on page 1 → natural terminus.
        positions = [
            {"id": k, "name": f"J{k}", "canonicalPositionUrl": f"https://x/{k}"}
            for k in range(5)
        ]
        return {"positions": positions, "count": 5}

    positions, ev = await eightfold_client.fetch_jobs_with_meta(
        _EF_HOST, "d", _GetHttp(handler)
    )
    assert ev.cap_hit is False
    assert ev.terminated_cleanly is True
    assert ev.page_advance_ok is True
    assert len(positions) == 5

    positions_only = await eightfold_client.fetch_jobs(_EF_HOST, "d", _GetHttp(handler))
    assert positions_only == positions
