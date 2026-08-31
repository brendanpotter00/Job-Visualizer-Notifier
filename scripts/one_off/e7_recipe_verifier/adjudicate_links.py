#!/usr/bin/env python
"""Adjudicate a `links` failure: is the RECIPE wrong, or is our PROVER too strict?

`discover._prove_job_link` sees only server-delivered bytes. A client-rendered job page
is byte-identical to a client-rendered 404 shell over plain HTTP, so a correct template
can be rejected. This renders the same two URLs in real Chromium and asks the same
question of the RENDERED DOM.

usage: adjudicate_links.py <verifier_result.json | recipe.json> [--urls U1 T1 U2 T2]

Verdicts:
  RECIPE_WRONG        rendered pages are identical / neither carries its own title
  VERIFIER_TOO_STRICT rendered pages differ and each carries its own title
  UNDECIDED           rendering failed or was ambiguous
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata

REPO = os.environ.get("JVN_REPO", os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, REPO)
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/jobscraper_pr243")

MULTISPACE = re.compile(r"\s+")


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return MULTISPACE.sub(" ", text).strip().casefold()


def sample_urls(recipe_path: str) -> list[tuple[str, str]]:
    """Replay the recipe and take the first two distinct (url, title)."""
    import httpx
    from src.backend.api.services.recipe_runner import USER_AGENT, run_recipe

    blob = json.load(open(recipe_path))
    script = blob.get("script", blob)
    with httpx.Client(follow_redirects=True, timeout=30.0,
                      headers={"user-agent": USER_AGENT}) as h:
        rows, _ = run_recipe(script, h)
    out, seen = [], set()
    for r in rows:
        u, t = r.get("url"), r.get("title")
        if isinstance(u, str) and u.startswith("http") and u not in seen:
            seen.add(u)
            out.append((u, t or ""))
        if len(out) == 2:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe")
    ap.add_argument("--label", default=None)
    args = ap.parse_args()

    pairs = sample_urls(args.recipe)
    if len(pairs) < 2:
        print(json.dumps({"verdict": "UNDECIDED", "why": "fewer than 2 distinct urls"}))
        return 0

    from playwright.sync_api import sync_playwright

    rendered = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"))
        for url, title in pairs:
            pg = ctx.new_page()
            try:
                resp = pg.goto(url, wait_until="domcontentloaded", timeout=45000)
                pg.wait_for_timeout(6000)
                body = pg.inner_text("body")
                rendered.append({
                    "url": url, "title": title, "status": resp.status if resp else 0,
                    "final_url": pg.url, "doc_title": pg.title(),
                    "text": norm(body), "chars": len(body),
                })
            except Exception as exc:  # noqa: BLE001
                rendered.append({"url": url, "title": title, "status": 0,
                                 "error": str(exc)[:200], "text": "", "chars": 0})
            pg.close()
        b.close()

    a, c = rendered
    ta, tc = norm(a["title"]), norm(c["title"])
    own = (ta and ta in a["text"]) and (tc and tc in c["text"])
    cross = (ta and ta in c["text"]) or (tc and tc in a["text"])
    differ = abs(a["chars"] - c["chars"]) >= max(200, 0.02 * max(a["chars"], c["chars"], 1))

    # The document <title> is the sharpest signal and the one the HTTP prover can never
    # see: an iframed job (Atlassian/iCIMS) puts nothing in body text but sets a correct
    # per-job <title>, and a listing-page fallback (Nintendo gh_jid, Walmart shell) sets
    # the SAME title on both. Distinct, job-specific document titles = the URL routes.
    da, dc = norm(a.get("doc_title", "")), norm(c.get("doc_title", ""))
    doc_titles_distinct = bool(da) and bool(dc) and da != dc
    # and each document title should be about its own job
    doc_own = bool(ta and da and (ta in da or da in ta)) and bool(tc and dc and (tc in dc or dc in tc))
    final_urls_distinct = a.get("final_url") != c.get("final_url")

    # Rendered texts differ at all (not by a 2% threshold — that bound exists only because
    # the HTTP prover compares LENGTHS of pages it cannot render). Two different rendered
    # pages IS the routing evidence.
    texts_differ = a["text"] != c["text"]

    if a["chars"] == 0 or c["chars"] == 0:
        verdict = "UNDECIDED"
    elif texts_differ and own:
        # each page renders its own job's title AND the two pages are not the same page
        verdict = "VERIFIER_TOO_STRICT"
    elif own and not cross:
        verdict = "VERIFIER_TOO_STRICT"
    elif doc_titles_distinct and (doc_own or (own and cross)):
        # each page's own <title> names its own job (or body carries both because the
        # page lists sibling roles) -> the link routes; the HTTP prover simply cannot see it
        verdict = "VERIFIER_TOO_STRICT"
    elif differ and ta != tc:
        verdict = "VERIFIER_TOO_STRICT"
    elif doc_titles_distinct and final_urls_distinct:
        verdict = "VERIFIER_TOO_STRICT"
    else:
        verdict = "RECIPE_WRONG"

    print(json.dumps({
        "label": args.label, "verdict": verdict,
        "title_on_own_page": bool(own), "title_on_other_page": bool(cross),
        "doc_titles_distinct": doc_titles_distinct, "doc_title_matches_job": doc_own,
        "final_urls_distinct": final_urls_distinct,
        "rendered_chars": [a["chars"], c["chars"]],
        "rendered_differ": differ,
        "samples": [{k: v for k, v in r.items() if k != "text"} for r in rendered],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
