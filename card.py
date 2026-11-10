"""The Kairos receipt card: one 1200x600 SVG, drawn with nothing but the standard library.

It carries numbers only: minutes of focus, counts, seven daily bars. No question text, no file names,
no session ids, so it is safe to post.

The look is a cyanotype print, the blue-and-white sun print the Hermes catalog art uses: white paper,
one hand-brushed field of Prussian blue, and the week exposed in it as white bars. Above each bar sits
one of Argus' eyes: closed on a day you kept focus, open on a day you did not.
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

PAPER = "#f4f1ea"
INK = "#12356b"
COBALT = "#2a5fa5"
SOFT_INK = "#5b7499"
WHITE = "#fbfaf6"
SERIF = "'Iowan Old Style', 'Palatino Linotype', Palatino, 'Book Antiqua', Georgia, serif"

_DEFS = (
    "<defs>"
    # Horizontal brush streaks: the noise changes fast down the page and slowly across it.
    '<filter id="brush" x="-10%" y="-10%" width="120%" height="120%">'
    '<feTurbulence type="fractalNoise" baseFrequency="0.003 0.09" numOctaves="3" seed="11" result="streak"/>'
    '<feDisplacementMap in="SourceGraphic" in2="streak" scale="70" xChannelSelector="R" yChannelSelector="G" result="a"/>'
    '<feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="2" seed="4" result="fine"/>'
    '<feDisplacementMap in="a" in2="fine" scale="14" xChannelSelector="G" yChannelSelector="R"/>'
    "</filter>"
    '<filter id="grain" x="0" y="0" width="100%" height="100%">'
    '<feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="3"/>'
    '<feColorMatrix type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 1.1 -0.52"/>'
    "</filter>"
    '<filter id="paper" x="0" y="0" width="100%" height="100%">'
    '<feTurbulence type="fractalNoise" baseFrequency="0.7" numOctaves="3" seed="9"/>'
    '<feColorMatrix type="matrix" values="0 0 0 0 0.35  0 0 0 0 0.33  0 0 0 0 0.3  0 0 0 0.55 -0.25"/>'
    "</filter>"
    '<filter id="wash" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="46"/></filter>'
    '<filter id="soft" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="0.7"/></filter>'
    f'<linearGradient id="blue" x1="0" y1="0" x2="1" y2="1">'
    f'<stop offset="0" stop-color="{COBALT}"/><stop offset="1" stop-color="{INK}"/></linearGradient>'
    '<mask id="field"><rect x="640" y="46" width="516" height="508" fill="#fff" filter="url(#brush)"/></mask>'
    "</defs>"
)


def _fmt_minutes(minutes: int) -> str:
    minutes = max(0, int(minutes))
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours}h {rest}m" if rest else f"{hours}h"


def _text(x: int, y: int, body: Any, *, size: int, fill: str, anchor: str = "start", weight: int = 400,
          italic: bool = False, spacing: float = 0, opacity: float = 1) -> str:
    extra = ' font-style="italic"' if italic else ""
    if spacing:
        extra += f' letter-spacing="{spacing}"'
    if opacity != 1:
        extra += f' fill-opacity="{opacity}"'
    return (f'<text x="{x}" y="{y}" font-family="{SERIF}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}"{extra}>{escape(str(body))}</text>')


def _eye(cx: int, cy: int, *, closed: bool) -> str:
    """One of Argus' eyes: a lid with lashes when asleep, a ring with a pupil when watching."""
    if closed:
        lashes = "".join(
            f'<line x1="{cx + dx}" y1="{cy + 4 - abs(dx) // 4}" x2="{cx + dx + dx // 3}" y2="{cy + 10 - abs(dx) // 4}"/>'
            for dx in (-9, -3, 3, 9))
        return (f'<g fill="none" stroke="{WHITE}" stroke-width="2" stroke-linecap="round">'
                f'<path d="M {cx - 13} {cy} Q {cx} {cy + 10} {cx + 13} {cy}"/>{lashes}</g>')
    return (f'<g fill="none" stroke="{WHITE}" stroke-width="2" stroke-opacity="0.75">'
            f'<ellipse cx="{cx}" cy="{cy + 3}" rx="12" ry="7"/></g>'
            f'<circle cx="{cx}" cy="{cy + 3}" r="3" fill="{WHITE}" fill-opacity="0.75"/>')


