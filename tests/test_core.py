"""Unit tests for the Syrinx rules. No Hermes needed: ``python -m pytest tests``."""

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
    k = core.Syrinx(core.MemoryStore(), now=clock.now, config=config)
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
    tightened = k.catchup_text("s1", llm=lambda p: "tight")
    # The model may tighten the prose, but the counted lines are appended untouched.
    assert tightened.startswith("tight") and "Counted from the tool calls" in tightened and "Read or searched: 1." in tightened

    def boom(_):
        raise RuntimeError("no model")

    assert "Syrinx catch-up" in k.catchup_text("s1", llm=boom)


def test_status_and_receipt_text():
    k, clock = make("2026-11-10 15:00")
    assert k.status_line() == "Syrinx · open"
    k.start_focus(45)
    k.park("q", "d", session_id="s1")
    clock.advance(minutes=5)
    assert k.status_line() == "Syrinx · focus until 3:45 PM · 5 min in · 1 parked"
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
    assert snap["parked"] == [] and "Syrinx receipt" in snap["receipt"]


def test_week_text_and_necessary_interruptions():
    k, clock = make("2026-11-10 15:00")
    k.start_focus(10)
    k._bump("interruptions_necessary")
    clock.advance(minutes=11)
    k.focus()
    week = k.week_text()
    assert week.startswith("Syrinx, last 7 days") and "today: 10 min focus" in week
    assert "Approvals that still reached you during focus: 1." in k.receipt_text()
    snap = k.snapshot()
    assert snap["parked"] == []


def test_focus_restart_closes_previous_block():
    k, clock = make()
    k.start_focus(30)
    clock.advance(minutes=10)
    k.start_focus(30)
    assert k.stats()["blocks_ended"] == 1 and k.stats()["focus_minutes"] == 10
    assert k.focus()["active"]


def test_standing_answer_stops_the_same_question_even_outside_focus():
    k, _ = make()
    made = k.add_standing("Tabs or spaces?", "spaces")
    assert made and k.match_standing("Should I use tabs or spaces for indentation?")["answer"] == "spaces"
    assert k.match_standing("Which database should I use?") is None
    directive = k.clarify_directive({"questions": [{"question": "Do you want tabs or spaces?"}]}, session_id="s1")
    assert directive["action"] == "block" and "use: spaces" in directive["message"]
    assert k.stats()["questions_auto_answered"] == 1 and k.standing()[0]["uses"] == 1
    assert "never had to answer again: 1" in k.receipt_text()
    # The agent insists right away: the case must be different, so it goes through once.
    assert k.clarify_directive({"questions": [{"question": "Do you want tabs or spaces?"}]}, session_id="s1") is None


def test_standing_and_new_questions_in_one_card():
    k, _ = make()
    k.add_standing("Tabs or spaces?", "spaces")
    args = {"questions": [{"question": "Tabs or spaces?"}, {"question": "Which port should the server use?"}]}
    outside = k.clarify_directive(args, session_id="s1")
    assert "use: spaces" in outside["message"] and "Ask only the remaining" in outside["message"]
    assert "Which port" in outside["message"] and k.parked_open() == []
    # In a focus block the settled one is answered and only the new one is parked.
    k2, _ = make()
    k2.add_standing("Tabs or spaces?", "spaces")
    k2.start_focus(30)
    inside = k2.clarify_directive(args, session_id="s1")
    assert "use: spaces" in inside["message"] and len(k2.parked_open()) == 1
    assert k2.parked_open()[0]["question"].startswith("Which port")


def test_same_answer_twice_becomes_a_suggestion_then_a_rule():
    k, _ = make()
    assert k.note_answer("Which package manager?", "pnpm") is None
    suggestion = k.note_answer("Which package manager should I use?", "pnpm")
    assert suggestion and k.suggested()[0]["answer"] == "pnpm"
    assert k.note_answer("Which package manager do you prefer?", "pnpm") is None      # offered once, not nagged
    assert "same answer twice" in k.standing_text()
    made = k.accept_suggestion("1")
    assert made["answer"] == "pnpm" and k.suggested() == [] and k.standing()[0]["source"] == "learned"
    assert "package manager" in k.standing_context()
    assert k.forget_standing("1") and k.standing() == [] and k.standing_context() == ""


def test_answer_in_chat_closes_a_handed_back_question_and_always_from_parked():
    k, clock = make()
    k.start_focus(10)
    item = k.park("Keep the old API?", "yes", session_id="s1")
    clock.advance(minutes=11)
    k.take_pending_return()
    k.return_context("s1")
    assert len(k.handed_back_open()) == 1
    k.note_answer("Keep the old API?", "no, remove it")
    assert k.handed_back_open() == []
    made = k.always_from_parked(item["id"])
    assert made["answer"] == "no, remove it"


