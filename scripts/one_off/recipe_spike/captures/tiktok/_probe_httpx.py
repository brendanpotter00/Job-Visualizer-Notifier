"""Throwaway: reproduce the search POST with plain httpx and ablate headers."""
import json

import httpx

URL = "https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts"
BODY = {
    "recruitment_id_list": [],
    "job_category_id_list": [],
    "subject_id_list": [],
    "location_code_list": [],
    "keyword": "",
    "limit": 12,
    "offset": 0,
}
print("body bytes:", len(json.dumps(BODY, separators=(",", ":"))))

FULL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Origin": "https://lifeattiktok.com",
    "Referer": "https://lifeattiktok.com/",
    "Accept": "*/*",
    "Accept-Language": "en-US",
    "website-path": "tiktok",
}


def attempt(label, headers):
    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            r = client.post(URL, json=BODY, headers=headers)
        note = ""
        if r.status_code == 200:
            try:
                p = r.json()
                jobs = (p.get("data") or {}).get("job_post_list") or []
                note = f"code={p.get('code')} n_jobs={len(jobs)} count={(p.get('data') or {}).get('count')}"
            except Exception as exc:
                note = f"json parse fail: {exc}; body[:120]={r.text[:120]!r}"
        else:
            note = f"body[:150]={r.text[:150]!r}"
        print(f"{label:<28} HTTP {r.status_code}  {note}")
    except Exception as exc:
        print(f"{label:<28} EXC {type(exc).__name__}: {exc}")


attempt("full headers", FULL_HEADERS)
for drop in ["website-path", "Origin", "Referer", "User-Agent", "Accept-Language", "Accept"]:
    trimmed = {k: v for k, v in FULL_HEADERS.items() if k != drop}
    attempt(f"minus {drop}", trimmed)
attempt("only website-path", {"website-path": "tiktok"})
attempt("no headers at all", {})
