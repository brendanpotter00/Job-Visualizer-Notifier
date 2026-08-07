"""One-off discovery probe for the Tesla target. Not part of the replay path."""
import json
import sys

import httpx

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

URLS = [
    "https://www.tesla.com/careers/search/",
    "https://www.tesla.com/cua-api/apps/careers/state",
]


def main() -> None:
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for url in URLS:
            try:
                r = client.get(url, headers=HEADERS)
            except Exception as exc:  # noqa: BLE001
                print(f"{url}\n  ERROR {type(exc).__name__}: {str(exc)[:200]}\n")
                continue
            body = r.text
            print(url)
            print(
                f"  status: {r.status_code} | content-type: {r.headers.get('content-type')}"
                f" | bytes: {len(body)}"
            )
            print("  snippet:", body[:250].replace("\n", " "))
            print()


if __name__ == "__main__":
    main()
