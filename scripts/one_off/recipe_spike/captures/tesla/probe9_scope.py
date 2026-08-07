"""Scope test: is Akamai's 403 site-wide for httpx, or only on the careers app?

Also hunts for any plain-HTTP route to Tesla job data (sitemaps, alt hosts).
"""
import httpx

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}

URLS = [
    "https://www.tesla.com/robots.txt",
    "https://www.tesla.com/",
    "https://www.tesla.com/sitemap.xml",
    "https://www.tesla.com/careers",
    "https://www.tesla.com/careers/search/job/224501",
    "https://tesla.com/cua-api/apps/careers/state",
    "https://www.tesla.com/cua-api/apps/careers/state?lang=en_US",
]


def main() -> None:
    with httpx.Client(timeout=25, follow_redirects=False) as client:
        for url in URLS:
            try:
                r = client.get(url, headers=HEADERS)
                snippet = r.text[:120].replace("\n", " ") if "html" in (r.headers.get("content-type") or "") or r.status_code < 300 else ""
                print(f"{r.status_code:>4}  {len(r.content):>8}b  {url}")
                if r.status_code < 400 and snippet:
                    print(f"        {snippet}")
                if 300 <= r.status_code < 400:
                    print(f"        -> {r.headers.get('location')}")
            except Exception as exc:  # noqa: BLE001
                print(f" ERR  {url}: {type(exc).__name__} {str(exc)[:120]}")


if __name__ == "__main__":
    main()
