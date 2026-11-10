"""The Kairos receipt card: one 1200x600 SVG, drawn with nothing but the standard library.

It carries numbers only: minutes of focus, counts, seven days. No question text, no file names, no
session ids, so it is safe to post.

The look borrows the Nous Research house style without using any of its artwork: a midnight ground
inside a thin electric-blue frame, tall condensed capitals, small letterspaced mono labels, and one
cyanotype print pinned to the page. The print is the week, drawn as Argus' tail: one feather per day,
as long as the focus you kept, with the eye at its tip closed on a day you kept focus and open on a
day you did not.
"""

from __future__ import annotations

import math
from typing import Any
from xml.sax.saxutils import escape

NAVY = "#0b0c20"
ELECTRIC = "#2424ff"
PERIWINKLE = "#8f9bff"
WHITE = "#f3f3f6"
PAPER = "#f1eee6"
INK = "#12356b"
COBALT = "#2a5fa5"
TALL = ("'Avenir Next Condensed', 'DIN Condensed', 'Bahnschrift Condensed', 'Roboto Condensed', "
        "'Arial Narrow', Impact, sans-serif")
MONO = "'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace"

# The print: a sheet of paper, slightly turned, with a brushed field of blue on it.
SHEET = (640, 52, 500, 452)          # x, y, width, height
ORIGIN = (890, 446)                  # where the tail fans out from
TURN = -2.2

_DEFS = (
    "<defs>"
    '<pattern id="dots" width="6" height="6" patternUnits="userSpaceOnUse">'
    f'<circle cx="1" cy="1" r="0.7" fill="{WHITE}" fill-opacity="0.07"/></pattern>'
    # Horizontal brush streaks: the noise changes fast down the page and slowly across it.
    '<filter id="brush" x="-10%" y="-10%" width="120%" height="120%">'
    '<feTurbulence type="fractalNoise" baseFrequency="0.004 0.09" numOctaves="3" seed="11" result="streak"/>'
    '<feDisplacementMap in="SourceGraphic" in2="streak" scale="46" xChannelSelector="R" yChannelSelector="G" result="a"/>'
    '<feTurbulence type="fractalNoise" baseFrequency="0.05" numOctaves="2" seed="4" result="fine"/>'
    '<feDisplacementMap in="a" in2="fine" scale="10" xChannelSelector="G" yChannelSelector="R"/>'
    "</filter>"
    '<filter id="grain" x="0" y="0" width="100%" height="100%">'
    '<feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="3"/>'
    '<feColorMatrix type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 1.1 -0.52"/>'
    "</filter>"
    '<filter id="paper" x="0" y="0" width="100%" height="100%">'
    '<feTurbulence type="fractalNoise" baseFrequency="0.7" numOctaves="3" seed="9"/>'
    '<feColorMatrix type="matrix" values="0 0 0 0 0.35  0 0 0 0 0.33  0 0 0 0 0.3  0 0 0 0.55 -0.25"/>'
    "</filter>"
    '<filter id="wash" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="40"/></filter>'
    '<filter id="glow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="5"/></filter>'
    '<filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="0.6"/></filter>'
    '<filter id="lift" x="-10%" y="-10%" width="120%" height="125%">'
    '<feDropShadow dx="0" dy="14" stdDeviation="16" flood-color="#000" flood-opacity="0.55"/></filter>'
    f'<linearGradient id="blue" x1="0" y1="0" x2="1" y2="1">'
    f'<stop offset="0" stop-color="{COBALT}"/><stop offset="1" stop-color="{INK}"/></linearGradient>'
    f'<mask id="field"><rect x="{SHEET[0] + 30}" y="{SHEET[1] + 30}" width="{SHEET[2] - 60}" '
    f'height="{SHEET[3] - 60}" fill="#fff" filter="url(#brush)"/></mask>'
    "</defs>"
)