def test_deep_work_hours_start_a_flow_once_a_day():
    k, clock = make("2026-11-10 08:30")           # a Tuesday
    k.add_window("weekdays", "09:00", "11:00")
    assert k.schedule_tick() is False
    clock.t = datetime.fromisoformat("2026-11-10 09:05")
    assert k.schedule_tick() is True
    focus = k.focus()
    assert focus["active"] and focus["source"] == "schedule" and focus["minutes"] == 115
    k.end_focus()
    assert k.schedule_tick() is False              # ended early: it does not come back today
    clock.t = datetime.fromisoformat("2026-11-11 09:00")
    assert k.schedule_tick() is True               # next day it does
    clock.t = datetime.fromisoformat("2026-11-14 09:30")   # Saturday
    k.end_focus()
    assert k.schedule_tick() is False
    with pytest.raises(ValueError):
        k.add_window("weekdays", "11:00", "09:00")
    assert "weekdays 09:00 to 11:00" in k.windows_text() and k.clear_windows() == 1


def test_question_budget_parks_the_extra_cards_and_hands_them_back():
    k, clock = make()
    k.set_budget(1)
    card = {"questions": [{"question": "Which region?", "choices": ["us-east", "eu-west"]}]}
    assert k.clarify_directive(card, session_id="s1") is None              # the first card reaches the user
    over = k.clarify_directive({"questions": [{"question": "Which tier?", "choices": ["small", "large"]}]}, session_id="s1")
    assert over["action"] == "block" and "1 question cards an hour" in over["message"]
    assert k.parked_open()[0]["default"] == "small"
    assert k.take_pending_return() is True and k.take_pending_return() is False
    clock.advance(minutes=61)
    assert k.clarify_directive(card, session_id="s1") is None              # an hour later the budget is back
    k.set_budget(0)
    assert k.budget() == 0


def test_default_hit_rate_counts_kept_and_changed():
    k, clock = make()
    k.start_focus(10)
    first = k.park("Keep the old API?", "yes (Recommended)", session_id="s1")
    second = k.park("Which port?", "8080", session_id="s1")
    k.answer(first["id"], "yes")
    k.answer(second["id"], "9090")
    stats = k.stats()
    assert stats["defaults_kept"] == 1 and stats["defaults_changed"] == 1
    assert "Defaults you kept: 1 of 2" in k.receipt_text()


def test_morning_brief_carries_yesterday():
    k, clock = make("2026-11-10 15:00")
    k.start_focus(60)
    k.park("q", "d", session_id="s1")
    clock.advance(minutes=61)
    k.focus()
    clock.t = datetime.fromisoformat("2026-11-10 23:10")
    k.queue_for_morning("write the report", session_id="s1")
    clock.t = datetime.fromisoformat("2026-11-11 08:05")
    text = k.morning_context(k.take_morning_brief())
    assert "write the report" in text and "yesterday Syrinx kept 1 h" in text and "still waiting" in text


def test_away_report_is_counted_and_flags_what_left_the_machine():
    k, clock = make()
    k.start_focus(30)
    k.record_tool("s1", "read_file", {"path": "/x/app.py"})
    k.record_tool("s1", "write_file", {"path": "/x/app.py", "content": "secret"})
    k.record_tool("s1", "patch", {"path": "/x/test_app.py"})
    k.record_tool("s1", "terminal", {"command": "pytest -q"})
    k.record_tool("s1", "web_search", {"query": "fastapi lifespan"})
    quiet = k.away_report("s1")
    assert "Files changed (2 edits): app.py, test_app.py." in quiet and "Commands run (1): pytest." in quiet
    assert "Nothing left your machine." in quiet and not any("unconfirmed" in line for line in quiet)
    # A parked default, then more work on top of it, then a push.
    clock.advance(minutes=1)
    k.park("Keep the old API?", "yes", session_id="s1")
    clock.advance(minutes=1)
    k.record_tool("s1", "write_file", {"path": "/x/api.py"})
    k.record_tool("s1", "terminal", {"command": "git push origin main --token=abc123"})
    report = k.away_report("s1")
    assert report[0].startswith("Left your machine or cannot be undone (1): git push.")
    assert any("Built on 1 unconfirmed default: 2 steps" in line for line in report)
    assert k.assumption_debt("s1") == 2
    text = "\n".join(report)
    assert "abc123" not in text and "secret" not in text and "/x/" not in text
    # The pane sees every session; the return context tells the agent to show the list as written.
    assert k.snapshot()["away"] == k.away_report("*") and k.snapshot()["debt"] == 2
    clock.advance(minutes=31)
    assert k.take_pending_return()
    context = k.return_context("s1")
    assert "Counted by Syrinx" in context and "git push" in context
    # Another block starts clean.
    k.start_focus(30)
    assert k.away_report("s1") == []


def test_classify_tool_calls():
    assert core.classify_tool_call("terminal", {"command": "ls -la"}) == ("run", "")
    assert core.classify_tool_call("terminal", {"command": "rm -rf build"}) == ("outward", "rm -r")
    assert core.classify_tool_call("terminal", {"command": "curl -X POST https://x"}) == ("outward", "curl send")
    assert core.classify_tool_call("send_message", {"text": "hi"}) == ("outward", "send_message")
    assert core.classify_tool_call("search_files", {"pattern": "x"}) == ("read", "")
    assert core.classify_tool_call("browser_click", {}) == ("web", "")
    assert core.classify_tool_call("delegate_task", {}) == ("delegate", "")

