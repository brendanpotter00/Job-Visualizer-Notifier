"""Forgeability round 5: can replay.py's own _request express this POST?

  M. POST with ALL params in the URL query string, body={} (what run_http_json
     would send for an entry with no body) — does Meta read query params on POST?
  N. POST with params as a JSON body (replay's native body encoding).

Both run through replay._request verbatim, so a pass here is a pass for the
real executor.
"""
import json
import sys
import time
import urllib.parse
from pathlib import Path

SPIKE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SPIKE))

import httpx  # noqa: E402
from replay import _request, _parse_json  # noqa: E402

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

PARAMS = {
    "av": "0", "__user": "0", "__a": "1", "__comet_req": "31",
    "lsd": "AdSrecipereplay000",
    "fb_api_caller_class": "RelayModern",
    "fb_api_req_friendly_name": "CareersJobSearchResultsV2DataQuery",
    "variables": VARIABLES,
    "server_timestamps": "true",
    "doc_id": "27129360303422352",
}

HEADERS = {
    "sec-ch-ua": '"Chromium";v="120", "Not)A;Brand";v="24", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Accept": "*/*",
    "Accept-Language": "en-US",
    "Origin": "https://www.metacareers.com",
    "Referer": "https://www.metacareers.com/jobsearch/",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "x-asbd-id": "359341",
    "x-fb-lsd": "AdSrecipereplay000",
    "x-fb-friendly-name": "CareersJobSearchResultsV2DataQuery",
}


def check(label: str, entry: dict) -> None:
    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            started = time.time()
            response = _request(client, entry, None)
            payload = _parse_json(response)
        node = (payload.get("data") or {}).get("job_search_with_featured_jobs_v2") or {}
        if "all_jobs" in node:
            print(f"[{label}] SUCCESS all_jobs={len(node['all_jobs'])} "
                  f"({round(time.time()-started,1)}s)")
        else:
            print(f"[{label}] UNEXPECTED_JSON {json.dumps(payload)[:250]}")
    except Exception as exc:  # noqa: BLE001
        print(f"[{label}] RAISED {type(exc).__name__}: {str(exc)[:200]}")


if __name__ == "__main__":
    url_with_params = (
        "https://www.metacareers.com/graphql?" + urllib.parse.urlencode(PARAMS)
    )
    check("M: replay._request, params in query string, empty body",
          {"method": "POST", "url": url_with_params, "headers": HEADERS})
    time.sleep(2)
    check("N: replay._request, params as JSON body               ",
          {"method": "POST", "url": "https://www.metacareers.com/graphql",
           "headers": HEADERS, "body": PARAMS})
