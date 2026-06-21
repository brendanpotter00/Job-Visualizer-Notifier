#!/usr/bin/env python3
"""Build a combined LOCKUP (symbol + wordmark, side by side) on an OPAQUE banner.

Usage:
  compose_lockup.py <symbol_master.png> <wordmark_master.png> <output.png>
        --bg "#RRGGBB" [--knockout white|black|none] [--height 128] [--gap 0.18]

Both inputs are transparent masters (from normalize.py). The symbol and the
wordmark are height-normalized to a common cap height, placed left-to-right with
a gap, and composited onto an opaque background banner. Use when you want a
deterministic lockup from the two parts; if the brand publishes an official
combined lockup asset, prefer running that single asset through tile.py --shape banner.
"""
import argparse
import os
import sys

from PIL import Image


def hex2rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def knockout(fg, name):
    if name == "none":
        return fg
    color = (255, 255, 255) if name == "white" else (0, 0, 0)
    a = fg.split()[-1]
    out = Image.new("RGBA", fg.size, color + (0,))
    out.putalpha(a)
    return out


def prep(path, name):
    img = Image.open(path).convert("RGBA")
    img = knockout(img, name)
    bbox = img.split()[-1].getbbox()
    if bbox is None:
        raise ValueError(f"{path} is blank")
    return img.crop(bbox)


def scale_to_h(img, h):
    w0, h0 = img.size
    s = h / h0
    return img.resize((max(1, round(w0 * s)), h), Image.LANCZOS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("wordmark")
    ap.add_argument("output")
    ap.add_argument("--bg", required=True)
    ap.add_argument("--knockout", choices=["white", "black", "none"], default="none")
    ap.add_argument("--height", type=int, default=128)
    ap.add_argument("--gap", type=float, default=0.18, help="gap as fraction of banner height")
    args = ap.parse_args()

    bg = hex2rgb(args.bg)
    cap = max(1, int(round(args.height * (1 - 0.30))))  # content cap height
    sym = scale_to_h(prep(args.symbol, args.knockout), cap)
    # wordmark is usually visually shorter cap-height; match symbol height for balance
    wm = scale_to_h(prep(args.wordmark, args.knockout), int(cap * 0.78))

    gap = int(round(args.height * args.gap))
    hpad = int(round(args.height * 0.16))
    cw = hpad + sym.size[0] + gap + wm.size[0] + hpad
    canvas = Image.new("RGB", (cw, args.height), bg)
    x = hpad
    canvas.paste(sym, (x, (args.height - sym.size[1]) // 2), sym)
    x += sym.size[0] + gap
    canvas.paste(wm, (x, (args.height - wm.size[1]) // 2), wm)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    canvas.save(args.output, "PNG")
    print(f"OK {args.output} {cw}x{args.height} bg={args.bg} knockout={args.knockout} (lockup)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
