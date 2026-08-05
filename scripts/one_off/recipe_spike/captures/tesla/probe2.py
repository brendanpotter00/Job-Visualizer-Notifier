"""Header-matrix probe: can HTTP/1.1 httpx get past Tesla's Akamai at all?"""
import httpx

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

FULL_CHROME = {
    "User-Agent": CHROME_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

MATRIX = [
    ("full-chrome-headers", FULL_CHROME),
    ("default-httpx", {}),
    ("firefox-ua", {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0", "Accept": "*/*"}),
]

URL = "https://www.tesla.com/cua-api/apps/careers/state"


def main() -> None:
    for label, headers in MATRIX:
        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                r = client.get(URL, headers=headers)
            print(f"{label}: status={r.status_code} bytes={len(r.content)} ct={r.headers.get('content-type')}")
            if r.status_code == 200:
                print("  snippet:", r.text[:200].replace("\n", " "))
        except Exception as exc:  # noqa: BLE001
            print(f"{label}: ERROR {type(exc).__name__}: {str(exc)[:150]}")


if __name__ == "__main__":
    main()
