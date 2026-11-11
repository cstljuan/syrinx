"""Wiring tests: the runtime against a fake Hermes plugin context. No Hermes needed."""

from __future__ import annotations

import importlib
import json
import os
import sys
import types
from datetime import datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT = os.path.dirname(ROOT)
sys.path.insert(0, PARENT)

syrinx_pkg = importlib.import_module(os.path.basename(ROOT))
runtime = importlib.import_module(f"{os.path.basename(ROOT)}.runtime")
core = importlib.import_module(f"{os.path.basename(ROOT)}.core")


class FakeState:
    def __init__(self) -> None:
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class FakeHandle:
    def __init__(self, text):
        self.ok = True
        self.texts = [text]

    def edit(self, text):
        self.texts.append(text)
        return {"ok": True, "edited": True}


class FakeCtx:
    def __init__(self) -> None:
        self.state = FakeState()
        self.tools = {}
        self.hooks = {}
        self.commands = {}
        self.posted = []
        self.llm = None
        self.cron = None
        self.config = {}

    def current_cron_execution(self):
        # A method, exactly as Hermes exposes it: None unless a cron run is executing.
        return self.cron

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = handler

    def register_hook(self, name, callback, **kwargs):
        self.hooks[name] = callback

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = handler

    def post_message(self, text):
        handle = FakeHandle(text)
        self.posted.append(handle)
        return handle


@pytest.fixture
def rt():
    ctx = FakeCtx()
    rt = syrinx_pkg.register(ctx)
    clock = {"t": datetime.fromisoformat("2026-11-10 15:00")}
    rt.k._now = lambda: clock["t"]
    return rt, ctx, clock


def test_registration_matches_manifest(rt):
    _, ctx, _ = rt
    assert set(ctx.tools) == {"syrinx_park", "syrinx_interrupt", "syrinx_status"}
    assert set(ctx.hooks) == {"pre_tool_call", "post_tool_call", "pre_llm_call", "post_llm_call",
                              "on_human_input_request", "on_human_input_resolved"}
    assert set(ctx.commands) == {"flow", "catchup", "late", "night", "syrinx"}


def test_focus_flow_end_to_end(rt):
    r, ctx, clock = rt
    reply = ctx.commands["flow"]("30", session_id="s1")
    assert "Focus until 3:30 PM" in reply
    assert ctx.posted and ctx.posted[0].texts[0].startswith("Syrinx · focus")

    # The agent tries to ask: parked, not shown.
    directive = ctx.hooks["pre_tool_call"](tool_name="clarify", args={"questions": [{"question": "Ship it?"}]},
                                          task_id="s1", session_id="s1")
    assert directive["action"] == "block"
    assert ctx.hooks["pre_tool_call"](tool_name="terminal", args={"command": "ls"}, task_id="s1") is None

    # Context during the block tells the agent how to behave.
    ctx_text = ctx.hooks["pre_llm_call"](session_id="s1", user_message="hi", is_first_turn=False, platform="cli")
    assert "focus block" in ctx_text["context"]

    # The status line is edited in place, not re-posted.
    ctx.hooks["post_llm_call"](session_id="s1", assistant_response="done with step 1")
    assert len(ctx.posted) == 1 and len(ctx.posted[0].texts) == 2

    # Back: the first turn carries the catch-up and the one-card hand-back.
    clock["t"] = datetime.fromisoformat("2026-11-10 15:31")
    back = ctx.hooks["pre_llm_call"](session_id="s1", user_message="back", is_first_turn=False, platform="cli")
    assert "ONE clarify call" in back["context"] and "Ship it?" in back["context"]
    assert ctx.hooks["pre_llm_call"](session_id="s1", user_message="next", is_first_turn=False, platform="cli") is None


def test_tools_return_json(rt):
    r, ctx, _ = rt
    ctx.commands["flow"]("45", session_id="s1")
    # Hermes calls a tool as handler(args_dict, **context).
    parked = json.loads(ctx.tools["syrinx_park"]({"question": "Which color?", "default": "blue", "why": "brand"},
                                                 task_id="s1"))
    assert parked["parked"].startswith("q-") and parked["proceed_with"] == "blue"
    assert r.k.parked_open()[0]["question"] == "Which color?"
    status = json.loads(ctx.tools["syrinx_status"]({}, task_id="s1"))
    assert status["focus_active"] and status["parked"] == 1
    ok = json.loads(ctx.tools["syrinx_interrupt"]({"question": "Pay?", "why": "money"}, task_id="s1"))
    assert ok["ok"]
    # Plain keywords still work.
    assert json.loads(ctx.tools["syrinx_park"](question="Old style?", default="yes"))["proceed_with"] == "yes"
    assert ctx.hooks["pre_tool_call"](tool_name="clarify", args={"questions": [{"question": "Pay?"}]},
                                      task_id="s1", session_id="s1") is None
    assert "question is required" in ctx.tools["syrinx_park"]({"question": "", "default": "x"})


