"""Unit tests for the custom_json recipe-replay client."""

from __future__ import annotations

import httpx
import pytest

from api.services import custom_json_client as cjc
from api.services.custom_json_client import (
    RecipeError,
    _resolve_path,
    fetch_jobs,
    transform_to_job_listings,
)



class TestResolvePath:
    def test_dotted(self):
        assert _resolve_path({"a": {"b": 5}}, "a.b") == 5

    def test_index(self):
        assert _resolve_path({"a": [{"c": 1}, {"c": 2}]}, "a[1].c") == 2

    def test_missing_returns_none(self):
        assert _resolve_path({"a": {}}, "a.b.c") is None

    def test_empty_path_returns_obj(self):
        obj = {"x": 1}
        assert _resolve_path(obj, "") is obj

    def test_out_of_range_index_none(self):
        assert _resolve_path({"a": [1]}, "a[5]") is None


RECIPE = {
    "endpoint": "https://8.8.8.8/api/jobs",
    "method": "GET",
    "list_path": "data.results",
    "base_url": "https://8.8.8.8",
    "pagination": {"type": "offset", "param": "start", "page_size": 2, "start": 0},
    "field_map": {
        "id": "id",
        "title": "title",
        "url": "absoluteUrl",
        "location": "location.name",
        "posted_on": "postedAt",
    },
}


def _job(i: int) -> dict:
    return {
        "id": f"job-{i}",
        "title": f"Engineer {i}",
        "absoluteUrl": f"https://8.8.8.8/jobs/{i}",
        "location": {"name": "Remote"},
        "postedAt": "2026-07-01T00:00:00Z",
    }


@pytest.mark.asyncio
class TestFetchAndTransform:
    async def test_offset_pagination_walks_pages(self):
        pages = {0: [_job(0), _job(1)], 2: [_job(2)], 4: []}

        def handler(request: httpx.Request) -> httpx.Response:
            start = int(request.url.params.get("start", "0"))
            return httpx.Response(200, json={"data": {"results": pages.get(start, [])}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            raw = await fetch_jobs(RECIPE, client)
        # page0 full (2) -> continue, page2 partial (1<2) -> stop.
        assert [r["id"] for r in raw] == ["job-0", "job-1", "job-2"]

        jobs = transform_to_job_listings("acme", raw, RECIPE)
        assert {j.id for j in jobs} == {"job-0", "job-1", "job-2"}
        j0 = next(j for j in jobs if j.id == "job-0")
        assert j0.title == "Engineer 0"
        assert j0.location == "Remote"
        assert j0.source_id == "custom_json_api"
        assert j0.url == "https://8.8.8.8/jobs/0"

    async def test_bad_list_path_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"nope": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(RecipeError):
                await fetch_jobs(RECIPE, client)

    async def test_missing_required_keys_raises(self):
        async with httpx.AsyncClient() as client:
            with pytest.raises(RecipeError):
                await fetch_jobs({"endpoint": "https://8.8.8.8/x"}, client)

    async def test_redirect_is_refused(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://8.8.8.8/other"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(cjc.url_guard.BlockedURLError):
                await fetch_jobs(RECIPE, client)


class TestTransform:
    def test_transform_drops_rows_without_id_title_url(self):
        # Recipe with NO base_url so a missing/relative url can't be resolved.
        recipe = {**RECIPE}
        recipe.pop("base_url")
        raw = [
            {"id": "", "title": "no id", "absoluteUrl": "https://8.8.8.8/a"},
            {"id": "x", "title": "", "absoluteUrl": "https://8.8.8.8/b"},
            {"id": "y", "title": "ok"},  # no url field at all -> dropped
            {"id": "z", "title": "good", "absoluteUrl": "https://8.8.8.8/z",
             "location": {"name": "NYC"}, "postedAt": "2026-07-01T00:00:00Z"},
        ]
        jobs = transform_to_job_listings("acme", raw, recipe)
        assert [j.id for j in jobs] == ["z"]

    def test_relative_url_resolved_against_base(self):
        recipe = {**RECIPE, "field_map": {**RECIPE["field_map"], "url": "path"}}
        raw = [{"id": "1", "title": "t", "path": "/jobs/1"}]
        jobs = transform_to_job_listings("acme", raw, recipe)
        assert jobs[0].url == "https://8.8.8.8/jobs/1"
