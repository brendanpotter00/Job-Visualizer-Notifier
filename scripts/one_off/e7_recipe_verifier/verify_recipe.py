#!/usr/bin/env python
"""Six-criteria verifier for a candidate replay recipe (E7 PoC harness).

NOT production code. Lives outside the repo on purpose. It imports the REAL
`recipe_schema.validate_recipe`, the REAL `recipe_runner.run_recipe`, and the REAL
`capture.discover._prove_job_link` so a PASS here means the same thing it would mean
on the nightly worker.

usage:
    verify_recipe.py <recipe.json> [--label NAME] [--quick] [--json-out PATH]

  --quick   skip the second stability sweep (agents use this while iterating)

Criteria:
  1 schema      validate_recipe(script) does not raise
  2 replay      run_recipe(script, plain httpx) returns rows, does not raise
  3 plausible   row count vs the board's declared total (oracle) / stated total
  4 links       discover._prove_job_link on two real job URLs
  5 stable_ids  two independent sweeps, symmetric difference of id sets == 0
  6 oracle      the oracle is honest: declared_probed/facet_sum/header/sitemap must
                actually resolve to a number that matches the sweep; self_consistent
                requires terminated_cleanly and no cap; `none` is honest but scored.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

REPO = os.environ.get("JVN_REPO", os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, REPO)
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/jobscraper_pr243")

import httpx  # noqa: E402

from src.backend.api.services.recipe_schema import (  # noqa: E402
    RecipeError,
    validate_recipe,
)
from src.backend.api.services.recipe_runner import (  # noqa: E402
    USER_AGENT,
    RecipeExecutionError,
    parse_plan,
    run_recipe,
)
from src.backend.api.services.capture.discover import (  # noqa: E402
    _default_probe,
    _prove_job_link,
)

STABILITY_CLAMP_PAGES = 4  # both stability sweeps use the same clamp; disclosed in output


def lenient_probe(url: str) -> tuple[int, str]:
    """The SAME shape as `_default_probe` but through a PLAIN client that follows
    cross-host redirects. Its only job is to split "the recipe's link is wrong" from
    "our SSRF-guarded prover cannot reach a link that is right" (SpaceX 301)."""
    try:
        with httpx.Client(follow_redirects=True, timeout=10.0,
                          headers={"user-agent": USER_AGENT}) as h:
            resp = h.get(url)
            return resp.status_code, resp.text[:4_000_000]
    except Exception:  # noqa: BLE001
        return 0, ""


def client() -> httpx.Client:
    """A PLAIN httpx client — no SSRF guard, no browser. The zero-cost replay tier."""
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"user-agent": USER_AGENT},
    )


def sweep(script: dict) -> tuple[list[dict], object, float]:
    started = time.monotonic()
    with client() as http:
        rows, evidence = run_recipe(script, http)
    return rows, evidence, time.monotonic() - started


def clamp(script: dict, pages: int) -> dict:
    out = json.loads(json.dumps(script))
    for step in out["steps"]:
        if step["op"] in ("paginate_page", "paginate_offset"):
            step["max_pages"] = min(step["max_pages"], pages)
        elif step["op"] == "paginate_facet":
            step["max_pages_per_facet"] = min(step["max_pages_per_facet"], 1)
            if isinstance(step.get("facet_values"), list):
                step["facet_values"] = step["facet_values"][:3]
    out["expected_min_jobs"] = 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe")
    ap.add_argument("--label", default=None)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--declared", type=int, default=None,
                    help="externally known board total, for the plausibility check")
    args = ap.parse_args()

    blob = json.load(open(args.recipe))
    # accept either a bare script or a wrapper {"script": ..., "board_url":..., "declared_total":...}
    script = blob.get("script", blob) if isinstance(blob, dict) else blob
    label = args.label or blob.get("label") or os.path.basename(args.recipe)
    declared_external = args.declared or (blob.get("declared_total") if isinstance(blob, dict) else None)

    r: dict = {
        "label": label,
        "board_url": blob.get("board_url") if isinstance(blob, dict) else None,
        "criteria": {},
        "rows": None,
        "declared_total": None,
        "declared_external": declared_external,
        "transport": script.get("transport") if isinstance(script, dict) else None,
        "oracle_kind": None,
        "elapsed_s": None,
        "notes": [],
    }

    def fail(name: str, why: str) -> None:
        r["criteria"][name] = {"pass": False, "why": why}

    def ok(name: str, why: str = "") -> None:
        r["criteria"][name] = {"pass": True, "why": why}

    # ---- 1 schema -------------------------------------------------------
    try:
        validate_recipe(script)
        ok("schema")
    except RecipeError as exc:
        fail("schema", str(exc))
        for c in ("replay", "plausible", "links", "stable_ids", "oracle"):
            fail(c, "not reached (schema failed)")
        emit(r, args)
        return 1
    except Exception as exc:  # noqa: BLE001
        fail("schema", f"{type(exc).__name__}: {exc}")
        for c in ("replay", "plausible", "links", "stable_ids", "oracle"):
            fail(c, "not reached")
        emit(r, args)
        return 1

    plan = parse_plan(script)
    r["oracle_kind"] = plan.oracle.get("kind")

    # ---- 2 replay -------------------------------------------------------
    try:
        rows, evidence, elapsed = sweep(script)
        ok("replay", f"{len(rows)} rows in {elapsed:.0f}s, {evidence.pages_fetched} pages")
        r["rows"] = len(rows)
        r["elapsed_s"] = round(elapsed, 1)
        r["declared_total"] = evidence.declared_total
        r["cap_hit"] = evidence.cap_hit
        r["terminated_cleanly"] = evidence.terminated_cleanly
        r["page_advance_ok"] = evidence.page_advance_ok
        r["pages_fetched"] = evidence.pages_fetched
    except (RecipeExecutionError, RecipeError) as exc:
        fail("replay", str(exc)[:400])
        for c in ("plausible", "links", "stable_ids", "oracle"):
            fail(c, "not reached (replay failed)")
        emit(r, args)
        return 1
    except Exception as exc:  # noqa: BLE001
        fail("replay", f"{type(exc).__name__}: {str(exc)[:300]}")
        for c in ("plausible", "links", "stable_ids", "oracle"):
            fail(c, "not reached (replay raised)")
        r["traceback"] = traceback.format_exc()[-1500:]
        emit(r, args)
        return 1

    # ---- 3 plausible ----------------------------------------------------
    truth = declared_external if declared_external is not None else evidence.declared_total
    if truth is None:
        # No oracle anywhere. Plausibility can only be asserted as "clean termination
        # of a real sweep" — which is exactly the weak claim `self_consistent` makes.
        if evidence.terminated_cleanly and not evidence.cap_hit and len(rows) >= 1:
            ok("plausible", f"no declared total anywhere; {len(rows)} rows, clean terminus")
            r["notes"].append("plausibility UNORACLED — no board-published total to check against")
        else:
            fail("plausible", "no declared total and the sweep did not terminate cleanly")
    else:
        ratio = len(rows) / truth if truth else 0.0
        r["coverage_ratio"] = round(ratio, 4)
        if 0.90 <= ratio <= 1.10:
            ok("plausible", f"{len(rows)} rows vs declared {truth} ({ratio:.0%})")
        else:
            fail("plausible", f"{len(rows)} rows vs declared {truth} ({ratio:.1%})")

    # ---- 4 links --------------------------------------------------------
    # Run the SAME prover twice with two probes, so a failure can be attributed:
    #   strict  = production `_default_probe` (SSRF-guarded, no cross-host redirect)
    #   lenient = plain httpx, follows redirects
    # strict FAIL + lenient PASS  => our verifier is too strict, the recipe is fine.
    field_map = {"url": "url", "title": "title", "id": "id"}
    try:
        proof = _prove_job_link(rows, field_map, "", _default_probe)
        if proof.proved:
            ok("links")
        else:
            fail("links", ("BLOCKED: " if proof.blocked else "") + proof.why)
    except Exception as exc:  # noqa: BLE001
        fail("links", f"prover raised {type(exc).__name__}: {exc}")
    try:
        lenient = _prove_job_link(rows, field_map, "", lenient_probe)
        r["links_lenient"] = {"pass": lenient.proved, "why": lenient.why or None}
    except Exception as exc:  # noqa: BLE001
        r["links_lenient"] = {"pass": False, "why": f"{type(exc).__name__}: {exc}"}

    # ---- 5 stable_ids ---------------------------------------------------
    if args.quick:
        r["criteria"]["stable_ids"] = {"pass": None, "why": "skipped (--quick)"}
    else:
        try:
            paginated = plan.pagination is not None
            if elapsed > 90 and paginated:
                s = clamp(script, STABILITY_CLAMP_PAGES)
                r["notes"].append(
                    f"stability sweeps clamped to {STABILITY_CLAMP_PAGES} pages "
                    f"(full sweep took {elapsed:.0f}s)"
                )
                a_rows, _, _ = sweep(s)
                time.sleep(3)
                b_rows, _, _ = sweep(s)
            else:
                a_rows = rows
                time.sleep(3)
                b_rows, _, _ = sweep(script)
            a = {x["id"] for x in a_rows}
            b = {x["id"] for x in b_rows}
            sym = len(a ^ b)
            r["stability"] = {"a": len(a), "b": len(b), "symmetric_difference": sym}
            if sym == 0:
                ok("stable_ids", f"{len(a)} == {len(b)}, symdiff 0")
            else:
                fail("stable_ids", f"symdiff {sym} ({len(a)} vs {len(b)} ids)")
        except Exception as exc:  # noqa: BLE001
            fail("stable_ids", f"second sweep raised {type(exc).__name__}: {str(exc)[:200]}")

    # ---- 6 oracle honesty ----------------------------------------------
    kind = plan.oracle.get("kind")
    if kind in ("declared_probed", "facet_sum", "header", "sitemap"):
        if evidence.declared_total is None:
            fail("oracle", f"oracle kind {kind!r} resolved to no number at replay")
        else:
            ratio = len(rows) / evidence.declared_total if evidence.declared_total else 0
            if 0.90 <= ratio <= 1.10:
                ok("oracle", f"{kind} = {evidence.declared_total}, sweep {len(rows)} ({ratio:.0%})")
            else:
                fail("oracle", f"{kind} = {evidence.declared_total} but sweep got {len(rows)} ({ratio:.1%})")
    elif kind == "self_consistent":
        if evidence.terminated_cleanly and not evidence.cap_hit:
            ok("oracle", "self_consistent: clean terminus, no cap")
        else:
            fail("oracle", f"self_consistent claimed but cap_hit={evidence.cap_hit} "
                           f"terminated_cleanly={evidence.terminated_cleanly}")
    elif kind == "none":
        # Honest, but it means this board can NEVER close a job. Scored as an honest
        # declaration (criterion 6 says "carry an honest oracle, or honestly declare
        # it has none") — recorded separately as `oracle_is_none`.
        ok("oracle", "declares none — honest, but the board can never close a job")
        r["notes"].append("ORACLE=none: replay shows jobs forever and closes nothing")
    else:
        fail("oracle", f"unknown oracle kind {kind!r}")

    r["oracle_is_none"] = kind == "none"
    passed = [k for k, v in r["criteria"].items() if v.get("pass") is True]
    r["all_pass"] = all(v.get("pass") is True for v in r["criteria"].values())
    r["passed_count"] = len(passed)
    emit(r, args)
    return 0 if r["all_pass"] else 1


def emit(r: dict, args) -> None:
    r["all_pass"] = all(v.get("pass") is True for v in r["criteria"].values())
    print(json.dumps(r, indent=2, default=str))
    if args.json_out:
        json.dump(r, open(args.json_out, "w"), indent=2, default=str)


if __name__ == "__main__":
    sys.exit(main())
