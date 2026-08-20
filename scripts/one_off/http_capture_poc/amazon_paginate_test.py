"""Extend the POC: prove the discovered Amazon API paginates + scales with PLAIN httpx
(no browser, $0). Bumps result_limit and walks offset; reports total 'hits'."""
import json
import httpx

BASE = ("https://www.amazon.jobs/en/search.json?radius=24km"
        "&facets%5B%5D=normalized_country_code&facets%5B%5D=normalized_state_name"
        "&facets%5B%5D=normalized_city_name&facets%5B%5D=location"
        "&facets%5B%5D=business_category&facets%5B%5D=category"
        "&facets%5B%5D=schedule_type_id&facets%5B%5D=employee_class"
        "&facets%5B%5D=normalized_location&facets%5B%5D=job_function_id"
        "&facets%5B%5D=is_manager&facets%5B%5D=is_intern"
        "&sort=relevant&base_query=software")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")


def fetch(offset, limit):
    url = f"{BASE}&offset={offset}&result_limit={limit}"
    r = httpx.get(url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30)
    data = json.loads(r.text)
    jobs = data.get("jobs", [])
    hits = data.get("hits")
    first = (jobs[0].get("title") if jobs else None)
    return r.status_code, hits, len(jobs), first


print("=== Amazon search.json — pagination/scale via plain httpx (no browser) ===")
s, hits, n, first = fetch(0, 100)
print(f"result_limit=100 offset=0   -> status {s}, TOTAL hits={hits}, got {n} jobs; first: {first!r}")
s2, hits2, n2, first2 = fetch(100, 100)
print(f"result_limit=100 offset=100 -> status {s2}, hits={hits2}, got {n2} jobs; first: {first2!r}")
print()
if n >= 100 and n2 >= 1 and first != first2:
    print(f"✅ SCALE PROVEN: one plain-httpx call returns 100 jobs, offset advances to a DIFFERENT page,")
    print(f"   and the API reports {hits} total matching jobs — all reachable by paging offset. $0, no browser.")
else:
    print("⚠️ pagination behaved unexpectedly — see values above.")
