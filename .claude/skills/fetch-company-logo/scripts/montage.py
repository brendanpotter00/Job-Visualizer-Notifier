#!/usr/bin/env python3
"""Build a labeled QA contact sheet from a folder of logo PNGs (for human review).

Usage:
  montage.py <folder> <output.png> [--cols 10] [--cell 200] [--title "Icons"]

Each logo is drawn on a checkerboard tile (so any transparency is visible) with
its filename stem as a caption. Opaque tiles simply show their own background.
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont


def load_font(size):
    for p in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def checker(s, sq=16):
    bg = Image.new("RGBA", (s, s), (235, 235, 235, 255))
    d = ImageDraw.Draw(bg)
    for y in range(0, s, sq):
        for x in range(0, s, sq):
            if (x // sq + y // sq) % 2 == 0:
                d.rectangle([x, y, x + sq, y + sq], fill=(205, 205, 205, 255))
    return bg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("output")
    ap.add_argument("--cols", type=int, default=10)
    ap.add_argument("--cell", type=int, default=200)
    ap.add_argument("--title", default="")
    args = ap.parse_args()

    stems = sorted(os.path.splitext(f)[0] for f in os.listdir(args.folder) if f.lower().endswith(".png"))
    if not stems:
        print("no PNGs in", args.folder, file=sys.stderr)
        return 1
    cell, pad, lab = args.cell, 10, 26
    cols = max(1, args.cols)
    rows = (len(stems) + cols - 1) // cols
    title_h = 50 if args.title else 0
    W = cols * cell + pad * (cols + 1)
    H = title_h + rows * (cell + lab) + pad * (rows + 1)
    sheet = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(sheet)
    font, tfont = load_font(15), load_font(28)
    if args.title:
        d.text((pad, 12), args.title, fill=(20, 20, 20), font=tfont)
    tile = checker(cell)
    for i, stem in enumerate(stems):
        r, c = divmod(i, cols)
        x = pad + c * (cell + pad)
        y = title_h + pad + r * (cell + lab + pad)
        sheet.alpha_composite(tile, (x, y))
        try:
            lg = Image.open(os.path.join(args.folder, stem + ".png")).convert("RGBA").resize((cell, cell), Image.LANCZOS)
            sheet.alpha_composite(lg, (x, y))
        except Exception:
            d.text((x + 6, y + 6), "ERR", fill=(200, 0, 0), font=font)
        d.text((x + 3, y + cell + 3), stem, fill=(20, 20, 20), font=font)
    sheet.convert("RGB").save(args.output, "PNG")
    print(f"OK {args.output} {W}x{H} ({len(stems)} logos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
