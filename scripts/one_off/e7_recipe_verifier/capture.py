#!/usr/bin/env python
"""Local Playwright network capture — the discovery agent's browser tool.

usage:
    capture.py <board_url> [--wait 8] [--scroll] [--click TEXT] [--out DIR]

Loads the page in headless Chromium, records EVERY request/response, and writes:
    <out>/requests.json   compact list: method, url, resource_type, status, ctype, bytes, post_data
    <out>/bodies/NNN.json full response body for every JSON/text response under 6 MB
    <out>/document.html   the navigation document
Then prints a ranked shortlist of JSON responses that look like a job list
(scored on record-array size + job-ish keys), so you rarely need to open the dump.

Costs nothing but local CPU. This is DISCOVERY-time only — nothing here ever runs
at replay.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

JOBISH = re.compile(
    r"(?i)\b(job|jobs|position|posting|requisition|req|opening|role|vacanc|career)",
)
RECORD_KEYS = {
    "title", "jobtitle", "name", "position", "postingtitle", "jobpostingtitle",
    "displayname", "text", "job_title",
}


def score_payload(obj):
    """(best_array_len, path) for the biggest job-ish array in this payload."""
    best = (0, "")

    def walk(node, path, depth):
        nonlocal best
        if depth > 8:
            return
        if isinstance(node, list):
            if node and isinstance(node[0], dict):
                keys = {k.lower() for k in node[0]}
                if keys & RECORD_KEYS and len(node) > best[0]:
                    best = (len(node), path)
            for i, v in enumerate(node[:3]):
                walk(v, f"{path}.{i}" if path else str(i), depth + 1)
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k, depth + 1)

    walk(obj, "", 0)
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--wait", type=float, default=8.0)
    ap.add_argument("--scroll", action="store_true")
    ap.add_argument("--click", default=None, help="click the first element with this text, then wait again")
    ap.add_argument("--out", default="/tmp/e7poc/capture_out")
    args = ap.parse_args()

    os.makedirs(f"{args.out}/bodies", exist_ok=True)
    from playwright.sync_api import sync_playwright

    entries: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()

        def on_response(resp):
            try:
                req = resp.request
                ctype = (resp.headers or {}).get("content-type", "")
                entry = {
                    "n": len(entries),
                    "method": req.method,
                    "url": resp.url,
                    "resource_type": req.resource_type,
                    "status": resp.status,
                    "content_type": ctype.split(";")[0],
                    "post_data": (req.post_data or "")[:4000] or None,
                    "req_headers": {k: v for k, v in (req.headers or {}).items()
                                    if k.lower() in ("content-type", "accept", "origin",
                                                     "referer", "x-requested-with",
                                                     "authorization", "apikey", "x-api-key")},
                    "resp_headers": {k: v for k, v in (resp.headers or {}).items()
                                     if k.lower() in ("x-total-count", "content-range",
                                                      "x-total", "total")},
                    "body_file": None,
                    "records": 0,
                    "records_path": "",
                }
                if req.resource_type in ("xhr", "fetch", "document") or "json" in ctype:
                    body = resp.body()
                    if len(body) < 6_000_000:
                        path = f"{args.out}/bodies/{entry['n']:03d}.txt"
                        with open(path, "wb") as fh:
                            fh.write(body)
                        entry["body_file"] = path
                        entry["bytes"] = len(body)
                        if "json" in ctype or body[:1] in (b"{", b"["):
                            try:
                                n, where = score_payload(json.loads(body))
                                entry["records"], entry["records_path"] = n, where
                            except Exception:
                                pass
                entries.append(entry)
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(args.url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(int(args.wait * 1000))
        if args.scroll:
            for _ in range(4):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1500)
        if args.click:
            try:
                page.get_by_text(args.click, exact=False).first.click(timeout=8000)
                page.wait_for_timeout(int(args.wait * 1000))
            except Exception as exc:
                print(f"[click failed: {exc}]", file=sys.stderr)
        with open(f"{args.out}/document.html", "w") as fh:
            fh.write(page.content())
        browser.close()

    with open(f"{args.out}/requests.json", "w") as fh:
        json.dump(entries, fh, indent=1)

    ranked = sorted(
        (e for e in entries if e.get("records")),
        key=lambda e: -e["records"],
    )[:12]
    print(f"captured {len(entries)} responses -> {args.out}/requests.json")
    print(f"document -> {args.out}/document.html")
    print("\nTOP JSON RESPONSES BY JOB-ARRAY SIZE:")
    for e in ranked:
        print(f"  [{e['n']:03d}] {e['records']:5d} recs at {e['records_path']!r:40s} "
              f"{e['method']} {e['url'][:110]}")
        if e["post_data"]:
            print(f"        POST body: {e['post_data'][:300]}")
    if not ranked:
        print("  (none — the board may embed jobs in the document, or need --scroll/--click)")
        for e in entries:
            if e["resource_type"] in ("xhr", "fetch") and e["status"] < 400:
                print(f"  xhr [{e['n']:03d}] {e['method']} {e['url'][:130]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
