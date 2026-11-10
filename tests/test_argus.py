"""Argus: the pose rules and the art lookup."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argus  # noqa: E402


def snap(parked=0, flow=False, night=False, late=False):
    return {"parked": [{}] * parked, "focus": {"active": flow}, "night": {"is_night": night, "late_active": late}}


def test_pose_follows_the_state():
    assert argus.pose_for(snap())["pose"] == "idle"
    assert argus.pose_for(snap(flow=True))["pose"] == "shush"
    guard = argus.pose_for(snap(flow=True, parked=2))
    assert guard["pose"] == "guard" and "2 questions" in guard["line"]
    letter = argus.pose_for(snap(parked=1))
    assert letter["pose"] == "letter" and "1 question waiting" in letter["line"]
    assert argus.pose_for(snap(night=True, parked=3))["pose"] == "sleep"
    assert argus.pose_for(snap(late=True))["pose"] == "yawn"
    assert argus.pose_for({})["pose"] == "idle"


def test_every_pose_the_rules_can_pick_has_art():
    names = argus.pose_names()
    if not names:          # a checkout without the art still works: the pane draws Argus itself
        return
    for wanted in ("idle", "shush", "guard", "letter", "sleep", "yawn"):
        assert wanted in names
        assert argus.pose_data_uri(wanted).startswith("data:image/webp;base64,")


def test_unknown_or_hostile_names_never_read_a_file():
    assert argus.pose_data_uri("nope") is None
    assert argus.pose_data_uri("../card-plate") is None
    assert argus.pose_data_uri("../../plugin.yaml") is None
