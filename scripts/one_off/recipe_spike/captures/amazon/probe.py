"""Discovery probe for amazon.jobs search.json — plain httpx, no browser.

Run steps individually to stay polite:
  python probe.py page1        # offset=0, result_limit=10
  python probe.py page2        # offset=10, result_limit=10
  python probe.py all76        # offset=0, result_limit=100 (whole filtered set)
  python probe.py cap          # broad query, result_limit=500 -> observe server cap
  python probe.py replaysim    # exact merge semantics replay.py will use
"""
from __future__ import annotations

import json
import sys

import httpx

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

BASE = "https://www.amazon.jobs/en/search.json"
COMMON = {
    "base_query": "software engineer",
    "loc_query": "Austin, TX, United States",
    "latitude": "30.26759",
    "longitude": "-97.74299",
    "radius": "24km",
    "distanceType": "Mi",
    "city": "Austin",
    "region": "Texas",
    "county": "Travis",
    "country": "USA",
    "sort": "recent",
}


def get(params: dict, url: str = BASE) -> dict:
    with httpx.Client(timeout=30, follow_redirects=False) as c:
        r = c.get(url, params=params, headers={"User-Agent": UA})
        print("status:", r.status_code, "ctype:", r.headers.get("content-type"))
        if r.status_code >= 300:
            print("location:", r.headers.get("location"))
            print("body[:300]:", r.text[:300])
            sys.exit(1)
        return json.loads(r.text, strict=False)


def main() -> None:
    step = sys.argv[1] if len(sys.argv) > 1 else "page1"

    if step == "page1":
        d = get({**COMMON, "offset": 0, "result_limit": 10})
        print("keys:", sorted(d.keys()), "error:", d.get("error"))
        print("hits:", d.get("hits"), "n_jobs:", len(d.get("jobs", [])))
        j = d["jobs"][0]
        for k in ("id", "id_icims", "title", "job_path", "posted_date",
                  "normalized_location", "company_name", "job_category", "team",
                  "updated_time", "url_next_step"):
            print(f"  {k}: {j.get(k)!r}"[:160])
    elif step == "page2":
        d1 = get({**COMMON, "offset": 0, "result_limit": 10})
        d2 = get({**COMMON, "offset": 10, "result_limit": 10})
        ids1 = [x["id"] for x in d1["jobs"]]
        ids2 = [x["id"] for x in d2["jobs"]]
        print("p1 n:", len(ids1), "p2 n:", len(ids2), "hits:", d2.get("hits"),
              "overlap:", len(set(ids1) & set(ids2)))
    elif step == "all76":
        d = get({**COMMON, "offset": 0, "result_limit": 100})
        jobs = d.get("jobs", [])
        print("hits:", d.get("hits"), "n_jobs:", len(jobs),
              "unique ids:", len({x["id"] for x in jobs}))
    elif step == "cap":
        d = get({"base_query": "software engineer", "sort": "recent",
                 "offset": 0, "result_limit": 500})
        jobs = d.get("jobs")
        print("asked 500 -> hits:", d.get("hits"), "error:", d.get("error"),
              "jobs type:", type(jobs).__name__,
              "returned:", len(jobs) if isinstance(jobs, list) else None)
    elif step == "cap100":
        d = get({"base_query": "software engineer", "sort": "recent",
                 "offset": 0, "result_limit": 100})
        jobs = d.get("jobs")
        print("asked 100 -> hits:", d.get("hits"), "error:", d.get("error"),
              "returned:", len(jobs) if isinstance(jobs, list) else None)
    elif step == "replaysim":
        # exactly what replay.py does: entrypoint URL already has result_limit &
        # offset=0 baked in; pagination passes params={"offset": cursor} which
        # httpx merges over the URL's own query. Prove the merge overrides.
        url = (
            "https://www.amazon.jobs/en/search.json?offset=0&result_limit=10"
            "&sort=recent&base_query=software%20engineer&loc_query=Austin%2C%20TX%2C%20United%20States"
            "&latitude=30.26759&longitude=-97.74299&radius=24km&distanceType=Mi"
            "&city=Austin&region=Texas&county=Travis&country=USA"
        )
        d1 = get({"offset": 0}, url=url)
        d2 = get({"offset": 10}, url=url)
        print("echo request:", str(d2.get("job_posting_search_request"))[:200])
        ids1 = [x["id"] for x in d1["jobs"]]
        ids2 = [x["id"] for x in d2["jobs"]]
        print("p1 n:", len(ids1), "p2 n:", len(ids2), "hits:", d2.get("hits"),
              "overlap:", len(set(ids1) & set(ids2)))
    elif step == "nullcheck":
        d = get({**COMMON, "offset": 0, "result_limit": 100})
        jobs = d["jobs"]
        for key in ("id", "id_icims", "title", "job_path", "posted_date",
                    "normalized_location", "job_category"):
            nulls = sum(1 for x in jobs if not x.get(key))
            print(f"  {key}: {nulls}/{len(jobs)} null-or-empty")
        print("sample posted_date values:", sorted({x['posted_date'] for x in jobs})[:5])
    elif step == "post":
        # replay.py POST path: client.post(url, json=body) with pagination param
        # merged into the body. Does Rails-side search.json accept a JSON body?
        with httpx.Client(timeout=30, follow_redirects=False) as c:
            r = c.post(BASE, json={**COMMON, "offset": 0, "result_limit": 10},
                       headers={"User-Agent": UA})
            print("POST status:", r.status_code, "ctype:", r.headers.get("content-type"))
            print("body[:300]:", r.text[:300])
            if r.status_code < 300:
                d = json.loads(r.text, strict=False)
                jobs = d.get("jobs")
                print("hits:", d.get("hits"), "error:", d.get("error"),
                      "n_jobs:", len(jobs) if isinstance(jobs, list) else None)
    else:
        raise SystemExit(f"unknown step {step}")


if __name__ == "__main__":
    main()
