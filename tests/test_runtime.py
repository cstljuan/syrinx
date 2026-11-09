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

kairos_pkg = importlib.import_module(os.path.basename(ROOT))
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
        self.current_cron_execution = None
        self.config = {}

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
    rt = kairos_pkg.register(ctx)
    clock = {"t": datetime.fromisoformat("2026-11-10 15:00")}
    rt.k._now = lambda: clock["t"]
    return rt, ctx, clock


def test_registration_matches_manifest(rt):
    _, ctx, _ = rt
    assert set(ctx.tools) == {"kairos_park", "kairos_interrupt", "kairos_status"}
    assert set(ctx.hooks) == {"pre_tool_call", "post_tool_call", "pre_llm_call", "post_llm_call",
                              "on_human_input_request", "on_human_input_resolved"}
    assert set(ctx.commands) == {"flow", "catchup", "late", "night", "kairos"}


def test_focus_flow_end_to_end(rt):
    r, ctx, clock = rt
    reply = ctx.commands["flow"]("30", session_id="s1")
    assert "Focus until 3:30 PM" in reply
    assert ctx.posted and ctx.posted[0].texts[0].startswith("Kairos · focus")

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
    parked = json.loads(ctx.tools["kairos_park"](question="Which color?", default="blue", why="brand", task_id="s1"))
    assert parked["parked"].startswith("q-") and parked["proceed_with"] == "blue"
    status = json.loads(ctx.tools["kairos_status"]())
    assert status["focus_active"] and status["parked"] == 1
    ok = json.loads(ctx.tools["kairos_interrupt"](question="Pay?", why="money", task_id="s1"))
    assert ok["ok"]
    assert ctx.hooks["pre_tool_call"](tool_name="clarify", args={"questions": [{"question": "Pay?"}]},
                                      task_id="s1", session_id="s1") is None
    assert "question is required" in ctx.tools["kairos_park"](question="", default="x")


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


def test_cron_turns_are_never_blocked(rt):
    r, ctx, clock = rt
    clock["t"] = datetime.fromisoformat("2026-11-10 23:05")
    ctx.current_cron_execution = object()
    assert ctx.hooks["pre_llm_call"](session_id="cron", user_message="nightly job", is_first_turn=True, platform="cli") is None


def test_hooks_never_raise(rt):
    r, ctx, _ = rt
    r.k.focus = lambda: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[assignment]
    assert ctx.hooks["pre_tool_call"](tool_name="clarify", args={}, task_id="s1") is None
    assert ctx.hooks["pre_llm_call"](session_id="s1", user_message="x") is None
    assert ctx.hooks["post_llm_call"](session_id="s1", assistant_response="x") is None
    assert ctx.hooks["on_human_input_request"](kind="approval", request_id="r") is None


def test_commands_text(rt):
    r, ctx, _ = rt
    assert "Kairos commands" in ctx.commands["kairos"]("help")
    assert "Night set: cutoff 11:00 PM" in ctx.commands["night"]("23:00 07:00")
    assert "Use /night" in ctx.commands["night"]("99:99")
    assert "No focus block" in ctx.commands["flow"]("off", session_id="s1")
    assert "Kairos receipt" in ctx.commands["kairos"]("receipt")
    assert "No questions were parked" in ctx.commands["catchup"]("", session_id="s1")
