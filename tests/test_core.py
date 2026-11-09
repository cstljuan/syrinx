"""Unit tests for the Kairos rules. No Hermes needed: ``python -m pytest tests``."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core  # noqa: E402


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def now(self) -> datetime:
        return self.t

    def advance(self, **kwargs) -> None:
        self.t = self.t + timedelta(**kwargs)


def make(start: str = "2026-11-10 15:00", **config):
    clock = FakeClock(datetime.fromisoformat(start))
    k = core.Kairos(core.MemoryStore(), now=clock.now, config=config)
    return k, clock


def test_focus_starts_and_expires():
    k, clock = make()
    focus = k.start_focus(30)
    assert focus["active"] and focus["minutes"] == 30
    assert k.focus_remaining_minutes() == 30
    clock.advance(minutes=31)
    assert not k.focus()["active"]
    assert k.take_pending_return() is True
    assert k.take_pending_return() is False
    assert k.stats()["focus_minutes"] == 30


def test_focus_off_counts_only_elapsed_minutes():
    k, clock = make()
    k.start_focus(45)
    clock.advance(minutes=12)
    ended = k.end_focus()
    assert ended["ended"] and ended["minutes"] == 12
    assert k.stats()["focus_minutes"] == 12


def test_clarify_is_parked_during_focus_with_recommended_default():
    k, _ = make()
    k.start_focus(45)
    args = {"questions": [{"question": "Which database?", "choices": ["Postgres (Recommended)", "SQLite"]},
                          {"question": "Delete the old logs?"}]}
    directive = k.clarify_directive(args, session_id="s1")
    assert directive["action"] == "block"
    assert "parked" in directive["message"]
    open_items = k.parked_open()
    assert len(open_items) == 2
    assert open_items[0]["default"] == "Postgres (Recommended)"
    assert open_items[1]["default"] == "your own best judgment"
    assert k.stats()["questions_parked"] == 2


def test_clarify_passes_when_no_focus_or_after_interrupt():
    k, _ = make()
    assert k.clarify_directive({"questions": [{"question": "x"}]}, session_id="s1") is None
    k.start_focus(45)
    k.allow_next_clarify("s1")
    assert k.clarify_directive({"questions": [{"question": "x"}]}, session_id="s1") is None
    assert k.clarify_directive({"questions": [{"question": "x"}]}, session_id="s1")["action"] == "block"
    assert k.stats()["interruptions_urgent"] == 1


def test_return_context_hands_back_every_question_once():
    k, clock = make()
    k.start_focus(10)
    k.park("Keep the old API?", "yes", "safer", session_id="s1")
    clock.advance(minutes=11)
    assert k.take_pending_return()
    ctx = k.return_context("s1")
    assert "ONE clarify call" in ctx and "Keep the old API?" in ctx
    assert k.parked_open() == []
    assert k.stats()["questions_batched"] == 1


def test_night_crosses_midnight_and_late_override():
    k, clock = make("2026-11-10 23:00")
    assert k.is_night()
    until = k.late(20)
    assert not k.is_night()
    clock.t = until + timedelta(minutes=1)
    assert k.is_night()
    clock.t = datetime.fromisoformat("2026-11-11 08:00")
    assert not k.is_night()
    clock.t = datetime.fromisoformat("2026-11-11 07:59")
    assert k.is_night()


def test_night_disabled_by_config():
    k, _ = make("2026-11-10 23:30", night_enabled=False)
    assert not k.is_night()


def test_queue_and_morning_brief_delivered_once():
    k, clock = make("2026-11-10 23:10")
    k.queue_for_morning("refactor the auth module", session_id="s1")
    assert k.take_morning_brief() == []  # still night
    clock.t = datetime.fromisoformat("2026-11-11 08:05")
    items = k.take_morning_brief()
    assert len(items) == 1 and items[0]["text"] == "refactor the auth module"
    assert k.take_morning_brief() == []
    assert "11:10 PM" in k.morning_context(items)


def test_set_night_times_validates():
    k, _ = make()
    k.set_night_times("23:15", "07:30")
    assert k.cutoff().hour == 23 and k.wake().minute == 30
    with pytest.raises(ValueError):
        k.set_night_times("25:00")


def test_trace_keeps_no_arguments_only_safe_summaries():
    k, _ = make()
    k.record_tool("s1", "terminal", {"command": "export TOKEN=abc && curl https://x"}, duration_ms=10)
    k.record_tool("s1", "write_file", {"path": "/Users/me/secret-project/app.py", "content": "x"})
    rows = k.trace_rows("s1")
    assert rows[0]["what"] == "terminal export"
    assert rows[1]["what"] == "write_file app.py"
    text = k.catchup_text("s1")
    assert "abc" not in text and "secret-project" not in text
    assert "2 tool calls" in text


def test_catchup_uses_llm_when_given_and_falls_back_on_failure():
    k, _ = make()
    k.record_tool("s1", "read_file", {"path": "a.py"})
    assert k.catchup_text("s1", llm=lambda p: "tight") == "tight"

    def boom(_):
        raise RuntimeError("no model")

    assert "Kairos catch-up" in k.catchup_text("s1", llm=boom)


def test_status_and_receipt_text():
    k, clock = make("2026-11-10 15:00")
    assert k.status_line() == "Kairos · open"
    k.start_focus(45)
    k.park("q", "d", session_id="s1")
    clock.advance(minutes=5)
    assert k.status_line() == "Kairos · focus until 3:45 PM · 5 min in · 1 parked"
    receipt = k.receipt_text()
    assert "Questions parked: 1" in receipt


def test_summaries_for_other_tools():
    assert core.summarize_tool_call("web_search", {"query": "hermes plugin api"}) == "web_search hermes plugin api"
    assert core.summarize_tool_call("delegate_task", {"goal": "x"}) == "delegate_task (subagent)"
    assert core.summarize_tool_call("browser_click", {"selector": "#a"}) == "browser_click"
    assert core.summarize_tool_call("terminal", {"command": ""}) == "terminal"


def test_pane_answers_are_delivered_once_and_snapshot_is_complete():
    k, _ = make()
    k.start_focus(10)
    item = k.park("Tabs or spaces?", "spaces", session_id="s1")
    assert k.take_answered() == []
    assert k.answer("nope", "x") is None
    assert k.answer(item["id"], "tabs")["status"] == "answered"
    fresh = k.take_answered()
    assert len(fresh) == 1 and fresh[0]["answer"] == "tabs"
    assert k.take_answered() == []
    assert "tabs" in k.answers_context(fresh)
    snap = k.snapshot()
    assert snap["focus"]["active"] and snap["night"]["cutoff"] == "22:30"
    assert snap["parked"] == [] and "Kairos receipt" in snap["receipt"]


def test_focus_restart_closes_previous_block():
    k, clock = make()
    k.start_focus(30)
    clock.advance(minutes=10)
    k.start_focus(30)
    assert k.stats()["blocks_ended"] == 1 and k.stats()["focus_minutes"] == 10
    assert k.focus()["active"]
