#!/usr/bin/env python3
"""Composite a transparent logo master onto a solid background -> OPAQUE PNG.

Usage:
  tile.py <master.png> <output.png> --bg "#RRGGBB"
          [--knockout white|black|none] [--shape square|banner]
          [--size 128] [--pad 0.16] [--hpad 0.22]

- --shape square : <size> x <size> tile, logo centered (for the SYMBOL icon).
- --shape banner : height = <size>, variable width, logo height-normalized with
                   horizontal padding (for WORDMARK / LOCKUP).
- --knockout white|black recolors the logo to solid white/black (preserving the
  alpha edges) for contrast; 'none' keeps the logo's own colors (use on a
  neutral bg, esp. for multi-color logos).
- Output is fully OPAQUE RGB PNG.
"""
import argparse
import os
import sys

from PIL import Image


def hex2rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"bad hex color: {h}")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def knockout(fg, color_name):
    if color_name == "none":
        return fg
    color = (255, 255, 255) if color_name == "white" else (0, 0, 0)
    alpha = fg.split()[-1]
    out = Image.new("RGBA", fg.size, color + (0,))
    out.putalpha(alpha)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--bg", required=True)
    ap.add_argument("--knockout", choices=["white", "black", "none"], default="none")
    ap.add_argument("--shape", choices=["square", "banner"], default="square")
    ap.add_argument("--size", type=int, default=128, help="square side, or banner height")
    ap.add_argument("--pad", type=float, default=0.16, help="square: margin fraction")
    ap.add_argument("--hpad", type=float, default=0.22, help="banner: horiz pad as fraction of height")
    args = ap.parse_args()

    bg = hex2rgb(args.bg)
    fg = Image.open(args.input).convert("RGBA")
    fg = knockout(fg, args.knockout)

    bbox = fg.split()[-1].getbbox()
    if bbox is None:
        print(f"ERROR: {args.input} is blank", file=sys.stderr)
        return 2
    fg = fg.crop(bbox)
    w, h = fg.size

    if args.shape == "square":
        inner = max(1, int(round(args.size * (1 - 2 * args.pad))))
        scale = inner / max(w, h)
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        fg = fg.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGB", (args.size, args.size), bg)
        canvas.paste(fg, ((args.size - nw) // 2, (args.size - nh) // 2), fg)
    else:  # banner
        target_h = max(1, int(round(args.size * (1 - 0.18))))  # vertical breathing room
        scale = target_h / h
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        fg = fg.resize((nw, nh), Image.LANCZOS)
        hpad = int(round(args.size * args.hpad))
        cw = nw + 2 * hpad
        canvas = Image.new("RGB", (cw, args.size), bg)
        canvas.paste(fg, (hpad, (args.size - nh) // 2), fg)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    canvas.save(args.output, "PNG")
    print(f"OK {args.output} {canvas.size[0]}x{canvas.size[1]} bg={args.bg} knockout={args.knockout} shape={args.shape}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
