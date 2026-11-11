"""Argus, the mascot: which pose fits the moment, and the art for it.

Pure rules and file reads, no Hermes imports. The pane asks for a pose by name and gets the small
image back as a data URI, so no file path ever leaves the plugin folder.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

ART = Path(__file__).resolve().parent / "assets" / "argus"


@lru_cache(maxsize=1)
def pose_names() -> tuple[str, ...]:
    try:
        return tuple(sorted(path.stem for path in ART.glob("*.webp")))
    except OSError:
        return ()


@lru_cache(maxsize=None)
def pose_data_uri(name: str) -> Optional[str]:
    """The pose as a data URI, or None. Only names found in the art folder are ever read."""
    if name not in pose_names():
        return None
    try:
        raw = (ART / f"{name}.webp").read_bytes()
    except OSError:
        return None
    return "data:image/webp;base64," + base64.b64encode(raw).decode("ascii")


def pose_for(snapshot: dict[str, Any]) -> dict[str, str]:
    """Pick the pose and the line under it from a ``Syrinx.snapshot()``."""
    parked = len(snapshot.get("parked") or [])
    night = snapshot.get("night") or {}
    focus = snapshot.get("focus") or {}
    questions = "question" if parked == 1 else "questions"
    if night.get("is_night"):
        return {"pose": "sleep", "line": "Argus sleeps until morning."}
    if focus.get("active"):
        if parked:
            return {"pose": "guard", "line": f"Argus is keeping {parked} {questions} for you."}
        return {"pose": "shush", "line": "Every eye is shut. Nothing gets through."}
    if parked:
        return {"pose": "letter", "line": f"{parked} {questions} waiting. Say /catchup."}
    handed = int(snapshot.get("handed_back") or 0)
    if handed:
        word = "question is" if handed == 1 else "questions are"
        return {"pose": "waiting", "line": f"Your {handed} {word} on the card. Argus is listening."}
    if night.get("late_active"):
        return {"pose": "yawn", "line": "Up late. Argus is keeping you company."}
    return {"pose": "idle", "line": "Argus is watching. Start a flow and he will hold the questions."}
