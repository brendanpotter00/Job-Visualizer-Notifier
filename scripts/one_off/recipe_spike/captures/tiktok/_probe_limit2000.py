"""Throwaway: does the API honor limit=2000?"""
import httpx

URL = "https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts"
HEADERS = {"website-path": "tiktok"}
BODY = {
    "recruitment_id_list": [],
    "job_category_id_list": [],
    "subject_id_list": [],
    "location_code_list": [],
    "keyword": "",
    "limit": 2000,
    "offset": 0,
}
with httpx.Client(timeout=30.0) as client:
    r = client.post(URL, json=BODY, headers=HEADERS)
print("status:", r.status_code)
if r.status_code == 200:
    p = r.json()
    d = p.get("data") or {}
    print("code:", p.get("code"), "n:", len(d.get("job_post_list") or []), "count:", d.get("count"))
else:
    print(r.text[:150])
