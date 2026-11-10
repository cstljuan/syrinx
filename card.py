"""The Kairos receipt card: one 1200x600 SVG, drawn with nothing but the standard library.

It carries numbers only: minutes of focus, counts, seven daily bars. No question text, no file names,
no session ids, so it is safe to post. Colors and type follow the Hermes Agent docs theme (near black,
gold, cream, a monospace face) and the blocky gold wordmark.
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

BG = "#07070d"
SURFACE = "#0f0f18"
GOLD = "#FFD700"
AMBER = "#FFBF00"
BRONZE = "#CD7F32"
CREAM = "#e8e4dc"
MUTED = "#9a968e"
FONT = "'JetBrains Mono', 'Fira Code', ui-monospace, Menlo, monospace"

# 5x7 block letters, the same construction as a pixel wordmark.
_GLYPHS = {
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
}


def _fmt_minutes(minutes: int) -> str:
    minutes = max(0, int(minutes))
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours}h {rest}m" if rest else f"{hours}h"


def _wordmark(text: str, x: int, y: int, cell: int) -> str:
    """Block letters: an offset outline behind, three gold bands in front."""
    back: list[str] = []
    front: list[str] = []
    cursor = x
    for letter in text:
        rows = _GLYPHS.get(letter)
        if not rows:
            cursor += cell * 3
            continue
        for r, row in enumerate(rows):
            fill = GOLD if r < 3 else AMBER if r < 5 else BRONZE
            for c, bit in enumerate(row):
                if bit != "1":
                    continue
                px, py = cursor + c * cell, y + r * cell
                back.append(f'<rect x="{px + 4}" y="{py + 4}" width="{cell}" height="{cell}" '
                            f'fill="none" stroke="{BRONZE}" stroke-width="1"/>')
                front.append(f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" fill="{fill}"/>')
        cursor += cell * 6
    return "".join(back) + "".join(front)


def _text(x: int, y: int, body: str, *, size: int, fill: str, anchor: str = "start", weight: int = 400) -> str:
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}">{escape(str(body))}</text>')


def receipt_svg(data: dict[str, Any]) -> str:
    """Draw the card from ``Kairos.card_data()``."""
    totals = data.get("totals", {})
    days = list(data.get("days", []))[-7:]
    minutes = int(totals.get("focus_minutes", 0))
    parts: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 600" width="1200" height="600" '
        'role="img" aria-label="Kairos receipt">',
        f'<rect width="1200" height="600" fill="{BG}"/>',
        f'<rect x="24.5" y="24.5" width="1151" height="551" fill="none" stroke="{GOLD}" stroke-opacity="0.25"/>',
        _wordmark("KAIROS", 72, 72, 12),
        _text(72, 196, "the right moment, not just the fast one", size=20, fill=MUTED),
        _text(72, 326, _fmt_minutes(minutes), size=88, fill=GOLD, weight=700),
        _text(72, 374, "of focus kept from interruptions", size=24, fill=CREAM),
    ]

    stats = [
        (int(totals.get("questions_parked", 0)), "questions parked"),
        (int(totals.get("questions_batched", 0)), "handed back"),
        (int(totals.get("requests_queued", 0)), "left for morning"),
    ]
    for index, (value, label) in enumerate(stats):
        x = 72 + index * 210
        parts.append(_text(x, 470, value, size=44, fill=CREAM, weight=700))
        parts.append(_text(x, 500, label, size=14, fill=MUTED))

    # Seven daily bars on the right.
    left, base, top, width, gap = 780, 470, 200, 36, 14
    peak = max([int(day.get("focus_minutes", 0)) for day in days] + [1])
    parts.append(_text(left, 170, "last 7 days", size=16, fill=MUTED))
    parts.append(f'<line x1="{left}" y1="{base + 0.5}" x2="{left + 7 * (width + gap) - gap}" y2="{base + 0.5}" '
                 f'stroke="{GOLD}" stroke-opacity="0.25"/>')
    for index, day in enumerate(days):
        value = int(day.get("focus_minutes", 0))
        height = round((base - top) * value / peak) if value else 0
        x = left + index * (width + gap)
        is_today = index == len(days) - 1
        if height:
            parts.append(f'<rect x="{x}" y="{base - height}" width="{width}" height="{height}" '
                         f'fill="{GOLD}" fill-opacity="{1 if is_today else 0.45}"/>')
        else:
            parts.append(f'<rect x="{x}" y="{base - 2}" width="{width}" height="2" fill="{MUTED}" fill-opacity="0.5"/>')
        parts.append(_text(x + width // 2, base + 24, day.get("label", ""), size=14,
                           fill=CREAM if is_today else MUTED, anchor="middle"))

    blocks = int(totals.get("blocks_ended", 0))
    foot = f"{blocks} focus block{'s' if blocks != 1 else ''} · kairos, a Hermes Agent plugin"
    parts.append(_text(72, 548, foot, size=14, fill=MUTED))
    parts.append(_text(1128, 548, str(data.get("date", "")), size=14, fill=MUTED, anchor="end"))
    parts.append("</svg>")
    return "".join(parts)
