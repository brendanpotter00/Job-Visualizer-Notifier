"""Throwaway: inspect the captured search API response shape."""
import json
from pathlib import Path

p = json.load(open(Path(__file__).parent / "raw" / "000.json"))
print("top:", list(p.keys()))
print("code:", p.get("code"), "message:", p.get("message"), "error:", p.get("error"))
d = p["data"]
print("data keys:", list(d.keys()))
print("count:", d.get("count"))
jobs = d["job_post_list"]
print("n jobs:", len(jobs))
j = jobs[0]
print("job keys:", list(j.keys()))
print(json.dumps({k: j[k] for k in ("id", "code", "title")}, indent=1))
print("city_info:", json.dumps(j.get("city_info"))[:300])
print("job_post_info:", json.dumps(j.get("job_post_info"))[:300])
print("recruit_type:", json.dumps(j.get("recruit_type"))[:200])
print("job_category:", json.dumps(j.get("job_category"))[:200])
print("job_subject:", json.dumps(j.get("job_subject"))[:200])