def test_night_blocks_and_morning_delivers(rt):
    r, ctx, clock = rt
    clock["t"] = datetime.fromisoformat("2026-11-10 23:05")
    blocked = ctx.hooks["pre_llm_call"](session_id="s1", user_message="refactor auth", is_first_turn=True, platform="cli")
    assert blocked["action"] == "block" and "11:05 PM" in blocked["message"]
    assert ctx.hooks["pre_llm_call"](session_id="s1", user_message="/late", is_first_turn=False, platform="cli") is None
    late = ctx.commands["late"]("15")
    assert "11:20 PM" in late
    # /late hands the queued request straight back, with late wording.
    back = ctx.hooks["pre_llm_call"](session_id="s1", user_message="go on", is_first_turn=False, platform="cli")
    assert "chose /late" in back["context"] and "refactor auth" in back["context"]
    assert ctx.hooks["pre_llm_call"](session_id="s1", user_message="more", is_first_turn=False, platform="cli") is None
    # A request queued and left alone arrives in the morning with the morning wording.
    clock["t"] = datetime.fromisoformat("2026-11-10 23:40")
    assert ctx.hooks["pre_llm_call"](session_id="s1", user_message="one more thing", platform="cli")["action"] == "block"
    clock["t"] = datetime.fromisoformat("2026-11-11 08:30")
    morning = ctx.hooks["pre_llm_call"](session_id="s1", user_message="morning", is_first_turn=True, platform="cli")
    assert "morning brief" in morning["context"] and "one more thing" in morning["context"]


def test_pane_answers_reach_the_agent_next_turn(rt):
    r, ctx, _ = rt
    item = r.k.park("Which port?", "8080", session_id="s1")
    r.k.answer(item["id"], "9090")
    turn = ctx.hooks["pre_llm_call"](session_id="s1", user_message="hey", platform="cli")
    assert "Syrinx pane" in turn["context"] and "9090" in turn["context"]
    assert ctx.hooks["pre_llm_call"](session_id="s1", user_message="hey", platform="cli") is None


def test_auto_focus_opens_and_closes_from_presence(rt, monkeypatch):
    r, ctx, clock = rt
    import importlib
    presence = importlib.import_module(f"{os.path.basename(ROOT)}.presence")
    monkeypatch.setattr(presence.platform, "system", lambda: "Darwin")
    r.k.config["auto_focus"] = True
    state = {"front": "com.apple.Safari"}

    def run(cmd):
        if cmd[0] == "ioreg":
            return '"HIDIdleTime" = 2000000000'
        if cmd[:2] == ["lsappinfo", "front"]:
            return "ASN:1"
        return f'"CFBundleIdentifier"="{state["front"]}"'

    r._presence_run = run
    # Active in Safari: an automatic block opens.
    ctx.hooks["post_tool_call"](tool_name="read_file", args={"path": "a.py"}, task_id="s1")
    assert r.k.focus()["active"] and r.k.focus()["source"] == "auto"
    # Back in Hermes: it closes and the next turn carries the catch-up.
    state["front"] = "com.nousresearch.hermes"
    clock["t"] = clock["t"].replace(minute=5)
    turn = ctx.hooks["pre_llm_call"](session_id="s1", user_message="back", platform="desktop")
    assert not r.k.focus()["active"]
    assert "back from a focus block" in turn["context"]


def test_auto_focus_is_off_by_default(rt):
    r, ctx, _ = rt
    r._presence_run = lambda cmd: (_ for _ in ()).throw(RuntimeError("must not run"))
    ctx.hooks["post_tool_call"](tool_name="read_file", args={"path": "a.py"}, task_id="s1")
    assert not r.k.focus().get("active")


