"""Syrinx backend routes for the Desktop pane: ``/api/plugins/syrinx/...``.

Runs inside the gateway process behind the dashboard's auth gate. It reads and writes the same
profile-scoped plugin state the agent-side hooks use, so a button in the pane and a slash command in
the chat are the same action. No network, no shell, no model calls.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

_PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"syrinx_{name}_for_api", _PLUGIN_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


_core = _load("core")
_card = _load("card")
_argus = _load("argus")


def _settings() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly  # type: ignore

        config = load_config_readonly() or {}
        entries = ((config.get("plugins") or {}).get("entries") or {})
        settings = (entries.get("syrinx") or {}).get("settings") or {}
        return dict(settings) if isinstance(settings, dict) else {}
    except Exception:
        logger.debug("syrinx api: settings unavailable, using defaults", exc_info=True)
        return {}


def _syrinx():
    from hermes_cli.plugins_state import PluginState  # type: ignore

    return _core.Syrinx(PluginState("syrinx", ""), config=_settings())


def _broadcast(kind: str, line: str) -> None:
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event  # type: ignore

        broadcast_plugin_event("syrinx", "state.changed", {"kind": kind, "line": line})
    except Exception:
        logger.debug("syrinx api: broadcast skipped", exc_info=True)


def _snapshot(k) -> dict[str, Any]:
    try:
        if k.schedule_tick():          # the pane polls, so deep-work hours start on time even when idle
            _broadcast("flow_on", k.status_line())
    except Exception:
        logger.debug("syrinx api: schedule tick failed", exc_info=True)
    snap = k.snapshot()
    snap["argus"] = _argus.pose_for(snap)
    return snap


@router.get("/state")
def state() -> dict[str, Any]:
    return _snapshot(_syrinx())


@router.get("/argus/{name}")
def argus_pose(name: str) -> dict[str, Any]:
    """One pose of the mascot as a data URI. Unknown names get an empty answer, never a file read."""
    return {"name": name, "src": _argus.pose_data_uri(name)}


@router.post("/flow")
def flow(body: dict) -> dict[str, Any]:
    k = _syrinx()
    minutes = body.get("minutes") if isinstance(body, dict) else None
    try:
        minutes = int(minutes) if minutes is not None else None
    except (TypeError, ValueError):
        minutes = None
    k.start_focus(minutes, source="pane")
    _broadcast("flow_on", k.status_line())
    return _snapshot(k)


@router.post("/flow/end")
def flow_end() -> dict[str, Any]:
    k = _syrinx()
    k.end_focus("pane")
    _broadcast("flow_off", k.status_line())
    return _snapshot(k)


@router.post("/late")
def late(body: dict) -> dict[str, Any]:
    k = _syrinx()
    minutes = body.get("minutes") if isinstance(body, dict) else None
    try:
        minutes = int(minutes) if minutes is not None else None
    except (TypeError, ValueError):
        minutes = None
    k.late(minutes)
    _broadcast("late", k.status_line())
    return _snapshot(k)


@router.post("/answer")
def answer(body: dict) -> dict[str, Any]:
    k = _syrinx()
    item_id = str((body or {}).get("id") or "")
    text = str((body or {}).get("answer") or "")
    item = k.answer(item_id, text)
    _broadcast("answered", k.status_line())
    return {"ok": item is not None, "snapshot": _snapshot(k)}


@router.post("/night")
def night(body: dict) -> dict[str, Any]:
    k = _syrinx()
    try:
        k.set_night_times((body or {}).get("cutoff"), (body or {}).get("wake"))
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "snapshot": _snapshot(k)}
    _broadcast("night", k.status_line())
    return {"ok": True, "snapshot": _snapshot(k)}


@router.get("/catchup")
def catchup() -> dict[str, Any]:
    k = _syrinx()
    return {"text": k.catchup_text("*")}


@router.get("/card")
def card() -> dict[str, Any]:
    """The shareable receipt card as SVG text. Numbers only."""
    return {"svg": _card.receipt_svg(_syrinx().card_data())}


@router.post("/always")
def always(body: dict) -> dict[str, Any]:
    """Make a standing answer: from a parked question (``id``), a suggestion (``suggestion``), or free text."""
    k = _syrinx()
    body = body if isinstance(body, dict) else {}
    if body.get("id"):
        item = k.always_from_parked(str(body["id"]))
    elif body.get("suggestion"):
        item = k.accept_suggestion(str(body["suggestion"]))
    else:
        item = k.add_standing(str(body.get("question") or ""), str(body.get("answer") or ""))
    _broadcast("standing", k.status_line())
    return {"ok": item is not None, "snapshot": _snapshot(k)}


@router.post("/always/forget")
def always_forget(body: dict) -> dict[str, Any]:
    k = _syrinx()
    item = k.forget_standing(str((body or {}).get("id") or ""))
    _broadcast("standing", k.status_line())
    return {"ok": item is not None, "snapshot": _snapshot(k)}

