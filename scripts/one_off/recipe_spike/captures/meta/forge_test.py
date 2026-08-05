"""THE forgeability experiment: can a plain httpx client (no browser, no cookies)
reproduce Meta's CareersJobSearchResultsV2DataQuery GraphQL POST?

Variants tested:
  A. captured lsd token, full-ish static body, NO cookies
  B. made-up lsd token ("AdSforgedforgedforge") — is lsd validated at all?
  C. minimal body: only lsd + doc_id + variables + friendly_name
  D. count query (doc_id=26210170368675892) with made-up lsd
"""
import json
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
COUNT_DOC_ID = "26210170368675892"


def attempt(label: str, lsd: str, doc_id: str, minimal: bool) -> None:
    body = {
        "lsd": lsd,
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": (
            "CareersJobSearchResultsV2DataQuery" if doc_id == SEARCH_DOC_ID
            else "CareersJobSearchHideFiltersBarV2Query"
        ),
        "variables": VARIABLES,
        "doc_id": doc_id,
    }
    if not minimal:
        body.update({"av": "0", "__user": "0", "__a": "1", "__comet_req": "31",
                     "server_timestamps": "true", "jazoest": "22374"})
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.metacareers.com",
        "Referer": "https://www.metacareers.com/jobsearch/",
        "x-fb-lsd": lsd,
        "x-fb-friendly-name": body["fb_api_req_friendly_name"],
        "x-asbd-id": "359341",
    }
    started = time.time()
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        # fresh client every attempt: guaranteed cookieless
        response = client.post(URL, data=body, headers=headers)
    elapsed = round(time.time() - started, 1)
    text = response.text
    verdict = "???"
    detail = ""
    try:
        payload = json.loads(text)
        if "data" in payload and "job_search_with_featured_jobs_v2" in (payload.get("data") or {}):
            node = payload["data"]["job_search_with_featured_jobs_v2"]
            if "all_jobs" in node:
                verdict = "SUCCESS"
                detail = f"all_jobs={len(node['all_jobs'])}"
            elif "job_count" in node:
                verdict = "SUCCESS"
                detail = f"job_count={node['job_count']}"
        elif "errors" in payload:
            verdict = "GRAPHQL_ERROR"
            detail = json.dumps(payload["errors"])[:200]
        else:
            verdict = "UNEXPECTED_JSON"
            detail = text[:200]
    except Exception:
        verdict = "NON_JSON"
        detail = text[:200]
    print(f"[{label}] status={response.status_code} verdict={verdict} {detail} "
          f"({elapsed}s, {len(text)} bytes, content-type={response.headers.get('content-type', '?')})")


if __name__ == "__main__":
    attempt("A: captured lsd, full body, no cookies", CAPTURED_LSD, SEARCH_DOC_ID, minimal=False)
    time.sleep(2)
    attempt("B: FORGED lsd, full body, no cookies  ", FORGED_LSD, SEARCH_DOC_ID, minimal=False)
    time.sleep(2)
    attempt("C: FORGED lsd, minimal body, no cookies", FORGED_LSD, SEARCH_DOC_ID, minimal=True)
    time.sleep(2)
    attempt("D: count query, FORGED lsd, minimal    ", FORGED_LSD, COUNT_DOC_ID, minimal=True)
