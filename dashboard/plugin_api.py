"""Kairos backend routes for the Desktop pane: ``/api/plugins/kairos/...``.

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
    spec = importlib.util.spec_from_file_location(f"kairos_{name}_for_api", _PLUGIN_DIR / f"{name}.py")
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
        settings = (entries.get("kairos") or {}).get("settings") or {}
        return dict(settings) if isinstance(settings, dict) else {}
    except Exception:
        logger.debug("kairos api: settings unavailable, using defaults", exc_info=True)
        return {}


def _kairos():
    from hermes_cli.plugins_state import PluginState  # type: ignore

    return _core.Kairos(PluginState("kairos", ""), config=_settings())


def _broadcast(kind: str, line: str) -> None:
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event  # type: ignore

        broadcast_plugin_event("kairos", "state.changed", {"kind": kind, "line": line})
    except Exception:
        logger.debug("kairos api: broadcast skipped", exc_info=True)


def _snapshot(k) -> dict[str, Any]:
    snap = k.snapshot()
    snap["argus"] = _argus.pose_for(snap)
    return snap


@router.get("/state")
def state() -> dict[str, Any]:
    return _snapshot(_kairos())


@router.get("/argus/{name}")
def argus_pose(name: str) -> dict[str, Any]:
    """One pose of the mascot as a data URI. Unknown names get an empty answer, never a file read."""
    return {"name": name, "src": _argus.pose_data_uri(name)}


@router.post("/flow")
def flow(body: dict) -> dict[str, Any]:
    k = _kairos()
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
    k = _kairos()
    k.end_focus("pane")
    _broadcast("flow_off", k.status_line())
    return _snapshot(k)


@router.post("/late")
def late(body: dict) -> dict[str, Any]:
    k = _kairos()
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
    k = _kairos()
    item_id = str((body or {}).get("id") or "")
    text = str((body or {}).get("answer") or "")
    item = k.answer(item_id, text)
    _broadcast("answered", k.status_line())
    return {"ok": item is not None, "snapshot": _snapshot(k)}


@router.post("/night")
def night(body: dict) -> dict[str, Any]:
    k = _kairos()
    try:
        k.set_night_times((body or {}).get("cutoff"), (body or {}).get("wake"))
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "snapshot": _snapshot(k)}
    _broadcast("night", k.status_line())
    return {"ok": True, "snapshot": _snapshot(k)}


@router.get("/catchup")
def catchup() -> dict[str, Any]:
    k = _kairos()
    return {"text": k.catchup_text("*")}


@router.get("/card")
def card() -> dict[str, Any]:
    """The shareable receipt card as SVG text. Numbers only."""
    return {"svg": _card.receipt_svg(_kairos().card_data())}
