"""The receipt card: a valid SVG that carries numbers only."""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import card  # noqa: E402
import core  # noqa: E402


def make():
    clock = {"t": datetime.fromisoformat("2026-11-10 15:00")}
    return core.Syrinx(core.MemoryStore(), now=lambda: clock["t"]), clock


def test_card_is_valid_svg_with_the_numbers():
    k, clock = make()
    k.start_focus(90)
    k.park("Rotate the SECRET-TOKEN in /Users/me/private/app.py?", "no", session_id="s1")
    clock["t"] += timedelta(minutes=91)
    k.focus()
    svg = card.receipt_svg(k.card_data())
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg") and root.attrib["viewBox"] == "0 0 1200 600"
    assert "1h 30m of focus kept" in svg and "questions parked" in svg
    # Numbers only: nothing the agent or the user wrote may reach the card. The embedded art is
    # base64 and can contain any short letter run by chance, so it is set aside before checking.
    drawn = re.sub(r'href="data:[^"]*"', "", svg)
    assert "SECRET-TOKEN" not in drawn and "private" not in drawn and "s1" not in drawn


def test_card_data_has_seven_days_ending_today():
    k, _ = make()
    data = k.card_data()
    assert len(data["days"]) == 7 and data["days"][-1]["label"] == "Tue"
    assert data["date"] == "Nov 10, 2026"
    assert "days" not in data["totals"]
    assert len(k.snapshot()["week"]) == 7


def test_empty_card_still_renders():
    svg = card.receipt_svg({})
    assert ET.fromstring(svg) is not None and "0m of focus kept" in svg


def test_card_uses_painted_art_when_assets_are_present():
    k, clock = make()
    k.start_focus(75)
    clock["t"] += timedelta(minutes=76)
    k.focus()
    svg = card.receipt_svg(k.card_data())
    assert ET.fromstring(svg) is not None
    if (card.ASSETS / "card-plate.jpg").exists():
        assert "data:image/jpeg;base64," in svg
    if card._have_numerals():
        # 1h 15m: both ones, the five, the h and the m are placed from the painted set.
        assert svg.count('<use href="#n1"') == 2 and '<use href="#n5"' in svg and '<use href="#nh"' in svg
    assert len(svg) < 600_000


def test_card_falls_back_to_lettering_without_assets(monkeypatch, tmp_path):
    monkeypatch.setattr(card, "ASSETS", tmp_path)
    card._data_uri.cache_clear()
    card._png_size.cache_clear()
    try:
        svg = card.receipt_svg({"totals": {"focus_minutes": 90}, "days": []})
        assert ET.fromstring(svg) is not None and "base64" not in svg and ">1h 30m<" in svg
    finally:
        card._data_uri.cache_clear()
        card._png_size.cache_clear()

