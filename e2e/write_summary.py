"""Writes summary.md / summary.json for one e2e/run.sh run (PLAN.md §10).

Reads pytest's JUnit XML (API tier) and Playwright's JSON reporter output (UI
tier, if it ran) and renders PLAN.md §10's contract: one line per case,
PASS/FAIL/BLOCKED, duration, the numbers — human-first in summary.md, the
same content machine-readable in summary.json.

A case whose only outcome was pytest.skip() (via conftest.py's
require_reachable) is BLOCKED, not PASS and not FAIL — PLAN.md §6: "What
green means — and that BLOCKED is not green."
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class CaseResult:
    name: str
    tier: str  # 'API' | 'UI'
    status: str  # 'PASS' | 'FAIL' | 'BLOCKED'
    duration_s: float
    detail: str = ""


def _parse_junit(path: Path) -> list[CaseResult]:
    if not path.exists():
        return []
    tree = ET.parse(path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    out: list[CaseResult] = []
    for suite in suites:
        for case in suite.findall("testcase"):
            classname = case.get("classname", "")
            name = case.get("name", "")
            full_name = f"{classname}::{name}" if classname else name
            duration = float(case.get("time", "0") or 0)
            skipped = case.find("skipped")
            failure = case.find("failure")
            error = case.find("error")
            if skipped is not None:
                status = "BLOCKED"
                detail = (skipped.get("message") or skipped.text or "").strip()
            elif failure is not None or error is not None:
                status = "FAIL"
                node = failure if failure is not None else error
                detail = (node.get("message") or "").strip()
            else:
                status = "PASS"
                detail = ""
            out.append(CaseResult(full_name, "API", status, duration, detail))
    return out


def _walk_playwright_suites(suites: list[dict[str, Any]], prefix: str = "") -> list[CaseResult]:
    out: list[CaseResult] = []
    for suite in suites:
        title = suite.get("title", "")
        new_prefix = f"{prefix}{title} > " if title else prefix
        for spec in suite.get("specs", []):
            spec_title = f"{new_prefix}{spec.get('title', '')}"
            for test in spec.get("tests", []):
                results = test.get("results", [])
                duration_ms = sum(r.get("duration", 0) for r in results)
                status = "PASS"
                detail = ""
                outcome = test.get("status") or (results[-1].get("status") if results else "")
                if outcome == "skipped":
                    status = "BLOCKED"
                elif outcome not in ("expected", "passed"):
                    status = "FAIL"
                    for r in results:
                        if r.get("error"):
                            detail = str(r["error"].get("message", ""))[:500]
                            break
                out.append(CaseResult(spec_title, "UI", status, duration_ms / 1000.0, detail))
        out.extend(_walk_playwright_suites(suite.get("suites", []), new_prefix))
    return out


def _parse_playwright(path: Path) -> list[CaseResult]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return _walk_playwright_suites(data.get("suites", []))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--elapsed-seconds", type=int, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--blocked", default="")
    parser.add_argument("--fast", default="0")
    parser.add_argument(
        "--interrupted",
        default="0",
        help="1 when run.sh caught INT/TERM — makes the verdict ABORTED, not RED.",
    )
    args = parser.parse_args()

    artifacts_dir = Path(args.artifacts_dir)
    junit_path = artifacts_dir / "pytest-junit.xml"
    playwright_path = artifacts_dir / "ui" / "playwright-report.json"

    cases = _parse_junit(junit_path) + _parse_playwright(playwright_path)

    n_pass = sum(1 for c in cases if c.status == "PASS")
    n_fail = sum(1 for c in cases if c.status == "FAIL")
    n_blocked = sum(1 for c in cases if c.status == "BLOCKED")

    interrupted = getattr(args, "interrupted", "0") == "1"

    summary_obj = {
        "runMode": "fast" if args.fast == "1" else "full",
        "interrupted": interrupted,
        "elapsedSeconds": args.elapsed_seconds,
        "exitCode": args.exit_code,
        "blockedBoards": [b for b in args.blocked.split(",") if b],
        "counts": {"pass": n_pass, "fail": n_fail, "blocked": n_blocked, "total": len(cases)},
        "cases": [asdict(c) for c in cases],
    }
    (artifacts_dir / "summary.json").write_text(json.dumps(summary_obj, indent=2))

    lines = [
        "# e2e add-companies run summary",
        "",
        f"- Mode: **{summary_obj['runMode']}**",
        f"- Elapsed: **{args.elapsed_seconds}s**",
        f"- Result: **{n_pass} PASS / {n_fail} FAIL / {n_blocked} BLOCKED** "
        f"(of {len(cases)})",
    ]
    if summary_obj["blockedBoards"]:
        lines.append(f"- Blocked boards (preflight): {', '.join(summary_obj['blockedBoards'])}")
    lines.append("")
    lines.append("| Case | Tier | Status | Duration | Notes |")
    lines.append("|---|---|---|---|---|")
    for c in cases:
        icon = {"PASS": "PASS", "FAIL": "FAIL", "BLOCKED": "BLOCKED"}[c.status]
        note = c.detail.splitlines()[0][:140] if c.detail else ""
        lines.append(f"| {c.name} | {c.tier} | {icon} | {c.duration_s:.1f}s | {note} |")
    lines.append("")
    if interrupted:
        # An aborted run must never publish its teardown cascade as a verdict.
        # Measured in artifacts/20260827T003341Z: run.sh's cleanup trap fired
        # while pytest was still running (backend served its last 200 OK at
        # 19:35:47.0 and logged "Shutting down" 0.8s later), so every case from
        # that point on recorded `httpx.ConnectError: Connection refused` and
        # the summary read "6 PASS / 13 FAIL" — thirteen failures that were one
        # killed process. A gate that reports its own abort as product
        # regressions is the exact thing that makes people stop believing it.
        lines.append(
            "**ABORTED** — this run was interrupted (Ctrl-C, a harness timeout, or "
            "SIGTERM) before it finished. The stack was torn down underneath the "
            "still-running suite, so every case after that point failed on a dead "
            "backend, NOT on its own assertions. This is not a red gate and not a "
            "green one — it is no result. Re-run it."
        )
    elif n_fail == 0 and n_blocked == 0 and cases:
        lines.append("**GREEN** — every collected case passed.")
    elif n_fail > 0:
        lines.append("**RED** — at least one case failed. BLOCKED is not green either; see above.")
    elif not cases:
        # Previously fell into the BLOCKED branch below, which blamed a
        # third-party outage for what is actually "nothing ran at all" —
        # e.g. the stack failed to boot, so there is no junit to parse.
        lines.append(
            f"**RED** — ZERO cases were collected (run.sh exited {args.exit_code}). "
            "Nothing ran, so nothing was proved. This is almost always the stack "
            "failing to come up — read stack/backend.log and stack/frontend.log in "
            "this artifacts directory before anything else."
        )
    else:
        lines.append(
            "**BLOCKED cases present — this is NOT a clean green run**, even though nothing "
            "failed. A board was unreachable at preflight (third-party outage), not a code "
            "regression — but it means those cases did not actually run."
        )

    (artifacts_dir / "summary.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
