"""Fetch Tesla robots.txt via httpx (the one path that answered 200) and print it."""
import httpx

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

with httpx.Client(timeout=25) as client:
    r = client.get("https://www.tesla.com/robots.txt", headers={"User-Agent": UA})
print("status", r.status_code, "bytes", len(r.content))
print(r.text)
