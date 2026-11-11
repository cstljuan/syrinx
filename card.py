"""The Syrinx receipt card: one 1200x600 SVG, drawn with nothing but the standard library.

It carries numbers only: minutes of focus, counts, seven days. No question text, no file names, no
session ids, so it is safe to post.

The card is a cyanotype print. The background plate (Argus asleep while Hermes plays to him) and the
hand-painted numerals are image files in ``assets/``, embedded into the SVG so the card is one
self-contained file. Everything else is drawn here in the same Prussian blue: the lettering, and the
week as seven small feathers, each as tall as the focus you kept, with the eye at its tip closed on a
day you kept focus and open on a day you did not. Without the image files the card falls back to
plain lettering on paper.
"""

from __future__ import annotations

import base64
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

ASSETS = Path(__file__).resolve().parent / "assets"
PAPER = "#f1eee7"
INK = "#173a72"
SOFT_INK = "#4f6a94"
SERIF = "Didot, 'Bodoni 72', 'Bodoni MT', 'Playfair Display', 'Hoefler Text', Baskerville, Georgia, serif"
GLYPHS = "0123456789hm"


@lru_cache(maxsize=None)
def _data_uri(relative: str) -> Optional[str]:
    path = ASSETS / relative
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    kind = "image/png" if relative.endswith(".png") else "image/jpeg"
    return f"data:{kind};base64,{base64.b64encode(raw).decode('ascii')}"


@lru_cache(maxsize=None)
def _png_size(relative: str) -> Optional[tuple[int, int]]:
    try:
        with open(ASSETS / relative, "rb") as handle:
            head = handle.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def _have_numerals() -> bool:
    return all(_png_size(f"numerals/{ch}.png") for ch in GLYPHS)


def _fmt_minutes(minutes: int) -> str:
    minutes = max(0, int(minutes))
    if minutes < 60:
        return f"{minutes}m"
    hours, rest = divmod(minutes, 60)
    return f"{hours}h {rest}m" if rest else f"{hours}h"


def _text(x: float, y: float, body: Any, *, size: int, fill: str = INK, anchor: str = "start", italic: bool = False,
          spacing: float = 0, weight: int = 400) -> str:
    extra = ' font-style="italic"' if italic else ""
    if spacing:
        extra += f' letter-spacing="{spacing}"'
    return (f'<text x="{x}" y="{y}" font-family="{SERIF}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{extra} filter="url(#print)">{escape(str(body))}</text>')


def _painted(text: str, x: float, top: float, height: float) -> tuple[str, float]:
    """A number set in the painted numerals. Units (h, m) are drawn smaller, on the same baseline."""
    out: list[str] = []
    cursor = x
    for ch in text:
        if ch == " ":
            cursor += height * 0.2
            continue
        size = _png_size(f"numerals/{ch}.png")
        if not size:
            continue
        unit = ch in "hm"
        scale = (height * (0.58 if unit else 1.0)) / size[1]
        y = top + height - size[1] * scale
        out.append(f'<use href="#n{ch}" transform="translate({cursor:.1f} {y:.1f}) scale({scale:.4f})"/>')
        cursor += size[0] * scale + height * (0.02 if unit else 0.035)
    return "".join(out), cursor


def _number(text: str, x: float, top: float, height: float) -> tuple[str, float]:
    if _have_numerals():
        return _painted(text, x, top, height)
    size = round(height * 1.08)
    return _text(x, top + height * 0.92, text, size=size, weight=500), x + size * 0.5 * len(text)


def _eye(cx: float, cy: float, *, closed: bool) -> str:
    """One of Argus' eyes: a lid with lashes when asleep, a ring with a pupil when watching."""
    if closed:
        lashes = "".join(
            f'<line x1="{cx + dx:.1f}" y1="{cy + 4 - abs(dx) / 4:.1f}" x2="{cx + dx * 1.3:.1f}" y2="{cy + 10 - abs(dx) / 4:.1f}"/>'
            for dx in (-9, -3, 3, 9))
        return (f'<g fill="none" stroke="{INK}" stroke-width="2.2" stroke-linecap="round" filter="url(#print)">'
                f'<path d="M {cx - 13:.1f} {cy:.1f} Q {cx:.1f} {cy + 10:.1f} {cx + 13:.1f} {cy:.1f}"/>{lashes}</g>')
    return (f'<g filter="url(#print)"><ellipse cx="{cx:.1f}" cy="{cy + 3:.1f}" rx="12" ry="7.5" fill="none" stroke="{INK}" '
            f'stroke-width="2"/><circle cx="{cx:.1f}" cy="{cy + 3:.1f}" r="3.4" fill="{INK}"/></g>')