def _fmt_minutes(minutes: int) -> str:
    minutes = max(0, int(minutes))
    if minutes < 60:
        return f"{minutes} MIN"
    hours, rest = divmod(minutes, 60)
    return f"{hours}H {rest}M" if rest else f"{hours}H"


def _tall(x: int, y: int, body: Any, *, size: int, fill: str = WHITE, fit: bool = False) -> str:
    """Tall condensed capitals. ``fit`` pins the width so the layout holds with any fallback font."""
    body = str(body)
    extra = ""
    if fit:
        width = round(size * (0.37 * sum(1 for ch in body if ch != " ") + 0.17 * body.count(" ")))
        extra = f' textLength="{width}" lengthAdjust="spacingAndGlyphs"'
    return (f'<text x="{x}" y="{y}" font-family="{TALL}" font-size="{size}" font-weight="500" '
            f'fill="{fill}"{extra}>{escape(body)}</text>')


def _mono(x: float, y: float, body: Any, *, size: int = 13, fill: str = WHITE, anchor: str = "start",
          spacing: float = 3, opacity: float = 1) -> str:
    return (f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="{size}" letter-spacing="{spacing}" '
            f'fill="{fill}" fill-opacity="{opacity}" text-anchor="{anchor}">{escape(str(body).upper())}</text>')