def test_cron_turns_are_never_blocked(rt):
    r, ctx, clock = rt
    clock["t"] = datetime.fromisoformat("2026-11-10 23:05")
    ctx.cron = object()
    assert ctx.hooks["pre_llm_call"](session_id="cron", user_message="nightly job", is_first_turn=True, platform="cli") is None


def test_cron_guard_accepts_a_plain_value_too(rt):
    r, ctx, clock = rt
    clock["t"] = datetime.fromisoformat("2026-11-10 23:05")
    ctx.current_cron_execution = None          # an older host that exposes a value, not a method
    assert ctx.hooks["pre_llm_call"](session_id="s1", user_message="late idea", platform="cli")["action"] == "block"
    ctx.current_cron_execution = object()
    assert ctx.hooks["pre_llm_call"](session_id="s1", user_message="nightly job", platform="cli") is None


def test_hooks_never_raise(rt):
    r, ctx, _ = rt
    r.k.focus = lambda: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[assignment]
    assert ctx.hooks["pre_tool_call"](tool_name="clarify", args={}, task_id="s1") is None
    assert ctx.hooks["pre_llm_call"](session_id="s1", user_message="x") is None
    assert ctx.hooks["post_llm_call"](session_id="s1", assistant_response="x") is None
    assert ctx.hooks["on_human_input_request"](kind="approval", request_id="r") is None


def test_syrinx_toggles_and_week(rt, monkeypatch):
    r, ctx, _ = rt
    ctx.set_config = lambda key, value: ctx.config.__setitem__(key, value)
    assert "Night off" in ctx.commands["syrinx"]("night off")
    assert r.k.config["night_enabled"] is False and ctx.config["night_enabled"] is False
    import importlib
    presence = importlib.import_module(f"{os.path.basename(ROOT)}.presence")
    monkeypatch.setattr(presence.platform, "system", lambda: "Linux")
    assert "needs macOS" in ctx.commands["syrinx"]("auto on")
    monkeypatch.setattr(presence.platform, "system", lambda: "Darwin")
    assert "Auto-focus on" in ctx.commands["syrinx"]("auto on")
    assert "last 7 days" in ctx.commands["syrinx"]("week")


def test_syrinx_card_saves_one_file_in_the_plugin_folder(rt, tmp_path):
    r, ctx, _ = rt
    ctx.state.data_dir = tmp_path / "plugin-data" / "syrinx"
    reply = ctx.commands["syrinx"]("card")
    saved = ctx.state.data_dir / "syrinx-receipt.svg"
    assert saved.exists() and str(saved) in reply and "numbers only" in reply
    assert saved.read_text(encoding="utf-8").startswith("<svg")
    # No data folder (an older host): the command still answers with the text receipt.
    del ctx.state.data_dir
    assert "could not save" in ctx.commands["syrinx"]("card") and "Syrinx receipt" in ctx.commands["syrinx"]("card")


def test_syrinx_pet_goes_through_the_hermes_pet_store(rt, monkeypatch):
    r, ctx, _ = rt
    # No pet feature on this host: a plain sentence, never an exception.
    monkeypatch.setitem(sys.modules, "agent.pet.store", None)
    assert "could not add Argus" in ctx.commands["syrinx"]("pet")
    # With the store: one call, raw sheet bytes, the argus slug; nothing is selected for the user.
    calls = []
    store = types.ModuleType("agent.pet.store")
    store.register_local_pet = lambda sheet, **kw: calls.append((sheet, kw))
    for name in ("agent", "agent.pet"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "agent.pet.store", store)
    reply = ctx.commands["syrinx"]("pet")
    sheet = os.path.join(ROOT, "assets", "pet", "argus", "spritesheet.webp")
    if os.path.exists(sheet):
        assert "/pet argus" in reply and len(calls) == 1
        assert calls[0][0][:4] == b"RIFF" and calls[0][1]["slug"] == "argus"
    else:
        assert "no pet art" in reply


def test_commands_text(rt):
    r, ctx, _ = rt
    assert "Syrinx commands" in ctx.commands["syrinx"]("help")
    assert "Night set: cutoff 11:00 PM" in ctx.commands["night"]("23:00 07:00")
    assert "Use /night" in ctx.commands["night"]("99:99")
    assert "No focus block" in ctx.commands["flow"]("off", session_id="s1")
    assert "Syrinx receipt" in ctx.commands["syrinx"]("receipt")
    assert "No questions were parked" in ctx.commands["catchup"]("", session_id="s1")
