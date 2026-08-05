"""Throwaway: probe page-size cap and offset semantics of the search API."""
import json
import time

import httpx

URL = "https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts"
HEADERS = {"website-path": "tiktok"}


def body(limit, offset):
    return {
        "recruitment_id_list": [],
        "job_category_id_list": [],
        "subject_id_list": [],
        "location_code_list": [],
        "keyword": "",
        "limit": limit,
        "offset": offset,
    }


def attempt(label, limit, offset):
    with httpx.Client(timeout=30.0) as client:
        r = client.post(URL, json=body(limit, offset), headers=HEADERS)
    if r.status_code != 200:
        print(f"{label:<30} HTTP {r.status_code} body[:120]={r.text[:120]!r}")
        return None
    p = r.json()
    data = p.get("data") or {}
    jobs = data.get("job_post_list") or []
    ids = [j.get("id") for j in jobs]
    print(
        f"{label:<30} HTTP 200 code={p.get('code')} n={len(jobs)} count={data.get('count')} "
        f"first={ids[0] if ids else None} last={ids[-1] if ids else None}"
    )
    return ids


a = attempt("limit=100 offset=0", 100, 0)
time.sleep(1)
b = attempt("limit=500 offset=0", 500, 0)
time.sleep(1)
c = attempt("limit=1000 offset=0", 1000, 0)
time.sleep(1)
d = attempt("limit=100 offset=100", 100, 100)
time.sleep(1)
e = attempt("limit=100 offset=3750", 100, 3750)  # past-the-end page: expect ~49 and short page

if a and d:
    overlap = set(a) & set(d)
    print("overlap page0 vs page1 (limit=100):", len(overlap))
if a and b:
    print("limit=500 first 100 == limit=100 page?", b[:100] == a)