def _tail(days: list[dict[str, Any]]) -> str:
    """Argus' tail: hairlines bursting from one point, and one feather per day with an eye at its tip."""
    ox, oy = ORIGIN
    out: list[str] = []
    # The burst of hairlines behind the feathers.
    for index in range(57):
        deg = -84 + index * 3
        length = (128, 190, 100, 160)[index % 4]
        rad = math.radians(deg)
        out.append(f'<line x1="{ox + 34 * math.sin(rad):.1f}" y1="{oy - 34 * math.cos(rad):.1f}" '
                   f'x2="{ox + length * math.sin(rad):.1f}" y2="{oy - length * math.cos(rad):.1f}" '
                   f'stroke="{WHITE}" stroke-opacity="0.17" stroke-width="1"/>')
    peak = max([int(day.get("focus_minutes", 0)) for day in days] + [1])
    count = max(1, len(days))
    for index, day in enumerate(days):
        value = int(day.get("focus_minutes", 0))
        deg = (index - (count - 1) / 2) * 15
        rad = math.radians(deg)
        sin, cos = math.sin(rad), math.cos(rad)
        length = 112 + round(113 * value / peak) if value else 92
        tx, ty = ox + length * sin, oy - length * cos
        is_today = index == count - 1
        strength = 0.95 if is_today else 0.7
        out.append(f'<line x1="{ox + 34 * sin:.1f}" y1="{oy - 34 * cos:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" '
                   f'stroke="{WHITE}" stroke-opacity="{strength}" stroke-width="2.2" stroke-linecap="round"/>')
        # Barbs down both sides of the shaft.
        step = 46
        while step < length - 24:
            px, py = ox + step * sin, oy - step * cos
            for side in (-1, 1):
                barb = math.radians(deg + side * 34)
                out.append(f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{px + 13 * math.sin(barb):.1f}" '
                           f'y2="{py - 13 * math.cos(barb):.1f}" stroke="{WHITE}" '
                           f'stroke-opacity="{strength * 0.55:.2f}" stroke-width="1"/>')
            step += 11
        # The eye at the tip: exposed white, with a lid or a pupil printed in blue.
        out.append(f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="19" fill="{WHITE}" fill-opacity="0.5" filter="url(#glow)"/>')
        out.append(f'<ellipse cx="{tx:.1f}" cy="{ty:.1f}" rx="15" ry="13" fill="{WHITE}" filter="url(#soft)"/>')
        if value:
            lashes = "".join(
                f'<line x1="{tx + dx:.1f}" y1="{ty + 3.5 - abs(dx) / 5:.1f}" x2="{tx + dx * 1.3:.1f}" '
                f'y2="{ty + 8.5 - abs(dx) / 5:.1f}"/>' for dx in (-7, -2.5, 2.5, 7))
            out.append(f'<g fill="none" stroke="{INK}" stroke-width="1.9" stroke-linecap="round">'
                       f'<path d="M {tx - 10:.1f} {ty - 1:.1f} Q {tx:.1f} {ty + 7:.1f} {tx + 10:.1f} {ty - 1:.1f}"/>'
                       f"{lashes}</g>")
        else:
            out.append(f'<ellipse cx="{tx:.1f}" cy="{ty:.1f}" rx="9.5" ry="6.5" fill="none" stroke="{INK}" stroke-width="1.8"/>'
                       f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="3.2" fill="{INK}"/>')
        lx, ly = ox + (length + 31) * sin, oy - (length + 31) * cos
        out.append(_mono(round(lx, 1), round(ly + 4, 1), str(day.get("label", ""))[:3], size=11, anchor="middle",
                         spacing=1.5, opacity=1 if is_today else 0.75))
    # Argus himself, small, asleep at the root of the tail.
    out.append(
        f'<circle cx="{ox}" cy="{oy - 4}" r="42" fill="{WHITE}" fill-opacity="0.35" filter="url(#glow)"/>'
        f'<ellipse cx="{ox}" cy="{oy - 2}" rx="30" ry="31" fill="{WHITE}" filter="url(#soft)"/>'
        f'<g fill="none" stroke="{INK}" stroke-width="2" stroke-linecap="round">'
        f'<path d="M {ox - 17} {oy - 9} Q {ox - 11} {oy - 3} {ox - 5} {oy - 9}"/>'
        f'<path d="M {ox + 5} {oy - 9} Q {ox + 11} {oy - 3} {ox + 17} {oy - 9}"/></g>'
        f'<path d="M {ox - 4.5} {oy - 1} L {ox + 4.5} {oy - 1} L {ox} {oy + 6} Z" fill="{INK}"/>'
        f'<g stroke="{WHITE}" stroke-width="1.6" stroke-linecap="round">'
        f'<path d="M {ox} {oy - 32} L {ox} {oy - 44} M {ox} {oy - 32} L {ox - 8} {oy - 42} M {ox} {oy - 32} L {ox + 8} {oy - 42}"/></g>'
        f'<circle cx="{ox}" cy="{oy - 45}" r="2.2" fill="{WHITE}"/><circle cx="{ox - 8.5}" cy="{oy - 43}" r="2.2" fill="{WHITE}"/>'
        f'<circle cx="{ox + 8.5}" cy="{oy - 43}" r="2.2" fill="{WHITE}"/>'
    )
    return "".join(out)


def _marks(x: int, y: int, w: int, h: int) -> str:
    """Printer's corner marks around a box."""
    out = []
    for cx, cy, dx, dy in ((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
        out.append(f'<path d="M {cx} {cy + dy * 16} L {cx} {cy} L {cx + dx * 16} {cy}" fill="none" '
                   f'stroke="{PERIWINKLE}" stroke-opacity="0.7" stroke-width="1"/>')
    return "".join(out)


def receipt_svg(data: dict[str, Any]) -> str:
    """Draw the card from ``Kairos.card_data()``."""
    totals = data.get("totals", {})
    days = list(data.get("days", []))[-7:]
    minutes = int(totals.get("focus_minutes", 0))
    blocks = int(totals.get("blocks_ended", 0))
    sx, sy, sw, sh = SHEET
    kept = sum(1 for day in days if int(day.get("focus_minutes", 0)))
    parts: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 600" width="1200" height="600" '
        'role="img" aria-label="Kairos receipt">',
        _DEFS,
        f'<rect width="1200" height="600" fill="{NAVY}"/>',
        '<rect width="1200" height="600" fill="url(#dots)"/>',
        f'<ellipse cx="880" cy="300" rx="330" ry="250" fill="{ELECTRIC}" opacity="0.2" filter="url(#wash)"/>',
        f'<rect x="9" y="9" width="1182" height="582" rx="12" fill="none" stroke="{ELECTRIC}" stroke-width="2"/>',

        # Left: the label row, the total, the three counters, the two tags.
        _mono(64, 86, "Kairos", size=14, spacing=5),
        _mono(170, 86, "ΚΑΙΡΟΣ", size=14, spacing=5, fill=PERIWINKLE),
        _mono(588, 86, "time given back", size=12, anchor="end", fill=PERIWINKLE),
        f'<line x1="64" y1="106.5" x2="588" y2="106.5" stroke="{ELECTRIC}" stroke-width="1"/>',
        _tall(58, 318, _fmt_minutes(minutes), size=226, fit=True),
        _mono(64, 362, "of focus kept from interruptions", size=14),
        f'<line x1="64" y1="392.5" x2="588" y2="392.5" stroke="{WHITE}" stroke-opacity="0.16" stroke-width="1"/>',
    ]

    stats = [
        (int(totals.get("questions_parked", 0)), "questions parked"),
        (int(totals.get("questions_batched", 0)), "handed back"),
        (int(totals.get("requests_queued", 0)), "left for morning"),
    ]
    for index, (value, label) in enumerate(stats):
        x = 64 + index * 180
        parts.append(_tall(x, 466, value, size=70))
        parts.append(_mono(x, 490, label, size=11, spacing=2, fill=PERIWINKLE))

    parts.append(f'<rect x="64" y="518" width="212" height="38" fill="{ELECTRIC}"/>')
    parts.append(_mono(170, 542, "Hermes Agent plugin", size=11, spacing=2, anchor="middle"))
    parts.append(f'<rect x="288.5" y="518.5" width="189" height="37" fill="none" stroke="{WHITE}" stroke-opacity="0.55"/>')
    parts.append(_mono(383, 542, f"{blocks} focus block{'s' if blocks != 1 else ''}", size=11, spacing=2, anchor="middle"))

    # Right: the cyanotype print, pinned a little crooked.
    cx, cy = sx + sw / 2, sy + sh / 2
    parts.append(f'<g transform="rotate({TURN} {cx} {cy})">')
    parts.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" fill="{PAPER}" filter="url(#lift)"/>')
    parts.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" filter="url(#paper)" opacity="0.5"/>')
    parts.append(
        '<g mask="url(#field)">'
        f'<rect x="{sx - 40}" y="{sy - 40}" width="{sw + 80}" height="{sh + 80}" fill="url(#blue)"/>'
        f'<ellipse cx="{ORIGIN[0]}" cy="{ORIGIN[1] - 150}" rx="170" ry="130" fill="{WHITE}" opacity="0.13" filter="url(#wash)"/>'
        f'<ellipse cx="{sx + sw - 60}" cy="{sy + sh - 70}" rx="120" ry="100" fill="#061a3a" opacity="0.4" filter="url(#wash)"/>'
        + _tail(days)
        + _mono(sx + 62, sy + 78, "the last seven days", size=11, spacing=2.5, opacity=0.85) +
        f'<rect x="{sx - 40}" y="{sy - 40}" width="{sw + 80}" height="{sh + 80}" filter="url(#grain)" opacity="0.5"/>'
        "</g>"
    )
    parts.append("</g>")
    parts.append(_marks(sx - 22, sy - 20, sw + 44, sh + 40))
    parts.append(_mono(sx - 4, 556, f"Plate {kept:02d}/07  ·  Argus, asleep", size=11, spacing=2, fill=PERIWINKLE))
    parts.append(_mono(sx + sw + 4, 556, str(data.get("date", "")), size=11, spacing=2, anchor="end", opacity=0.8))
    parts.append("</svg>")
    return "".join(parts)
