"""Development helper: turn the cyanotype art into the files the plugin ships in ``assets/``.

Needs Pillow and numpy, which the plugin itself never imports:

    uv run --with pillow --with numpy python tools/make_assets.py plate    <art.png>
    uv run --with pillow --with numpy python tools/make_assets.py numerals <sheet.png> "0123456789hm"
    uv run --with pillow --with numpy python tools/make_assets.py poses    <sheet.png> <rows> <cols> <name,name,...>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

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
    rows = np.where(ink.sum(axis=1) > 2)[0]
    top, bottom = int(rows.min()), int(rows.max()) + 1
    columns = _runs(ink[top:bottom].sum(axis=0) > 1, min_gap=max(6, sheet.width // 160))
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


def cut_sprite(image: Image.Image) -> Image.Image:
    """One pose off white paper: flood the outside, keep the body with its pale belly and eyes."""
    ink = _blueness(image) > 26
    mask = Image.fromarray((ink * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))
    canvas = Image.new("L", (mask.width + 2, mask.height + 2), 0)
    canvas.paste(mask, (1, 1))
    ImageDraw.floodfill(canvas, (0, 0), 128)
    inside = np.asarray(canvas.crop((1, 1, mask.width + 1, mask.height + 1))) != 128
    solid = Image.fromarray((inside * 255).astype(np.uint8))
    core = solid.filter(ImageFilter.MinFilter(15)).getbbox()
    if core is None:
        raise SystemExit("no sprite found in a cell")
    left, top, right, bottom = core[0] - 12, core[1] - 12, core[2] + 12, core[3] + 12
    alpha = solid.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(1.0))
    keep = Image.new("L", alpha.size, 0)
    keep.paste(alpha.crop((left, top, right, bottom)), (left, top))
    sprite = image.convert("RGBA")
    sprite.putalpha(keep)
    return sprite.crop(keep.point(lambda v: 255 if v > 40 else 0).getbbox())


def poses(path: str, rows: str, cols: str, names: str) -> None:
    """Cut a grid of poses into ``assets/argus/<name>.png``."""
    sheet = Image.open(path).convert("RGB")
    n_rows, n_cols = int(rows), int(cols)
    labels = names.split(",")
    out_dir = ASSETS / "argus"
    out_dir.mkdir(parents=True, exist_ok=True)
    cell_w, cell_h = sheet.width / n_cols, sheet.height / n_rows
    for index, name in enumerate(labels):
        r, c = divmod(index, n_cols)
        cell = sheet.crop((round(c * cell_w), round(r * cell_h), round((c + 1) * cell_w), round((r + 1) * cell_h)))
        sprite = cut_sprite(cell)
        target = out_dir / f"{name}.png"
        sprite.save(target, optimize=True)
        print(target.name, sprite.size, target.stat().st_size)


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    {"plate": plate, "numerals": numerals, "poses": poses}[command](*args)
