"""Development helper: build the animated Argus pet for Hermes from the pose cutouts.

Key poses are painted; every in-between is made here by moving a pose (breathe, bob, waddle, hop),
so the print grain is identical from frame to frame and never flickers.

    uv run --with pillow python tools/build_pet.py

Reads ``art/poses/*.png`` (on the ``art`` branch), writes ``assets/pet/argus/spritesheet.webp`` and
``pet.json`` in the petdex layout Hermes loads: 8 columns by 9 rows of 192x208 cells.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
POSES = ROOT / "art" / "poses"
OUT = ROOT / "assets" / "pet" / "argus"
CELL_W, CELL_H = 192, 208
# (state, row, frames): the petdex nine-state sheet.
ROWS = [("idle", 0, 6), ("running-right", 1, 8), ("running-left", 2, 8), ("waving", 3, 4), ("jumping", 4, 5),
        ("failed", 5, 8), ("waiting", 6, 6), ("running", 7, 6), ("review", 8, 6)]
FLOOR = CELL_H - 8          # every pose stands on this line
HEADROOM = 30               # room above for hops


def pose(name: str) -> Image.Image:
    return Image.open(POSES / f"{name}.png").convert("RGBA")


BASE = min((CELL_W - 14) / 349, (CELL_H - 8 - HEADROOM) / 384)      # the idle pose sets the size of the bird


def frame(name: str, *, sx: float = 1.0, sy: float = 1.0, dy: int = 0, turn: float = 0.0) -> Image.Image:
    """One cell: the pose scaled, optionally squashed, tilted about its feet, and lifted."""
    sprite = pose(name)
    scale = min(BASE, (CELL_W - 10) / sprite.width, (CELL_H - 8 - HEADROOM) / sprite.height)
    size = (max(1, round(sprite.width * scale * sx)), max(1, round(sprite.height * scale * sy)))
    sprite = sprite.resize(size, Image.Resampling.LANCZOS)
    if turn:
        # Tilt about the feet: pad so the feet sit at the centre, rotate, then cut the padding off.
        tall = Image.new("RGBA", (sprite.width * 2, sprite.height * 2), (0, 0, 0, 0))
        tall.alpha_composite(sprite, (sprite.width // 2, 0))
        tall = tall.rotate(turn, resample=Image.Resampling.BICUBIC, center=(sprite.width, sprite.height))
        box = tall.getbbox()
        feet_x = sprite.width - box[0]
        sprite = tall.crop(box)
    else:
        feet_x = sprite.width // 2
    cell = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    x = max(0, min(CELL_W - sprite.width, CELL_W // 2 - feet_x))
    y = max(0, FLOOR - sprite.height + dy)
    cell.alpha_composite(sprite, (x, y))
    return cell


BREATH = [(1.0, 1.0), (1.012, 0.985), (1.022, 0.97), (1.012, 0.985)]


def build() -> dict[str, list[Image.Image]]:
    idle = [frame("idle", sx=sx, sy=sy) for sx, sy in BREATH]
    return {
        # Breathing, then one slow blink of every eye.
        "idle": [idle[0], idle[1], idle[2], idle[3], frame("focus"), idle[0]],
        "running-right": [frame("walk-right", turn=t, dy=d) for t, d in [(-4, 0), (4, -4)] * 4],
        "running-left": [frame("walk-left", turn=t, dy=d) for t, d in [(4, 0), (-4, -4)] * 4],
        "waving": [frame("wave", turn=t) for t in (-5, 0, 5, 0)],
        "jumping": [frame("happy", sx=1.05, sy=0.93), frame("jump", dy=-8), frame("jump", sx=0.97, sy=1.04, dy=-22),
                    frame("jump", dy=-8), frame("happy", sx=1.05, sy=0.93)],
        "failed": [frame("sad", sy=sy) for sy in (1.0, 0.99, 0.98, 0.97, 0.96, 0.96, 0.97, 0.98)],
        # Blocked on you: he holds the letter out and bobs.
        "waiting": [frame("letter", dy=d) for d in (0, -3, -6, -6, -3, 0)],
        # A tool is running: he writes.
        "running": [frame("write", turn=t, dy=d) for t, d in ((-2, 0), (0, -1), (2, 0), (0, -1), (-2, 0), (0, -1))],
        # The model is thinking: he reads.
        "review": [frame("read", turn=t) for t in (0, -2, -3, -2, 0, 1)],
    }


def main() -> None:
    frames = build()
    atlas = Image.new("RGBA", (CELL_W * 8, CELL_H * len(ROWS)), (0, 0, 0, 0))
    for state, row, count in ROWS:
        cells = frames[state]
        if len(cells) != count:
            raise SystemExit(f"{state}: {len(cells)} frames, expected {count}")
        for col, cell in enumerate(cells):
            atlas.alpha_composite(cell, (col * CELL_W, row * CELL_H))
    OUT.mkdir(parents=True, exist_ok=True)
    sheet = OUT / "spritesheet.webp"
    atlas.save(sheet, "WEBP", lossless=True, quality=100, method=6, exact=True)
    meta = {"id": "argus", "displayName": "Argus",
            "description": "The hundred-eyed watchman Hermes played to sleep. A cyanotype peacock chick who keeps your questions until the right moment.",
            "spritesheetPath": sheet.name}
    (OUT / "pet.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(sheet, atlas.size, sheet.stat().st_size)

    if len(sys.argv) > 1:       # optional preview GIF: every state, on the dark app background
        shots = []
        for state, _row, _count in ROWS:
            for _ in range(2):
                for cell in frames[state]:
                    bg = Image.new("RGB", (CELL_W * 2, CELL_H * 2), "#0f0f18")
                    big = cell.resize((CELL_W * 2, CELL_H * 2), Image.Resampling.LANCZOS)
                    bg.paste(big, (0, 0), big)
                    shots.append(bg)
        shots[0].save(sys.argv[1], save_all=True, append_images=shots[1:], duration=183, loop=0)
        print(sys.argv[1], len(shots))


if __name__ == "__main__":
    main()
