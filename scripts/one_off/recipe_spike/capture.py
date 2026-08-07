"""DISCOVERY SIDE — the agent's eyes on a careers site.

Loads a page in a local headless Chromium, records every network response,
and writes a compact evidence report the agent reads to author a recipe.
This file is NEVER imported by replay.py.

Usage:
    python capture.py --target amazon --url "https://www.amazon.jobs/en/search?..."
    python capture.py --target meta --url "https://www.metacareers.com/jobsearch" --scroll 3

Outputs (under captures/<target>/):
    report.json   compact evidence summary — read this first
    raw/NNN.json  full bodies of the JSON responses worth inspecting
    page.html     final rendered HTML (for http_html candidates)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

HERE = Path(__file__).parent
CAPTURES = HERE / "captures"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Keys that suggest an object is a job posting. Scored case-insensitively.
JOB_KEY_HINTS = {
    "title": 3, "job_title": 3, "jobTitle": 3, "name": 1, "position": 2,
    "location": 2, "locations": 2, "city": 1, "office": 1, "workplace": 1,
    "id": 1, "job_id": 2, "jobId": 2, "requisition": 3, "req_id": 3,
    "url": 1, "absolute_url": 2, "apply_url": 2, "job_path": 2, "externalPath": 2,
    "department": 1, "team": 1, "category": 1,
    "posted": 2, "posted_date": 3, "postedOn": 3, "created_at": 2, "updated_at": 1,
}
MAX_RAW_BODY_BYTES = 6_000_000


def score_object(obj: dict[str, Any]) -> int:
    score = 0
    lowered = {str(k).lower() for k in obj}
    for hint, weight in JOB_KEY_HINTS.items():
        if hint.lower() in lowered:
            score += weight
    return score


def find_record_arrays(payload: Any, path: str = "", out: list | None = None, depth: int = 0):
    """Walk a payload and report every array-of-objects with a job-like shape."""
    if out is None:
        out = []
    if depth > 8:
        return out
    if isinstance(payload, list):
        objs = [item for item in payload[:5] if isinstance(item, dict)]
        if objs:
            score = max(score_object(o) for o in objs)
            if score >= 4:
                out.append({
                    "path": path,
                    "count": len(payload),
                    "job_score": score,
                    "sample_keys": sorted(objs[0].keys())[:30],
                    "sample": {k: _truncate(v) for k, v in list(objs[0].items())[:12]},
                })
        for index, item in enumerate(payload[:3]):
            find_record_arrays(item, f"{path}.{index}" if path else str(index), out, depth + 1)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            find_record_arrays(value, f"{path}.{key}" if path else str(key), out, depth + 1)
    return out


def _truncate(value: Any, limit: int = 120) -> Any:
    if isinstance(value, str):
        return value[:limit] + ("…" if len(value) > limit else "")
    if isinstance(value, (list, dict)):
        text = json.dumps(value)[:limit]
        return text + "…"
    return value


def find_counts(payload: Any, depth: int = 0) -> dict[str, int]:
    """Harvest scalar *count* fields — the completeness oracle."""
    found: dict[str, int] = {}
    if depth > 6:
        return found
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if isinstance(value, int) and ("count" in lowered or lowered in ("hits", "total", "totalcount", "numfound")):
                found[key] = value
            elif isinstance(value, (dict, list)):
                found.update(find_counts(value, depth + 1))
    elif isinstance(payload, list):
        for item in payload[:3]:
            found.update(find_counts(item, depth + 1))
    return found


async def capture(target: str, url: str, scrolls: int, wait: str, settle_ms: int) -> dict:
    out_dir = CAPTURES / target
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for stale in raw_dir.glob("*.json"):
        stale.unlink()

    responses: list[dict] = []
    pending: list[asyncio.Task] = []
    started = time.time()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            user_agent=USER_AGENT,
        )
        page = await context.new_page()

        async def record(response) -> None:
            try:
                request = response.request
                content_type = (response.headers or {}).get("content-type", "")
                entry = {
                    "method": request.method,
                    "url": response.url,
                    "status": response.status,
                    "content_type": content_type.split(";")[0],
                    "resource_type": request.resource_type,
                }
                if request.method == "POST":
                    body = request.post_data
                    if body:
                        entry["request_body"] = body[:2000]
                is_jsonish = "json" in content_type or response.url.endswith(".json")
                if is_jsonish and response.status < 400:
                    body_bytes = await response.body()
                    entry["bytes"] = len(body_bytes)
                    if len(body_bytes) <= MAX_RAW_BODY_BYTES:
                        try:
                            payload = json.loads(body_bytes.decode("utf-8", "replace"), strict=False)
                        except Exception as exc:  # noqa: BLE001 - evidence, not control flow
                            entry["parse_error"] = str(exc)[:200]
                        else:
                            arrays = find_record_arrays(payload)
                            arrays.sort(key=lambda a: (a["job_score"], a["count"]), reverse=True)
                            entry["record_arrays"] = arrays[:5]
                            entry["counts"] = find_counts(payload)
                            entry["top_level_keys"] = (
                                sorted(payload.keys())[:25] if isinstance(payload, dict) else f"<list len={len(payload)}>"
                            )
                            if arrays:
                                index = len(list(raw_dir.glob("*.json")))
                                raw_path = raw_dir / f"{index:03d}.json"
                                raw_path.write_text(json.dumps(payload, indent=1)[:4_000_000])
                                entry["raw_file"] = str(raw_path.relative_to(out_dir))
                responses.append(entry)
            except Exception as exc:  # noqa: BLE001
                responses.append({"url": getattr(response, "url", "?"), "capture_error": str(exc)[:200]})

        page.on("response", lambda r: pending.append(asyncio.create_task(record(r))))

        nav_error = None
        try:
            await page.goto(url, wait_until=wait, timeout=60_000)
        except Exception as exc:  # noqa: BLE001
            nav_error = str(exc)[:300]

        for _ in range(scrolls):
            try:
                await page.mouse.wheel(0, 4000)
                await page.wait_for_timeout(1200)
            except Exception:  # noqa: BLE001
                break

        await page.wait_for_timeout(settle_ms)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        html = await page.content()
        (out_dir / "page.html").write_text(html[:3_000_000])
        title = await page.title()
        await context.close()
        await browser.close()

    embedded = scan_embedded_json(html, out_dir)
    dom = sketch_dom_repetition(html)

    jsonish = [r for r in responses if r.get("record_arrays")]
    jsonish.sort(key=lambda r: max((a["job_score"] for a in r["record_arrays"]), default=0), reverse=True)

    report = {
        "target": target,
        "entry_url": url,
        "page_title": title,
        "nav_error": nav_error,
        "wall_seconds": round(time.time() - started, 1),
        "browser_seconds": round(time.time() - started, 1),
        "dollars": 0.0,
        "responses_total": len(responses),
        "job_like_json_responses": jsonish[:8],
        "embedded_json": embedded,
        "dom_repetition": dom,
        "all_xhr": [
            {"method": r.get("method"), "url": r.get("url", "")[:300], "status": r.get("status"), "type": r.get("content_type")}
            for r in responses
            if r.get("resource_type") in ("xhr", "fetch")
        ][:60],
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    return report


def scan_embedded_json(html: str, out_dir: Path) -> list[dict]:
    """Find JSON islands in the HTML (ld+json, __NEXT_DATA__, data-sjs, etc.)."""
    results: list[dict] = []
    patterns = [
        ("ld+json", r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>'),
        ("next-data", r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>'),
        ("application/json", r'<script[^>]+type="application/json"[^>]*>(.*?)</script>'),
    ]
    for label, pattern in patterns:
        for index, match in enumerate(re.finditer(pattern, html, re.DOTALL | re.IGNORECASE)):
            blob = match.group(1).strip()
            if len(blob) < 40:
                continue
            try:
                payload = json.loads(blob, strict=False)
            except Exception:  # noqa: BLE001
                continue
            arrays = find_record_arrays(payload)
            arrays.sort(key=lambda a: (a["job_score"], a["count"]), reverse=True)
            is_job_posting = '"JobPosting"' in blob or '"@type": "JobPosting"' in blob
            if arrays or is_job_posting:
                path = out_dir / f"embedded_{label.replace('/', '_').replace('+', '_')}_{index}.json"
                path.write_text(json.dumps(payload, indent=1)[:2_000_000])
                results.append({
                    "kind": label,
                    "is_job_posting_ld": is_job_posting,
                    "record_arrays": arrays[:3],
                    "file": path.name,
                })
            if len(results) >= 6:
                return results
    return results


def sketch_dom_repetition(html: str) -> list[dict]:
    """Cheap signal for server-rendered lists: most-repeated class attributes."""
    classes = re.findall(r'class="([^"]{3,120})"', html)
    counts: dict[str, int] = {}
    for value in classes:
        counts[value.strip()] = counts.get(value.strip(), 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [{"class": name, "occurrences": n} for name, n in ranked[:15] if n >= 3]


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture discovery evidence for one careers site")
    parser.add_argument("--target", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--scroll", type=int, default=2, help="scroll bursts after load")
    parser.add_argument("--wait", default="networkidle", choices=["load", "domcontentloaded", "networkidle", "commit"])
    parser.add_argument("--settle-ms", type=int, default=3000)
    args = parser.parse_args()

    report = asyncio.run(capture(args.target, args.url, args.scroll, args.wait, args.settle_ms))
    print(json.dumps({
        "target": report["target"],
        "page_title": report["page_title"],
        "nav_error": report["nav_error"],
        "wall_seconds": report["wall_seconds"],
        "responses_total": report["responses_total"],
        "job_like_json_responses": len(report["job_like_json_responses"]),
        "embedded_json": len(report["embedded_json"]),
        "report": str((CAPTURES / report["target"] / "report.json")),
    }, indent=2))


if __name__ == "__main__":
    main()