def receipt_svg(data: dict[str, Any]) -> str:
    """Draw the card from ``Kairos.card_data()``."""
    totals = data.get("totals", {})
    days = list(data.get("days", []))[-7:]
    minutes = int(totals.get("focus_minutes", 0))
    parts: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 600" width="1200" height="600" '
        'role="img" aria-label="Kairos receipt">',
        _DEFS,
        f'<rect width="1200" height="600" fill="{PAPER}"/>',
        '<rect width="1200" height="600" filter="url(#paper)" opacity="0.5"/>',
        # The brushed blue field, unevenly exposed, with grain.
        '<g mask="url(#field)">'
        '<rect x="560" y="0" width="640" height="600" fill="url(#blue)"/>'
        f'<ellipse cx="760" cy="150" rx="150" ry="90" fill="{WHITE}" opacity="0.16" filter="url(#wash)"/>'
        f'<ellipse cx="1080" cy="470" rx="140" ry="110" fill="#061a3a" opacity="0.35" filter="url(#wash)"/>'
        '<rect x="560" y="0" width="640" height="600" filter="url(#grain)" opacity="0.55"/>'
        "</g>",
        _text(72, 128, "KAIROS", size=58, fill=INK, spacing=16, weight=600),
        _text(74, 162, "the right moment, not just the fast one", size=20, fill=SOFT_INK, italic=True),
        _text(70, 326, _fmt_minutes(minutes), size=112, fill=INK, weight=600),
        _text(74, 368, "of focus kept from interruptions", size=24, fill=INK),
    ]

    stats = [
        (int(totals.get("questions_parked", 0)), "questions parked"),
        (int(totals.get("questions_batched", 0)), "handed back"),
        (int(totals.get("requests_queued", 0)), "left for morning"),
    ]
    for index, (value, label) in enumerate(stats):
        x = 74 + index * 176
        parts.append(_text(x, 470, value, size=46, fill=INK, weight=600))
        parts.append(_text(x, 498, label, size=16, fill=SOFT_INK, italic=True))

    # Seven daily bars, exposed white in the blue.
    left, base, top, width, gap = 716, 452, 190, 34, 22
    peak = max([int(day.get("focus_minutes", 0)) for day in days] + [1])
    parts.append(_text(left, 118, "the last seven days", size=18, fill=WHITE, italic=True, opacity=0.9))
    for index, day in enumerate(days):
        value = int(day.get("focus_minutes", 0))
        height = max(6, round((base - top) * value / peak)) if value else 0
        x = left + index * (width + gap)
        is_today = index == len(days) - 1
        if height:
            parts.append(f'<rect x="{x}" y="{base - height}" width="{width}" height="{height}" rx="2" '
                         f'fill="{WHITE}" fill-opacity="{0.96 if is_today else 0.6}" filter="url(#soft)"/>')
        else:
            parts.append(f'<rect x="{x}" y="{base - 2}" width="{width}" height="2" fill="{WHITE}" fill-opacity="0.45"/>')
        parts.append(_eye(x + width // 2, base - height - 26, closed=bool(value)))
        parts.append(_text(x + width // 2, base + 28, day.get("label", ""), size=16, fill=WHITE,
                           anchor="middle", opacity=1 if is_today else 0.75))
    parts.append(_text(left + 7 * (width + gap) - gap, 522, str(data.get("date", "")), size=15, fill=WHITE,
                       anchor="end", italic=True, opacity=0.8))

    blocks = int(totals.get("blocks_ended", 0))
    foot = f"{blocks} focus block{'s' if blocks != 1 else ''}  ·  Kairos, a Hermes Agent plugin"
    parts.append(_text(74, 552, foot, size=15, fill=SOFT_INK))
    parts.append("</svg>")
    return "".join(parts)
