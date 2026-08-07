"""One-off discovery probe for janestreet (evidence only, not part of replay)."""
import collections

import httpx

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

with httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": UA}) as c:
    r = c.get("https://www.janestreet.com/jobs/main.json")
    print("main.json:", r.status_code, r.headers.get("content-type"), len(r.content), "bytes")
    data = r.json()
    print("records:", len(data), "| first id:", data[0]["id"], "| position:", data[0]["position"][:40])
    print(collections.Counter(d.get("availability") for d in data))
    ft = next(d for d in data if d.get("availability") == "Full-Time: Experienced")
    print("probe record:", ft["id"], ft["position"], ft["city"])
    slug = ft["position"].lower().replace(" ", "-").replace(",", "")
    for u in [
        f"https://www.janestreet.com/join-jane-street/position/{ft['id']}/",
        f"https://www.janestreet.com/join-jane-street/position/{ft['id']}/{slug}/",
        f"https://www.janestreet.com/join-jane-street/open-roles/position/{ft['id']}/",
    ]:
        rr = c.get(u)
        print(rr.status_code, u, "->", rr.headers.get("location", ""))
    d = c.get("https://www.janestreet.com/static/position-directories.json")
    print("position-directories.json:", d.status_code, len(d.content))
    print(str(d.text)[:600])
