"""Development helper: turn the cyanotype art into the files the plugin ships in ``assets/``.

Needs Pillow and numpy, which the plugin itself never imports:

    uv run --with pillow --with numpy python tools/make_assets.py plate    <art.png>
    uv run --with pillow --with numpy python tools/make_assets.py numerals <sheet.png> "0123456789hm"
    uv run --with pillow --with numpy --with scipy python tools/make_assets.py poses <sheet.png> <name,name,...>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def _blueness(image: Image.Image) -> np.ndarray:
    data = np.asarray(image.convert("RGB")).astype(np.int16)
    return data[..., 2] - data[..., 0]          # paper is neutral, pigment is blue


def plate(path: str) -> None:
    """Card background: 1200x600, cropped from the centre."""
    art = Image.open(path).convert("RGB")
    target = 2.0
    if art.width / art.height > target:
        width = round(art.height * target)
        art = art.crop(((art.width - width) // 2, 0, (art.width + width) // 2, art.height))
    else:
        height = round(art.width / target)
        art = art.crop((0, (art.height - height) // 2, art.width, (art.height + height) // 2))
    art = art.resize((1200, 600), Image.Resampling.LANCZOS)
    out = ASSETS / "card-plate.jpg"
    art.save(out, "JPEG", quality=80, optimize=True, progressive=True)
    print(out, out.stat().st_size)


def _runs(flags: np.ndarray, min_gap: int) -> list[tuple[int, int]]:
    """Start and end of each stretch of True, merging stretches closer than ``min_gap``."""
    runs: list[list[int]] = []
    start = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append([start, index]); start = None
    if start is not None:
        runs.append([start, len(flags)])
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] < min_gap:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    return [(a, b) for a, b in merged]


def numerals(path: str, order: str) -> None:
    """Cut a painted row of glyphs into one transparent PNG each, all on one baseline."""
    sheet = Image.open(path).convert("RGB")
    blue = _blueness(sheet)
    ink = blue > 28
    rows = np.where(ink.sum(axis=1) > sheet.width * 0.02)[0]      # the glyph band, not a stray stain
    top, bottom = int(rows.min()), int(rows.max()) + 1
    columns = _runs(ink[top:bottom].sum(axis=0) > (bottom - top) * 0.02, min_gap=max(6, sheet.width // 160))
    columns = [(a, b) for a, b in columns if b - a > sheet.width // 200]
    if len(columns) != len(order):
        raise SystemExit(f"found {len(columns)} glyphs, expected {len(order)}: {columns}")
    out_dir = ASSETS / "numerals"
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = 200 / (bottom - top)
    for char, (left, right) in zip(order, columns):
        box = (max(0, left - 6), max(0, top - 6), min(sheet.width, right + 6), min(sheet.height, bottom + 6))
        crop = sheet.crop(box)
        alpha = np.clip((_blueness(crop) - 8) * 4.2, 0, 255).astype(np.uint8)
        glyph = crop.convert("RGBA")
        glyph.putalpha(Image.fromarray(alpha))
        glyph = glyph.resize((max(1, round(glyph.width * scale)), max(1, round(glyph.height * scale))), Image.Resampling.LANCZOS)
        glyph = glyph.quantize(colors=48, method=Image.Quantize.FASTOCTREE)
        target = out_dir / f"{char}.png"
        glyph.save(target, optimize=True)
        print(target.name, glyph.size, target.stat().st_size)


def poses(path: str, names: str) -> None:
    """Find every pose on a sheet, reading order: full PNG to ``art/poses``, small WebP to ``assets/argus``.

    Poses are found as connected blobs of pigment, so nothing is clipped at a grid line and pale
    paper stains are left behind. Holes (the pale belly, the eye whites, a scroll) are filled.
    """
    from scipy import ndimage

    sheet = Image.open(path).convert("RGB")
    labels_wanted = names.split(",")
    ink = _blueness(sheet) > 30
    joined = ndimage.binary_dilation(ink, iterations=4)
    labelled, count = ndimage.label(joined)
    sizes = ndimage.sum(joined, labelled, range(1, count + 1))
    floor = 0.012 * sheet.width * sheet.height
    blobs = []
    for index, size in enumerate(sizes, start=1):
        if size < floor:
            continue
        rows, cols = np.where(labelled == index)
        blobs.append((index, rows.min(), rows.max() + 1, cols.min(), cols.max() + 1))
    if len(blobs) != len(labels_wanted):
        raise SystemExit(f"found {len(blobs)} poses, expected {len(labels_wanted)}")
    # Reading order: split into rows by vertical centre, then left to right.
    blobs.sort(key=lambda b: (b[1] + b[2]) / 2)
    ordered, row = [], [blobs[0]]
    for blob in blobs[1:]:
        if (blob[1] + blob[2]) / 2 - (row[-1][1] + row[-1][2]) / 2 > sheet.height * 0.2:
            ordered += sorted(row, key=lambda b: b[3]); row = [blob]
        else:
            row.append(blob)
    ordered += sorted(row, key=lambda b: b[3])

    out_dir = ASSETS.parent / "art" / "poses"       # full cutouts, kept for building the pet
    small_dir = ASSETS / "argus"                    # small WebP copies, shipped for the pane
    out_dir.mkdir(parents=True, exist_ok=True)
    small_dir.mkdir(parents=True, exist_ok=True)
    rgba = np.dstack([np.asarray(sheet), np.zeros((sheet.height, sheet.width), np.uint8)])
    for name, (index, top, bottom, left, right) in zip(labels_wanted, ordered):
        solid = ndimage.binary_fill_holes(labelled == index)
        solid = ndimage.binary_erosion(solid, iterations=5)          # bite back the dilation and the paper halo
        alpha = Image.fromarray((solid * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.1))
        cut = rgba.copy()
        cut[..., 3] = np.asarray(alpha)
        sprite = Image.fromarray(cut, "RGBA").crop((left, top, right, bottom))
        sprite = sprite.crop(sprite.getchannel("A").point(lambda v: 255 if v > 30 else 0).getbbox())
        if max(sprite.size) > 384:
            sprite.thumbnail((384, 384), Image.Resampling.LANCZOS)
        target = out_dir / f"{name}.png"
        sprite.save(target, optimize=True)
        small = sprite.copy()
        small.thumbnail((240, 240), Image.Resampling.LANCZOS)
        small.save(small_dir / f"{name}.webp", "WEBP", quality=82, method=6)
        print(target.name, sprite.size, target.stat().st_size, (small_dir / f"{name}.webp").stat().st_size)


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    {"plate": plate, "numerals": numerals, "poses": poses}[command](*args)
