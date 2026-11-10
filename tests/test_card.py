"""The receipt card: a valid SVG that carries numbers only."""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import card  # noqa: E402
import core  # noqa: E402


def make():
    clock = {"t": datetime.fromisoformat("2026-11-10 15:00")}
    return core.Kairos(core.MemoryStore(), now=lambda: clock["t"]), clock


def test_card_is_valid_svg_with_the_numbers():
    k, clock = make()
    k.start_focus(90)
    k.park("Rotate the SECRET-TOKEN in /Users/me/private/app.py?", "no", session_id="s1")
    clock["t"] += timedelta(minutes=91)
    k.focus()
    svg = card.receipt_svg(k.card_data())
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg") and root.attrib["viewBox"] == "0 0 1200 600"
    assert "1H 30M" in svg and "QUESTIONS PARKED" in svg
    # Numbers only: nothing the agent or the user wrote may reach the card.
    assert "SECRET-TOKEN" not in svg and "private" not in svg and "s1" not in svg


def test_card_data_has_seven_days_ending_today():
    k, _ = make()
    data = k.card_data()
    assert len(data["days"]) == 7 and data["days"][-1]["label"] == "Tue"
    assert data["date"] == "Nov 10, 2026"
    assert "days" not in data["totals"]
    assert len(k.snapshot()["week"]) == 7


def test_empty_card_still_renders():
    svg = card.receipt_svg({})
    assert ET.fromstring(svg) is not None and "0 MIN" in svg
