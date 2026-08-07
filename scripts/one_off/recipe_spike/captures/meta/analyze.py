import json
from pathlib import Path

base = Path(__file__).parent / "graphql"
d = json.load(open(base / "002_resp.txt"))
root = d["data"]["job_search_with_featured_jobs_v2"]
print("keys under job_search_with_featured_jobs_v2:", list(root.keys()))
jobs = root["all_jobs"]
print("all_jobs count:", len(jobs))
print("sample keys:", sorted(jobs[0].keys()))
print("top-level data keys:", list(d["data"].keys()))
for k, v in root.items():
    if isinstance(v, int):
        print("int field:", k, "=", v)
    elif isinstance(v, list) and k != "all_jobs":
        print("list field:", k, "len", len(v), "sample:", json.dumps(v[:1])[:200])
# count query body
req1 = (base / "001_req.txt").read_text()
body_start = req1.index("POST_BODY:")
print("\n001 request (count query) friendly name + doc_id:")
for part in req1[body_start:].split("&"):
    if part.startswith(("fb_api_req_friendly_name", "doc_id", "variables")):
        print("  ", part[:300])
