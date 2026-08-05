"""Forgeability round 2: cookies and bootstrap.

  E. captured datr cookie + captured lsd  -> does the cookie unlock it?
  F. pure-httpx bootstrap: GET /jobs, harvest set-cookie datr + LSD token from
     the HTML, then POST. Fully browserless two-step flow.
"""
import json
import re
import time

import httpx

URL = "https://www.metacareers.com/graphql"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

VARIABLES = json.dumps({
    "search_input": {
        "q": None, "divisions": [], "offices": [], "roles": [],
        "leadership_levels": [], "saved_jobs": [], "saved_searches": [],
        "sub_teams": [], "teams": [], "is_leadership": False,
        "is_remote_only": False, "sort_by_new": False, "results_per_page": None,
    },
    "viewasUserID": None,
    "isLoggedIn": False,
})

CAPTURED_LSD = "AdS-LBTOfReSRJgbRvl3xAokiMk"
CAPTURED_DATR = "6sVyalxWywY2U-Nboy-fXsd9"
SEARCH_DOC_ID = "27129360303422352"


def post_search(client: httpx.Client, lsd: str, label: str) -> None:
    body = {
        "av": "0", "__user": "0", "__a": "1", "__comet_req": "31",
        "lsd": lsd,
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": "CareersJobSearchResultsV2DataQuery",
        "variables": VARIABLES,
        "server_timestamps": "true",
        "doc_id": SEARCH_DOC_ID,
    }
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.metacareers.com",
        "Referer": "https://www.metacareers.com/jobsearch/",
        "x-fb-lsd": lsd,
        "x-fb-friendly-name": "CareersJobSearchResultsV2DataQuery",
        "x-asbd-id": "359341",
    }
    started = time.time()
    response = client.post(URL, data=body, headers=headers)
    elapsed = round(time.time() - started, 1)
    text = response.text
    try:
        payload = json.loads(text)
        node = (payload.get("data") or {}).get("job_search_with_featured_jobs_v2") or {}
        if "all_jobs" in node:
            print(f"[{label}] status={response.status_code} SUCCESS all_jobs={len(node['all_jobs'])} ({elapsed}s, {len(text)} bytes)")
            return
        print(f"[{label}] status={response.status_code} UNEXPECTED_JSON {text[:200]} ({elapsed}s)")
    except Exception:
        print(f"[{label}] status={response.status_code} NON_JSON {text[:150]!r} ({elapsed}s, {len(text)} bytes)")


if __name__ == "__main__":
    # E: captured datr + captured lsd
    with httpx.Client(timeout=30.0, follow_redirects=False,
                      cookies={"datr": CAPTURED_DATR}) as client:
        post_search(client, CAPTURED_LSD, "E: captured datr cookie + captured lsd")

    time.sleep(2)

    # F: pure-httpx bootstrap. GET the jobs page, harvest datr + fresh LSD.
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        get_headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        landing = client.get("https://www.metacareers.com/jobs", headers=get_headers)
        html = landing.text
        print(f"[F-boot] GET /jobs status={landing.status_code} bytes={len(html)} "
              f"cookies_now={sorted(client.cookies.keys())}")
        lsd_matches = re.findall(r'\["LSD",\[\],\{"token":"([^"]+)"\}', html)
        alt = re.findall(r'"lsd":"([^"]{8,40})"', html)
        print(f"[F-boot] LSD via sjs-array={lsd_matches[:2]} via-json-key={alt[:2]}")
        fresh_lsd = (lsd_matches or alt or [None])[0]
        if fresh_lsd:
            time.sleep(1)
            post_search(client, fresh_lsd, "F: httpx-bootstrapped datr + fresh lsd")
        else:
            print("[F] no LSD token found in HTML — dumping marker probes")
            for marker in ("LSD", "lsd", "datr"):
                idx = html.find(marker)
                print(f"  marker {marker!r} first at {idx}: {html[max(0,idx-40):idx+80]!r}" if idx >= 0 else f"  marker {marker!r} absent")
