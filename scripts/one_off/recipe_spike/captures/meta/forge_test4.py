"""Forgeability round 4: the POST, now with a complete Chrome XHR header set.

  J. captured lsd, no cookies, full XHR headers
  K. FORGED lsd value, no cookies, full XHR headers
  L. LSD bootstrapped from the HTML of a fresh GET (fully self-contained flow)
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
FORGED_LSD = "AdSforgedforgedforge"
SEARCH_DOC_ID = "27129360303422352"

XHR_HEADERS = {
    "sec-ch-ua": '"Chromium";v="120", "Not)A;Brand";v="24", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "en-US",
    "Accept-Encoding": "gzip, deflate",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://www.metacareers.com",
    "Referer": "https://www.metacareers.com/jobsearch/",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "x-asbd-id": "359341",
}

GET_HEADERS = {
    "sec-ch-ua": '"Chromium";v="120", "Not)A;Brand";v="24", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "en-US,en;q=0.9",
}


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
    headers = {**XHR_HEADERS, "x-fb-lsd": lsd,
               "x-fb-friendly-name": "CareersJobSearchResultsV2DataQuery"}
    started = time.time()
    response = client.post(URL, data=body, headers=headers)
    elapsed = round(time.time() - started, 1)
    text = response.text
    try:
        payload = json.loads(text)
        node = (payload.get("data") or {}).get("job_search_with_featured_jobs_v2") or {}
        if "all_jobs" in node:
            print(f"[{label}] status={response.status_code} SUCCESS all_jobs={len(node['all_jobs'])} "
                  f"({elapsed}s, {len(text)} bytes)")
            return
        print(f"[{label}] status={response.status_code} UNEXPECTED_JSON {text[:250]} ({elapsed}s)")
    except Exception:
        print(f"[{label}] status={response.status_code} NON_JSON {text[:120]!r} ({elapsed}s, {len(text)} bytes)")


if __name__ == "__main__":
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        post_search(client, CAPTURED_LSD, "J: captured lsd, full XHR headers, no cookies")
    time.sleep(2)
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        post_search(client, FORGED_LSD, "K: FORGED lsd, full XHR headers, no cookies  ")
    time.sleep(2)
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        landing = client.get("https://www.metacareers.com/jobs", headers=GET_HEADERS)
        html = landing.text
        tokens = re.findall(r'\["LSD",\[\],\{"token":"([^"]+)"\}', html)
        print(f"[L-boot] GET /jobs status={landing.status_code} bytes={len(html)} "
              f"lsd_tokens={tokens[:2]} cookies={sorted(client.cookies.keys())}")
        if tokens:
            time.sleep(1)
            post_search(client, tokens[0], "L: bootstrapped lsd from fresh GET       ")
