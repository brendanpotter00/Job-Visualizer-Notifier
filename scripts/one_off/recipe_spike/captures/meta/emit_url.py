"""Emit the exact entrypoint URL proven in forge_test5 variant M."""
import json
import urllib.parse

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

print("https://www.metacareers.com/graphql?" + urllib.parse.urlencode(PARAMS))
