"""Forgeability round 3: rule out header-level causes before concluding
TLS/HTTP-fingerprint blocking.

  G. GET /jobs with a byte-faithful copy of Chrome's header set (HTTP/1.1, httpx)
  H. same GET via raw curl CLI (different TLS stack: LibreSSL/OpenSSL, HTTP/2)
  I. show the full error page body once, for the record
"""
import httpx

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

CHROME_HEADERS = {
    "Host": "www.metacareers.com",
    "sec-ch-ua": '"Chromium";v="120", "Not)A;Brand";v="24", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "en-US,en;q=0.9",
}

if __name__ == "__main__":
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        r = client.get("https://www.metacareers.com/jobs", headers=CHROME_HEADERS)
        print(f"[G: full Chrome headers, httpx h1] status={r.status_code} bytes={len(r.text)} "
              f"http={r.http_version} set_cookie={r.headers.get_list('set-cookie')[:2]}")
        if r.status_code == 400:
            print("--- error body (full, one time) ---")
            print(r.text)
