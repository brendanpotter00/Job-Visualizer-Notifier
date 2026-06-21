#!/usr/bin/env python3
"""Independent mechanical QA for the generated logo set (the 3 opaque variants).

Usage:
  verify_assets.py [--logos-dir src/frontend/public/logos] [--companies path/to/companies.ts]
                   [--size 128] [--variants icons,wordmarks,lockups]

Checks, for every company id in companies.ts and every variant dir:
  - file present (mirrors the companyLogoAssets.test.ts coverage gate)
  - OPAQUE (no real alpha channel) — these are background tiles, not transparent
  - icons are <size>x<size> square; wordmarks/lockups are <size> tall (banner)
  - not blank / not a single flat color (logo actually differs from the bg)
  - reports extra files not backed by a company id
Exit 0 if clean, 1 if any problems.
"""
import argparse
import os
import re
import sys

from PIL import Image


def companies_from_ts(path):
    src = open(path).read()
    start = src.find("COMPANIES")
    region = src[start:] if start != -1 else src
    pat = re.compile(r"createBackendScraperCompany\(\s*['\"]([^'\"]+)['\"]")
    out, seen = [], set()
    for m in pat.finditer(region):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1))
    return out


def find_default(name):
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        cand = os.path.join(d, "src", "frontend", "src", "config", "companies.ts") if name == "ts" else \
            os.path.join(d, "src", "frontend", "public", "logos")
        if os.path.exists(cand):
            return cand
        d = os.path.dirname(d)
    return None


def analyze(path, size, square):
    img = Image.open(path)
    has_alpha = img.mode in ("RGBA", "LA") and img.getchannel("A").getextrema()[0] < 255
    img = img.convert("RGB")
    w, h = img.size
    px = img.load()
    bg = px[2, 2]
    diff = tot = 0
    for y in range(0, h, max(1, h // 64)):
        for x in range(0, w, max(1, w // 64)):
            r, g, b = px[x, y]
            tot += 1
            if max(abs(r - bg[0]), abs(g - bg[1]), abs(b - bg[2])) > 40:
                diff += 1
    issues = []
    if has_alpha:
        issues.append("has transparency (should be opaque)")
    if square and (w, h) != (size, size):
        issues.append(f"not {size}x{size} (is {w}x{h})")
    if not square and h != size:
        issues.append(f"height != {size} (is {h})")
    if diff / tot < 0.01:
        issues.append("blank/flat (logo not visible vs bg)")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logos-dir", default=None)
    ap.add_argument("--companies", default=None)
    ap.add_argument("--size", type=int, default=128)
    ap.add_argument("--variants", default="icons,wordmarks,lockups")
    args = ap.parse_args()

    logos = args.logos_dir or find_default("logos")
    ts = args.companies or find_default("ts")
    if not logos or not ts:
        print("ERROR: could not locate logos dir or companies.ts (pass --logos-dir/--companies)", file=sys.stderr)
        return 1
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    ids = companies_from_ts(ts)
    idset = set(ids)
    problems = []
    print(f"companies: {len(ids)} | logos dir: {logos} | variants: {variants}")
    for v in variants:
        d = os.path.join(logos, v)
        square = v == "icons"
        files = set(os.path.splitext(f)[0] for f in os.listdir(d)) if os.path.isdir(d) else set()
        missing = sorted(idset - files)
        extra = sorted(files - idset)
        bad = []
        for cid in ids:
            p = os.path.join(d, cid + ".png")
            if not os.path.exists(p):
                continue
            try:
                for iss in analyze(p, args.size, square):
                    bad.append(f"{cid}: {iss}")
            except Exception as e:
                bad.append(f"{cid}: UNREADABLE {e}")
        print(f"\n[{v}] files={len(files)} missing={len(missing)} extra={len(extra)} invalid={len(bad)}")
        if missing:
            print("  missing:", missing)
        if extra:
            print("  extra:", extra)
        for b in bad:
            print("  -", b)
        problems += [f"{v}/{m}" for m in missing] + [f"{v}/{b}" for b in bad]

    print("\n==============================")
    if problems:
        print(f"FAIL: {len(problems)} problems")
        return 1
    print("PASS: all variants complete, opaque, correctly sized, non-blank ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