def _week(days: list[dict[str, Any]], x: float, base: float) -> str:
    """Seven small feathers on one line."""
    out: list[str] = []
    peak = max([int(day.get("focus_minutes", 0)) for day in days] + [1])
    step = 60
    for index, day in enumerate(days):
        value = int(day.get("focus_minutes", 0))
        height = 14 + round(42 * value / peak) if value else 6
        cx = x + 16 + index * step
        today = index == len(days) - 1
        # No filter here: a perfectly vertical line has an empty bounding box and would not be drawn.
        out.append(f'<line x1="{cx}" y1="{base}" x2="{cx}" y2="{base - height}" stroke="{INK}" '
                   f'stroke-width="{2.6 if today else 1.8}" stroke-linecap="round"/>')
        barb = base - 5
        while barb > base - height + 6:
            out.append(f'<path d="M {cx - 6} {barb - 5} L {cx} {barb} L {cx + 6} {barb - 5}" fill="none" stroke="{INK}" '
                       f'stroke-opacity="0.55" stroke-width="1"/>')
            barb -= 7
        out.append(_eye(cx, base - height - 16, closed=bool(value)))
        out.append(_text(cx, base + 24, day.get("label", ""), size=15, anchor="middle", italic=True,
                         fill=INK if today else SOFT_INK))
    return "".join(out)


def receipt_svg(data: dict[str, Any]) -> str:
    """Draw the card from ``Syrinx.card_data()``."""
    totals = data.get("totals", {})
    days = list(data.get("days", []))[-7:]
    minutes = int(totals.get("focus_minutes", 0))
    blocks = int(totals.get("blocks_ended", 0))
    total = _fmt_minutes(minutes)
    plate = _data_uri("card-plate.jpg")
    label = f"Syrinx receipt: {total} of focus kept from interruptions"

    defs = ['<filter id="print" x="-5%" y="-20%" width="110%" height="140%">'
            '<feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="1" seed="2" result="n"/>'
            '<feDisplacementMap in="SourceGraphic" in2="n" scale="1.5"/></filter>'
            '<filter id="paper" x="0" y="0" width="100%" height="100%">'
            '<feTurbulence type="fractalNoise" baseFrequency="0.7" numOctaves="3" seed="9"/>'
            '<feColorMatrix type="matrix" values="0 0 0 0 0.35  0 0 0 0 0.33  0 0 0 0 0.3  0 0 0 0.55 -0.25"/></filter>']
    if _have_numerals():
        for ch in GLYPHS:
            width, height = _png_size(f"numerals/{ch}.png")  # type: ignore[misc]
            defs.append(f'<image id="n{ch}" width="{width}" height="{height}" href="{_data_uri(f"numerals/{ch}.png")}"/>')

    parts: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 600" width="1200" height="600" '
        f'role="img" aria-label="{escape(label)}">',
        f"<title>{escape(label)}</title>",
        "<defs>" + "".join(defs) + "</defs>",
        f'<rect width="1200" height="600" fill="{PAPER}"/>',
    ]
    if plate:
        parts.append(f'<image width="1200" height="600" preserveAspectRatio="xMidYMid slice" href="{plate}"/>')
    else:
        parts.append('<rect width="1200" height="600" filter="url(#paper)" opacity="0.5"/>')

    parts.append(_text(66, 88, "SYRINX", size=30, spacing=13))
    parts.append(_text(66, 116, f"time given back  ·  {data.get('date', '')}", size=16, italic=True, fill=SOFT_INK))

    # The total, as large as fits on the paper beside the print.
    height, room = 132.0, 462.0
    number, end = _number(total, 62, 150, height)
    if end - 62 > room:
        height *= room / (end - 62)
        number, end = _number(total, 62, 150 + (132 - height), height)
    parts.append(number)
    parts.append(_text(66, 326, "of focus kept from interruptions", size=24, italic=True))

    stats = [
        (int(totals.get("questions_parked", 0)), "questions parked"),
        (int(totals.get("questions_batched", 0)), "handed back"),
        (int(totals.get("requests_queued", 0)), "left for morning"),
    ]
    for index, (value, caption) in enumerate(stats):
        x = 66 + index * 150
        drawn, _ = _number(str(value), x - 2, 358, 44)
        parts.append(drawn)
        parts.append(_text(x, 426, caption, size=15, italic=True, fill=SOFT_INK))

    parts.append(_week(days, 66, 536))
    foot = f"{blocks} focus block{'s' if blocks != 1 else ''}  ·  a Hermes Agent plugin"
    parts.append(_text(1176, 584, foot, size=13, anchor="end", italic=True, fill="#eef1f6"))
    parts.append("</svg>")
    return "".join(parts)
