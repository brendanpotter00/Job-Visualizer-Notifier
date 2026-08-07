"""Verify job detail URL format and id uniqueness (one polite GET)."""
import json
from pathlib import Path

import httpx

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "sec-ch-ua": '"Chromium";v="120", "Not)A;Brand";v="24", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Accept-Language": "en-US,en;q=0.9",
}

base = Path(__file__).parent / "graphql"
payload = json.load(open(base / "002_resp.txt"))
jobs = payload["data"]["job_search_with_featured_jobs_v2"]["all_jobs"]
ids = [j["id"] for j in jobs]
print(f"jobs={len(ids)} unique_ids={len(set(ids))}")

probe = f"https://www.metacareers.com/jobs/{ids[0]}"
with httpx.Client(timeout=30.0, follow_redirects=False) as client:
    r = client.get(probe, headers=HEADERS)
    print(f"GET {probe} -> {r.status_code} "
          f"location={r.headers.get('location', '-')} bytes={len(r.text)}")
    title_jobs_probe = jobs[0]["title"]
    if r.status_code == 200 and title_jobs_probe.split(",")[0] in r.text:
        print(f"page contains job title fragment {title_jobs_probe.split(',')[0]!r}: True")
