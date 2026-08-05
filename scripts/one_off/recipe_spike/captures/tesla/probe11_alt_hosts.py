"""Alt-origin hunt: is the same careers state JSON served by a less-defended host?"""
import httpx

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept": "application/json,*/*", "Accept-Language": "en-US,en;q=0.9"}

URLS = [
    "https://www.tesla.cn/cua-api/apps/careers/state",
    "https://www.tesla.com/en_eu/cua-api/apps/careers/state",
    "https://www.tesla.com/cua-api/apps/careers/listings",
    "https://www.tesla.com/careers/search/sitemap.xml",
]


def main() -> None:
    with httpx.Client(timeout=25, follow_redirects=True) as client:
        for url in URLS:
            try:
                r = client.get(url, headers=HEADERS)
                ct = r.headers.get("content-type", "")
                print(f"{r.status_code:>4} {len(r.content):>9}b {ct[:30]:<30} {url}")
                if r.status_code == 200 and "json" in ct:
                    print("      snippet:", r.text[:200].replace("\n", " "))
            except Exception as exc:  # noqa: BLE001
                print(f" ERR  {url}: {type(exc).__name__} {str(exc)[:110]}")


if __name__ == "__main__":
    main()
