#!/usr/bin/env python3
"""Turn any logo source (SVG/PNG/JPG/ICO/WEBP) into a clean TRANSPARENT master PNG.

Usage:
  normalize.py <input> <output.png> [--max 1024] [--remove-white] [--bg-threshold 240]

- SVG inputs are rasterized via cairosvg at high resolution.
- Output is RGBA, autocropped to the logo's bounding box, longest side = --max,
  with NO canvas/padding (it is an intermediate "master"; tile.py / compose_lockup.py
  place it on a final background at the deployed size).
- --remove-white floods near-white pixels connected to the corners to transparent
  (use ONLY when a raster source has a solid white background; off by default so
  logos that legitimately contain white are never damaged).

Exit: 0 ok, 2 blank/empty result, 1 error.
"""
import argparse
import io
import os
import sys
from collections import deque

from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def _looks_like_svg(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(512).lstrip()
        return head[:5].lower() == b"<?xml" or b"<svg" in head[:512].lower()
    except OSError:
        return False


def load_image(path: str, render_px: int) -> Image.Image:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".svg" or _looks_like_svg(path):
        import cairosvg  # requires libcairo (brew install cairo)

        png = cairosvg.svg2png(url=path, output_width=render_px)
        return Image.open(io.BytesIO(png)).convert("RGBA")
    img = Image.open(path)
    if ext == ".ico":
        try:
            best = max(img.ico.sizes(), key=lambda s: s[0] * s[1])
            img = img.ico.getimage(best)
        except Exception:
            pass
    return img.convert("RGBA")


def flood_remove_white(img: Image.Image, threshold: int) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()

    def whiteish(p):
        r, g, b, a = p
        return a > 0 and r >= threshold and g >= threshold and b >= threshold

    seen = bytearray(w * h)
    dq = deque()
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if not seen[y * w + x] and whiteish(px[x, y]):
            seen[y * w + x] = 1
            dq.append((x, y))
    while dq:
        x, y = dq.popleft()
        r, g, b, _ = px[x, y]
        px[x, y] = (r, g, b, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and whiteish(px[nx, ny]):
                seen[ny * w + nx] = 1
                dq.append((nx, ny))
    return img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--max", type=int, default=1024, help="longest side of the output")
    ap.add_argument("--remove-white", action="store_true")
    ap.add_argument("--bg-threshold", type=int, default=240)
    args = ap.parse_args()

    try:
        img = load_image(args.input, render_px=args.max * 2)
    except Exception as e:
        print(f"ERROR loading {args.input}: {e}", file=sys.stderr)
        return 1

    if args.remove_white:
        img = flood_remove_white(img, args.bg_threshold)

    bbox = img.split()[-1].getbbox()
    if bbox is None:
        print(f"ERROR: {args.input} is blank / fully transparent", file=sys.stderr)
        return 2
    img = img.crop(bbox)

    w, h = img.size
    scale = args.max / max(w, h)
    if scale < 1:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    img.save(args.output, "PNG")
    print(f"OK {args.output} {img.size[0]}x{img.size[1]} RGBA master")
    return 0


if __name__ == "__main__":
    sys.exit(main())
