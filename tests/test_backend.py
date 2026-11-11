"""The Desktop backend routes, exercised with FastAPI and Hermes stubbed out.

Every route is called at least once, so a renamed helper or a missing name fails here and not in
someone's Desktop app.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import core  # noqa: E402


@pytest.fixture
def api(monkeypatch):
    fastapi = types.ModuleType("fastapi")

    class APIRouter:
        def get(self, *args, **kwargs):
            return lambda fn: fn

        post = get

    fastapi.APIRouter = APIRouter
    store = core.MemoryStore()
    state = types.ModuleType("hermes_cli.plugins_state")
    state.PluginState = lambda *args: store
    config = types.ModuleType("hermes_cli.config")
    config.load_config_readonly = lambda: {}
    for name, module in (("fastapi", fastapi), ("hermes_cli", types.ModuleType("hermes_cli")),
                         ("hermes_cli.plugins_state", state), ("hermes_cli.config", config)):
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("syrinx_api_under_test", os.path.join(ROOT, "dashboard", "plugin_api.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_route_answers(api):
    snap = api.state()
    assert {"focus", "night", "parked", "standing", "suggested", "week", "argus", "windows", "budget"} <= set(snap)
    assert api.flow({"minutes": 25})["focus"]["active"] is True
    item = api._syrinx().park("Which port?", "8080")
    assert api.always({"id": item["id"]})["ok"] is True
    assert api.always({"question": "tabs or spaces", "answer": "spaces"})["ok"] is True
    assert api.always({"question": "", "answer": ""})["ok"] is False
    standing = api.state()["standing"]
    assert len(standing) == 2 and api.always_forget({"id": standing[0]["id"]})["ok"] is True
    assert api.answer({"id": item["id"], "answer": "9090"})["ok"] is True
    assert api.answer({"id": "nope", "answer": "x"})["ok"] is False
    assert api.flow_end()["focus"]["active"] is False
    assert "focus" in api.late({"minutes": 5})
    assert api.night({"cutoff": "23:00", "wake": "07:00"})["ok"] is True
    assert api.night({"cutoff": "99:00"})["ok"] is False
    assert "text" in api.catchup()
    assert api.card()["svg"].startswith("<svg")
    assert api.argus_pose("../plugin")["src"] is None


def test_deep_work_hours_start_from_the_pane_poll(api):
    k = api._syrinx()
    now = k.now()
    start = now.replace(second=0, microsecond=0)
    if start.hour >= 23:                 # too close to midnight for a same-day window
        return
    days = "weekdays" if now.weekday() < 5 else "weekends"
    k.add_window(days, start.strftime("%H:%M"), f"{start.hour + 1:02d}:{start.minute:02d}")
    snap = api.state()
    assert snap["focus"]["active"] is True and snap["focus"]["source"] == "schedule"
