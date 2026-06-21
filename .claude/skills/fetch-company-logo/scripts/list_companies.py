#!/usr/bin/env python3
"""Extract the canonical company list (id, name) from companies.ts.

Usage:
  list_companies.py [path/to/companies.ts] [--json]

Defaults to src/frontend/src/config/companies.ts relative to the repo root
(auto-detected by walking up from this script). Parses every
createBackendScraperCompany('id', 'Name', ...) entry inside the COMPANIES array.
This is the source of truth — the companyLogoAssets.test.ts gate enumerates the
same list, so the logo set must cover exactly these ids.
"""
import json
import os
import re
import sys


def find_companies_ts(explicit):
    if explicit:
        return explicit
    here = os.path.dirname(os.path.abspath(__file__))
    d = here
    for _ in range(8):
        cand = os.path.join(d, "src", "frontend", "src", "config", "companies.ts")
        if os.path.exists(cand):
            return cand
        d = os.path.dirname(d)
    raise SystemExit("could not locate src/frontend/src/config/companies.ts; pass the path explicitly")


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv[1:]
    path = find_companies_ts(args[0] if args else None)
    src = open(path).read()

    # Only the COMPANIES array region (avoid the COMPANY_IDS enum etc.)
    start = src.find("COMPANIES")
    region = src[start:] if start != -1 else src

    # createBackendScraperCompany('id', 'Name', ...   (single or double quotes)
    pat = re.compile(
        r"createBackendScraperCompany\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]"
    )
    seen = {}
    for m in pat.finditer(region):
        cid, name = m.group(1), m.group(2)
        seen.setdefault(cid, name)

    companies = [{"id": k, "name": v} for k, v in seen.items()]
    if as_json:
        print(json.dumps({"count": len(companies), "companies": companies}, indent=2))
    else:
        print(f"# {len(companies)} companies from {path}")
        for c in companies:
            print(f"{c['id']}\t{c['name']}")


if __name__ == "__main__":
    main()
