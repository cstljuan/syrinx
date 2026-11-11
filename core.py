"""Syrinx core: the state and the rules, with no Hermes imports.

Everything here is plain Python so it can be unit tested without Hermes. ``runtime.py`` wires
these rules to the Hermes plugin context (hooks, slash commands, tools).

State lives in one ``Store`` (``ctx.state`` in Hermes, a dict in tests) under five keys:
``focus``, ``parked``, ``night``, ``stats`` and ``trace``. Nothing here reads the environment,
runs a command or touches the network.
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from datetime import datetime, time as dtime, timedelta
from typing import Any, Callable, Optional

FOCUS_DEFAULT_MINUTES = 45
FOCUS_MAX_MINUTES = 240
LATE_DEFAULT_MINUTES = 20
LATE_MAX_MINUTES = 90
TRACE_MAX = 200
PARKED_MAX = 40
QUEUE_MAX = 40
HELD_MAX = 40
SUMMARY_MAX_CHARS = 80


class Store:
    """The two calls Syrinx needs from storage. ``ctx.state`` already has this shape."""

    def get(self, key: str, default: Any = None) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def set(self, key: str, value: Any) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class MemoryStore(Store):
    """In-memory store for tests and for a Hermes home where state is unavailable."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def parse_hhmm(text: str) -> Optional[dtime]:
    match = re.fullmatch(r"\s*([01]?\d|2[0-3]):([0-5]\d)\s*", text or "")
    if not match:
        return None
    return dtime(int(match.group(1)), int(match.group(2)))


def fmt_clock(moment: datetime) -> str:
    """12-hour clock without a leading zero, the way a person says it."""
    hour = moment.hour % 12 or 12
    suffix = "AM" if moment.hour < 12 else "PM"
    return f"{hour}:{moment.minute:02d} {suffix}"


def fmt_minutes(minutes: int) -> str:
    minutes = max(0, int(minutes))
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d} min" if rest else f"{hours} h"


_FILLER = frozenset("""a an the to of for in on at or and do does did you your i me my we our us is are be it this that these
those use using want wants would should could can will shall like prefer which what how please with as if so then than here there
go ahead ok okay yes no not want need""".split())


def question_tokens(text: Any) -> frozenset[str]:
    """The meaningful words of a question, for comparing two questions without a model."""
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return frozenset(word for word in words if len(word) > 1 and word not in _FILLER)


def question_similarity(first: Any, second: Any) -> float:
    """0 to 1. Shared words over all words, with credit when one question contains the other."""
    one, two = question_tokens(first), question_tokens(second)
    if not one or not two:
        return 0.0
    shared = len(one & two)
    smaller = min(len(one), len(two))
    contained = (shared / smaller) * 0.9 if smaller >= 2 else 0.0
    return max(shared / len(one | two), contained)


def clarify_questions(args: Any) -> list[dict[str, Any]]:
    """The questions of a ``clarify`` call as ``{question, default}``. Hermes puts the recommended
    choice first; an explicit "recommended" label wins if the agent wrote one."""
    args = args if isinstance(args, dict) else {}
    questions = args.get("questions")
    if isinstance(questions, dict):
        questions = [questions]
    if not isinstance(questions, list):
        return []
    out = []
    for raw in questions[:8]:
        if isinstance(raw, str):
            raw = {"question": raw}
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("question") or "").strip()
        if not text:
            continue
        choices = raw.get("choices")
        default = ""
        if isinstance(choices, list) and choices:
            marked = [c for c in choices if isinstance(c, str) and "recommended" in c.lower()]
            default = str((marked or choices)[0])
        out.append({"question": text, "default": default})
    return out


def command_programs(command: str, limit: int = 4) -> list[str]:
    """The program names a shell command runs (``mkdir``, ``python3``), in order, without arguments.
    Heredoc bodies are dropped first, so file contents never count as commands."""
    command = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?.*?\n\1\b", " ", command, flags=re.S)
    programs: list[str] = []
    for segment in re.split(r"&&|\|\||[;|\n]", command):
        words = segment.strip().split()
        while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in ("sudo", "time", "nohup", "env")):
            words = words[1:]
        if not words:
            continue
        program = os.path.basename(words[0])[:24]
        if re.match(r"^[A-Za-z0-9_.+-]+$", program) and program not in programs:
            programs.append(program)
    return programs[:limit]


def summarize_tool_call(tool_name: str, args: Any) -> str:
    """One short, safe line about a tool call. Never the full arguments: a command line or a
    message body can carry something private. Paths keep only their last component."""
    args = args if isinstance(args, dict) else {}
    name = str(tool_name or "tool")
    path = args.get("path") or args.get("file_path") or args.get("filename")
    if isinstance(path, str) and path.strip():
        return f"{name} {os.path.basename(path.rstrip('/'))[:SUMMARY_MAX_CHARS]}"
    if name == "terminal":
        programs = command_programs(str(args.get("command") or ""))
        return f"terminal {' '.join(programs)}".strip()
    if name in ("web_search", "web_fetch", "web_extract"):
        query = str(args.get("query") or args.get("url") or "").strip()
        return f"{name} {query[:SUMMARY_MAX_CHARS]}".strip()
    if name == "delegate_task":
        return "delegate_task (subagent)"
    return name


_OUTWARD_COMMANDS = (
    (r"\bgit\s+push\b", "git push"), (r"\bgit\s+reset\s+--hard\b", "git reset --hard"),
    (r"\b(npm|pnpm|yarn|cargo|twine|gem)\s+publish\b", "package publish"), (r"\bgh\s+(pr|release|issue)\s+create\b", "gh create"),
    (r"\brm\s+-[a-zA-Z]*[rf]", "rm -r"), (r"\bcurl\b[^|;&]*(-X\s*(POST|PUT|PATCH|DELETE)|--data|-d\s)", "curl send"),
    (r"\b(scp|rsync)\b", "copy to another machine"), (r"\bssh\b", "ssh"), (r"\bdocker\s+push\b", "docker push"),
    (r"\bkubectl\s+(apply|delete)\b", "kubectl change"), (r"\b(terraform|pulumi)\s+(apply|destroy|up)\b", "infrastructure change"),
    (r"\bdrop\s+(table|database)\b", "drop table"),
)
# Flagged in the report but never held: they stay on this machine, and agents use them all day.
_NEVER_HELD = frozenset({"rm -r", "git reset --hard", "copy to another machine"})
_NEVER_HELD_TOOLS = re.compile(r"(delete|remove)", re.I)
_OUTWARD_TOOLS = re.compile(r"(send|post|publish|email|tweet|deploy|upload|pay|purchase|checkout|delete|remove|transfer)", re.I)
_WRITE_TOOLS = re.compile(r"(write|patch|edit|create_file|str_replace|apply_diff|notebook)", re.I)
_READ_TOOLS = re.compile(r"(read|search|list|grep|glob|find|view|cat)", re.I)


def classify_tool_call(tool_name: str, args: Any) -> tuple[str, str]:
    """``(kind, flag)`` for the away report. ``kind`` is write, run, read, web, outward, delegate or other.
    ``flag`` is a short fixed label for an action that left the machine or cannot be undone, never the
    command itself."""
    args = args if isinstance(args, dict) else {}
    name = str(tool_name or "")
    if name in ("terminal", "execute_code", "shell", "bash"):
        command = str(args.get("command") or args.get("code") or "")
        for pattern, label in _OUTWARD_COMMANDS:
            if re.search(pattern, command, re.I):
                return "outward", label
        return "run", ""
    if name.startswith(("web_", "browser")):
        return "web", ""
    if name == "delegate_task":
        return "delegate", ""
    if _WRITE_TOOLS.search(name):
        return "write", ""
    if _OUTWARD_TOOLS.search(name):
        return "outward", name[:40]
    if _READ_TOOLS.search(name):
        return "read", ""
    return "other", ""


def holdable(tool_name: str, args: Any) -> str:
    """The fixed label of an action that would leave this machine (push, publish, send, deploy), or
    ``""``. This is what a focus block holds until the person is back."""
    kind, flag = classify_tool_call(tool_name, args)
    if kind != "outward" or not flag or flag in _NEVER_HELD:
        return ""
    if flag == str(tool_name or "")[:40] and _NEVER_HELD_TOOLS.search(flag):
        return ""
    return flag


class Syrinx:
    """The rules. One instance per plugin load; thread-safe at the level of each public call."""

    def __init__(self, store: Store, *, now: Optional[Callable[[], datetime]] = None,
                 config: Optional[dict[str, Any]] = None) -> None:
        self.store = store
        self._now = now or datetime.now
        self.config = dict(config or {})
        self._lock = threading.RLock()

    # ----- helpers ---------------------------------------------------------------------------

    def now(self) -> datetime:
        return self._now()

    def _get(self, key: str, default: Any) -> Any:
        value = self.store.get(key, None)
        return value if isinstance(value, type(default)) else default

    def _set(self, key: str, value: Any) -> None:
        self.store.set(key, value)

    def _cfg_time(self, key: str, fallback: str) -> dtime:
        return parse_hhmm(str(self.config.get(key, fallback))) or parse_hhmm(fallback)  # type: ignore[return-value]

    def _today(self) -> str:
        return self.now().date().isoformat()

    def _bump(self, key: str, amount: int = 1) -> None:
        stats = self._get("stats", {})
        stats[key] = int(stats.get(key, 0)) + amount
        days = stats.setdefault("days", {})
        day = days.setdefault(self._today(), {})
        day[key] = int(day.get(key, 0)) + amount
        self._set("stats", stats)

    # ----- focus -----------------------------------------------------------------------------

    def focus(self) -> dict[str, Any]:
        """Current focus block, after expiring a finished one. ``active`` is the flag to read."""
        with self._lock:
            focus = self._get("focus", {})
            if focus.get("active"):
                until = datetime.fromisoformat(focus["until"])
                if self.now() >= until:
                    self._end_focus(focus, reason="finished", at=until)
                    focus = self._get("focus", {})
            return focus

    def start_focus(self, minutes: Optional[int] = None, *, source: str = "manual") -> dict[str, Any]:
        with self._lock:
            default = int(self.config.get("focus_minutes", FOCUS_DEFAULT_MINUTES) or FOCUS_DEFAULT_MINUTES)
            minutes = int(minutes or default)
            minutes = max(1, min(FOCUS_MAX_MINUTES, minutes))
            current = self.focus()
            if current.get("active"):
                self._end_focus(current, reason="restarted", at=self.now())
            start = self.now()
            focus = {
                "active": True,
                "source": source,
                "started": start.isoformat(),
                "until": (start + timedelta(minutes=minutes)).isoformat(),
                "minutes": minutes,
                "pending_return": False,
            }
            self._set("focus", focus)
            self._bump("blocks_started")
            return focus

    def extend_focus(self, minutes: int) -> None:
        """Push the end of an active block out to at least ``minutes`` from now (auto-focus keeps
        the block open while the person is still heads-down elsewhere)."""
        with self._lock:
            focus = self.focus()
            if not focus.get("active"):
                return
            target = self.now() + timedelta(minutes=max(1, int(minutes)))
            if target > datetime.fromisoformat(focus["until"]):
                focus["until"] = target.isoformat()
                self._set("focus", focus)

    def end_focus(self, reason: str = "manual") -> dict[str, Any]:
        with self._lock:
            focus = self.focus()
            if not focus.get("active"):
                return {"ended": False, "minutes": 0}
            return self._end_focus(focus, reason=reason, at=self.now())

    def _end_focus(self, focus: dict[str, Any], *, reason: str, at: datetime) -> dict[str, Any]:
        started = datetime.fromisoformat(focus["started"])
        until = datetime.fromisoformat(focus["until"])
        end = min(at, until)
        minutes = max(0, int((end - started).total_seconds() // 60))
        parked = len(self.parked_open())
        self._set("focus", {
            "active": False,
            "ended": end.isoformat(),
            "last_started": focus.get("started"),
            "reason": reason,
            "last_minutes": minutes,
            "pending_return": True,
            "source": focus.get("source", "manual"),
        })
        self._bump("focus_minutes", minutes)
        self._bump("blocks_ended")
        return {"ended": True, "minutes": minutes, "parked": parked, "reason": reason}

    def focus_remaining_minutes(self) -> int:
        focus = self.focus()
        if not focus.get("active"):
            return 0
        until = datetime.fromisoformat(focus["until"])
        return max(0, int((until - self.now()).total_seconds() // 60))

    def focus_elapsed_minutes(self) -> int:
        focus = self.focus()
        if not focus.get("active"):
            return 0
        started = datetime.fromisoformat(focus["started"])
        return max(0, int((self.now() - started).total_seconds() // 60))

    def take_pending_return(self) -> bool:
        """True once after a focus block ended, so the next turn can deliver the catch-up."""
        with self._lock:
            focus = self.focus()
            if focus.get("pending_return") and not focus.get("active"):
                focus["pending_return"] = False
                self._set("focus", focus)
                return True
            if self._get("budget_return", False) and not focus.get("active"):
                self._set("budget_return", False)
                return True
            return False

    # ----- deep-work hours -------------------------------------------------------------------
    # Flow that starts by itself: "every weekday 09:00 to 11:00". Checked lazily, no scheduler needed.

    DAY_SETS = {"daily": tuple(range(7)), "weekdays": tuple(range(5)), "weekends": (5, 6)}

    def windows(self) -> list[dict[str, Any]]:
        return list(self._get("windows", []))

    def add_window(self, days: str, start: str, end: str) -> dict[str, Any]:
        first, last = parse_hhmm(start), parse_hhmm(end)
        if days not in self.DAY_SETS or first is None or last is None or first >= last:
            raise ValueError("use daily, weekdays or weekends, then HH:MM-HH:MM with the end after the start")
        window = {"id": _new_id("w"), "days": days, "start": first.strftime("%H:%M"), "end": last.strftime("%H:%M")}
        self._set("windows", (self._get("windows", []) + [window])[-8:])
        return window

    def clear_windows(self) -> int:
        count = len(self._get("windows", []))
        self._set("windows", [])
        return count

    def current_window(self, moment: Optional[datetime] = None) -> Optional[tuple[dict[str, Any], datetime]]:
        now = moment or self.now()
        for window in self._get("windows", []):
            if now.weekday() not in self.DAY_SETS.get(window.get("days"), ()):
                continue
            start = datetime.combine(now.date(), parse_hhmm(window["start"]))
            end = datetime.combine(now.date(), parse_hhmm(window["end"]))
            if start <= now < end:
                return window, end
        return None

    def schedule_tick(self) -> bool:
        """Open the scheduled block if one should be running now. True if this call opened it.
        A window opens once a day: ending it early does not make it come back."""
        found = self.current_window()
        if not found or self.focus().get("active"):
            return False
        window, end = found
        key = f"{window['id']}:{end.date().isoformat()}"
        if self._get("window_done", "") == key:
            return False
        self._set("window_done", key)
        self.start_focus(max(1, int((end - self.now()).total_seconds() // 60)), source="schedule")
        return True

    def windows_text(self) -> str:
        items = self._get("windows", [])
        if not items:
            return ("No deep-work hours set. Example: /flow weekdays 09:00-11:00 starts a flow by itself "
                    "every weekday morning.")
        lines = ["Deep-work hours (flow starts by itself):"]
        lines += [f"- {w['days']} {w['start']} to {w['end']}" for w in items]
        lines.append("/flow hours clear removes them.")
        return "\n".join(lines)

    # ----- question budget -------------------------------------------------------------------
    # Outside a flow: at most N question cards an hour. The rest are parked and come back with the
    # user's next message.

    def budget(self) -> int:
        try:
            return max(0, int(self._get("budget", self.config.get("question_budget", 0)) or 0))
        except (TypeError, ValueError):
            return 0

    def set_budget(self, per_hour: int) -> int:
        self._set("budget", max(0, min(60, int(per_hour))))
        return self.budget()

    def _budget_spent(self) -> int:
        cutoff = self.now() - timedelta(hours=1)
        return sum(1 for stamp in self._get("ask_log", []) if datetime.fromisoformat(stamp) > cutoff)

    def _budget_note(self) -> None:
        self._set("ask_log", (self._get("ask_log", []) + [self.now().isoformat()])[-60:])

    # ----- parking ---------------------------------------------------------------------------

    def parked_open(self) -> list[dict[str, Any]]:
        return [item for item in self._get("parked", []) if item.get("status") == "parked"]

    def handed_back_open(self) -> list[dict[str, Any]]:
        """Questions handed back to the user and not answered yet."""
        return [item for item in self._get("parked", []) if item.get("status") == "handed_back"]

    def park(self, question: str, default: str = "", why: str = "", *, session_id: str = "",
             urgent: bool = False, source: str = "agent") -> dict[str, Any]:
        with self._lock:
            parked = self._get("parked", [])
            item = {
                "id": _new_id("q"),
                "question": str(question or "").strip()[:500],
                "default": str(default or "").strip()[:300],
                "why": str(why or "").strip()[:300],
                "session_id": session_id or "",
                "created": self.now().isoformat(),
                "status": "parked",
                "urgent": bool(urgent),
                "source": source,
                "answer": "",
            }
            parked.append(item)
            if len(parked) > PARKED_MAX:
                parked = parked[-PARKED_MAX:]
            self._set("parked", parked)
            self._bump("questions_parked")
            return item

    def park_from_clarify(self, args: Any, *, session_id: str = "") -> list[dict[str, Any]]:
        """Park every question of a ``clarify`` call. The default is the choice the agent marked as
        recommended, else the first choice, else the agent's own judgment."""
        return self.park_questions(clarify_questions(args), session_id=session_id)

    def park_questions(self, questions: list[dict[str, Any]], *, session_id: str = "") -> list[dict[str, Any]]:
        return [self.park(q["question"], q.get("default") or "your own best judgment",
                          "asked while the user was heads-down", session_id=session_id, source="clarify")
                for q in questions]

    # ----- standing answers ------------------------------------------------------------------
    # "Answer once, never asked again." A standing answer is a question the user has settled for good.
    # Syrinx hands it to the agent at the start of a session and stops a clarify call that asks it again.

    MATCH = 0.72

    def standing(self) -> list[dict[str, Any]]:
        return list(self._get("standing", []))

    def suggested(self) -> list[dict[str, Any]]:
        return list(self._get("suggested", []))

    def match_standing(self, question: Any) -> Optional[dict[str, Any]]:
        best, score = None, 0.0
        for item in self._get("standing", []):
            similarity = question_similarity(question, item.get("question"))
            if similarity > score:
                best, score = item, similarity
        return best if score >= self.MATCH else None

    def add_standing(self, question: str, answer: str, *, source: str = "user") -> Optional[dict[str, Any]]:
        question, answer = str(question or "").strip()[:300], str(answer or "").strip()[:300]
        if not question or not answer:
            return None
        with self._lock:
            items = self._get("standing", [])
            existing = next((i for i in items if question_similarity(question, i.get("question")) >= self.MATCH), None)
            if existing:
                existing["answer"] = answer
                item = existing
            else:
                item = {"id": _new_id("a"), "question": question, "answer": answer, "created": self.now().isoformat(),
                        "uses": 0, "source": source}
                items.append(item)
                items = items[-60:]
            self._set("standing", items)
            # A suggestion that became a rule is no longer a suggestion.
            self._set("suggested", [s for s in self._get("suggested", [])
                                    if question_similarity(question, s.get("question")) < self.MATCH])
            self._bump("standing_added")
            return item

    def _pick(self, items: list[dict[str, Any]], ref: Any) -> Optional[dict[str, Any]]:
        ref = str(ref or "").strip()
        if ref.isdigit() and 1 <= int(ref) <= len(items):
            return items[int(ref) - 1]
        return next((i for i in items if i.get("id") == ref), None)

    def forget_standing(self, ref: Any) -> Optional[dict[str, Any]]:
        with self._lock:
            items = self._get("standing", [])
            item = self._pick(items, ref)
            if item:
                self._set("standing", [i for i in items if i is not item])
            return item

    def accept_suggestion(self, ref: Any) -> Optional[dict[str, Any]]:
        item = self._pick(self._get("suggested", []), ref)
        return self.add_standing(item["question"], item["answer"], source="learned") if item else None

    def always_from_parked(self, item_id: str) -> Optional[dict[str, Any]]:
        """Turn one parked question into a standing answer: the answer given, else the default taken."""
        for item in self._get("parked", []):
            if item.get("id") == item_id:
                return self.add_standing(item.get("question", ""), item.get("answer") or item.get("default", ""),
                                         source="parked")
        return None

    def _score_default(self, default: Any, answer: Any) -> None:
        """Count whether the user kept the default the agent had taken. This is the agent's hit rate."""
        one, two = str(default or "").strip().lower(), str(answer or "").strip().lower()
        strip = lambda text: re.sub(r"\s*\(recommended\)\s*", "", text).strip()
        one, two = strip(one), strip(two)
        kept = bool(one) and (one == two or one in two or two in one or question_similarity(one, two) >= 0.8)
        self._bump("defaults_kept" if kept else "defaults_changed")

    def note_answer(self, question: Any, answer: Any) -> Optional[dict[str, Any]]:
        """Remember what the user answered. The second time the same question gets the same answer,
        Syrinx offers to make it a standing answer. Returns the new suggestion, if this made one."""
        question, answer = str(question or "").strip()[:300], str(answer or "").strip()[:300]
        if not question or not answer:
            return None
        with self._lock:
            # A handed-back question that has now been answered in the chat is closed.
            parked = self._get("parked", [])
            for item in parked:
                if item.get("status") == "handed_back" and question_similarity(question, item.get("question")) >= self.MATCH:
                    item["status"], item["answer"], item["delivered"] = "answered", answer, True
                    item["answered"] = self.now().isoformat()
                    self._score_default(item.get("default", ""), answer)
            self._set("parked", parked)

            history = self._get("answer_history", [])
            repeat = next((h for h in history if h.get("answer", "").lower() == answer.lower()
                           and question_similarity(question, h.get("question")) >= self.MATCH), None)
            history.append({"question": question, "answer": answer})
            self._set("answer_history", history[-40:])
            if not repeat or self.match_standing(question):
                return None
            suggested = self._get("suggested", [])
            if any(question_similarity(question, s.get("question")) >= self.MATCH for s in suggested):
                return None
            suggestion = {"id": _new_id("s"), "question": question, "answer": answer}
            self._set("suggested", (suggested + [suggestion])[-12:])
            return suggestion

    def standing_context(self) -> str:
        items = self._get("standing", [])
        if not items:
            return ""
        lines = ["Syrinx: the user has already settled these questions for good. If one comes up, use the answer and do "
                 "not ask again. Do not mention this list or any answer that does not apply to the task:"]
        lines += [f"- {item['question']} -> {item['answer']}" for item in items[-25:]]
        return "\n".join(lines)

    def standing_text(self) -> str:
        items, suggested = self._get("standing", []), self._get("suggested", [])
        lines = ["Standing answers (the agent never asks these again)"]
        if not items:
            lines.append("None yet. Add one with: /always <question> = <answer>")
        for index, item in enumerate(items, start=1):
            used = f", used {item.get('uses', 0)}x" if item.get("uses") else ""
            lines.append(f"{index}. {item['question']} -> {item['answer']}{used}")
        if suggested:
            lines.append("")
            lines.append("You gave the same answer twice. Make it permanent with /always yes <number>:")
            for index, item in enumerate(suggested, start=1):
                lines.append(f"{index}. {item['question']} -> {item['answer']}")
        if items:
            lines.append("")
            lines.append("/always forget <number> removes one.")
        return "\n".join(lines)

    def answer(self, item_id: str, text: str) -> Optional[dict[str, Any]]:
        with self._lock:
            parked = self._get("parked", [])
            for item in parked:
                if item.get("id") == item_id and item.get("status") in ("parked", "handed_back"):
                    item["status"] = "answered"
                    item["answer"] = str(text or "").strip()[:500]
                    self._score_default(item.get("default", ""), item["answer"])
                    item["answered"] = self.now().isoformat()
                    item["delivered"] = False
                    self._set("parked", parked)
                    return item
            return None

    def take_answered(self) -> list[dict[str, Any]]:
        """Answers given outside the chat (the Desktop pane) that the agent has not seen yet."""
        with self._lock:
            parked = self._get("parked", [])
            fresh = [item for item in parked if item.get("status") == "answered" and not item.get("delivered", True)]
            for item in fresh:
                item["delivered"] = True
            if fresh:
                self._set("parked", parked)
            return [dict(item) for item in fresh]

    def answers_context(self, items: list[dict[str, Any]]) -> str:
        lines = [f"Syrinx: the user answered {len(items)} parked question{'s' if len(items) != 1 else ''} in the "
                 "Syrinx pane. Apply each answer; redo any piece where it differs from the default you used:"]
        for item in items:
            lines.append(f"- {item['id']}: \"{item['question']}\" -> {item['answer']} (default used: {item['default']})")
        return "\n".join(lines)

    def snapshot(self) -> dict[str, Any]:
        """Everything a UI needs, in one read."""
        focus = self.focus()
        now = self.now()
        return {
            "status_line": self.status_line(),
            "now": now.isoformat(),
            "focus": {
                "active": bool(focus.get("active")),
                "until": focus.get("until") if focus.get("active") else None,
                "minutes": focus.get("minutes") if focus.get("active") else None,
                "remaining_minutes": self.focus_remaining_minutes(),
                "elapsed_minutes": self.focus_elapsed_minutes(),
                "last_minutes": focus.get("last_minutes"),
                "source": focus.get("source") if focus.get("active") else None,
            },
            "night": {
                "enabled": bool(self.config.get("night_enabled", True)),
                "is_night": self.is_night(),
                "late_active": self.late_active(),
                "cutoff": self.cutoff().strftime("%H:%M"),
                "wake": self.wake().strftime("%H:%M"),
                "queued": self.queued_open(),
            },
            "parked": self.parked_open(),
            "handed_back": len(self.handed_back_open()),
            "held": [{"label": item["label"], "tries": int(item.get("tries", 1))} for item in self.held_open()],
            "hold": self.hold_enabled(),
            "away": self.away_for_pane(),
            "debt": self.assumption_debt("*"),
            "windows": self.windows(),
            "budget": self.budget(),
            "standing": self.standing(),
            "suggested": self.suggested(),
            "stats": self.stats(),
            "week": self.card_data()["days"],
            "receipt": self.receipt_text(),
        }

    def hand_back(self) -> list[dict[str, Any]]:
        """Mark every open question as handed back to the person (the agent will ask them in one
        pass) and return them."""
        with self._lock:
            parked = self._get("parked", [])
            handed = []
            for item in parked:
                if item.get("status") == "parked":
                    item["status"] = "handed_back"
                    item["handed_back"] = self.now().isoformat()
                    handed.append(dict(item))
            self._set("parked", parked)
            if handed:
                self._bump("questions_batched", len(handed))
            return handed

    def allow_next_clarify(self, session_id: str) -> None:
        with self._lock:
            passes = self._get("clarify_pass", {})
            passes[session_id or "*"] = self.now().isoformat()
            self._set("clarify_pass", passes)

    def consume_clarify_pass(self, session_id: str) -> bool:
        with self._lock:
            passes = self._get("clarify_pass", {})
            key = session_id if (session_id or "") in passes else ("*" if "*" in passes else None)
            if key is None:
                return False
            passes.pop(key, None)
            self._set("clarify_pass", passes)
            return True

    def clarify_directive(self, args: Any, *, session_id: str = "") -> Optional[dict[str, Any]]:
        """What ``pre_tool_call`` returns for a ``clarify`` call. ``None`` lets it through.

        Two things can stop a question: a standing answer (always), and a focus block (while it runs).
        """
        questions = clarify_questions(args)
        settled, open_questions = [], []
        for question in questions:
            match = self.match_standing(question["question"])
            (settled if match else open_questions).append((question, match))

        # Safety valve: if the agent asks the very same thing again right away, it is telling us the
        # standing answer does not fit this case. Let it through once.
        if settled:
            key = "|".join(sorted(" ".join(sorted(question_tokens(q["question"]))) for q, _ in settled))
            with self._lock:
                insisted = self._get("standing_insist", {})
                stamp = insisted.get(session_id or "*", {})
                again = stamp.get("key") == key and (self.now() - datetime.fromisoformat(stamp["at"])).total_seconds() < 180
                insisted[session_id or "*"] = {"key": key, "at": self.now().isoformat()}
                self._set("standing_insist", dict(list(insisted.items())[-20:]))
            if again:
                settled, open_questions = [], [(q, None) for q in questions]

        focus = self.focus()
        in_focus = bool(focus.get("active"))
        if in_focus and open_questions and self.consume_clarify_pass(session_id):
            self._bump("interruptions_urgent")
            in_focus = False
        over_budget = False
        if not in_focus and open_questions:
            limit = self.budget()
            if limit and self._budget_spent() >= limit:
                if self.consume_clarify_pass(session_id):
                    self._bump("interruptions_urgent")
                else:
                    over_budget = True
            if not over_budget and not settled:
                self._budget_note()        # this card is going to reach the user
        if not settled and not in_focus and not over_budget:
            return None

        lines: list[str] = []
        if settled:
            with self._lock:
                items = self._get("standing", [])
                for _, match in settled:
                    for item in items:
                        if item.get("id") == match.get("id"):
                            item["uses"] = int(item.get("uses", 0)) + 1
                self._set("standing", items)
            self._bump("questions_auto_answered", len(settled))
            lines.append("Syrinx: the user already settled this for good, so it was not asked again.")
            for question, match in settled:
                lines.append(f"- \"{question['question']}\" -> use: {match['answer']}")
            lines.append("If this case is truly different from the standing answer, ask again and it will go through.")

        if open_questions and in_focus:
            items = self.park_questions([q for q, _ in open_questions], session_id=session_id)
            until = datetime.fromisoformat(focus["until"])
            lines.append(
                f"Syrinx: the user is in a focus block until {fmt_clock(until)} and is not reading the chat. "
                "This question was parked for them, not shown."
            )
            for item in items:
                lines.append(f"- {item['id']}: \"{item['question']}\" parked. Default to use now: {item['default']}.")
            lines.append(
                "Continue the task with those defaults and say in your reply which defaults you took. "
                "Park anything else with syrinx_park(question, default, why). Only if the task truly cannot "
                "move without an answer, call syrinx_interrupt(question, why) and then ask with clarify."
            )
        elif open_questions and over_budget:
            items = self.park_questions([q for q, _ in open_questions], session_id=session_id)
            self._set("budget_return", True)
            self._bump("questions_budgeted", len(items))
            lines.append(
                f"Syrinx: the user allows {self.budget()} question cards an hour and that is used up, so this was "
                "parked, not shown. It will be handed back with their next message."
            )
            for item in items:
                lines.append(f"- {item['id']}: \"{item['question']}\" parked. Default to use now: {item['default']}.")
            lines.append("Continue with those defaults and say which ones you took. If the task truly cannot move, "
                         "call syrinx_interrupt(question, why) and then ask with clarify.")
        elif open_questions:
            lines.append("Ask only the remaining questions, in one clarify call:")
            lines += [f"- {q['question']}" for q, _ in open_questions]
        else:
            lines.append("Continue the task with those answers.")
        return {"action": "block", "message": "\n".join(lines)}

    # ----- hold ------------------------------------------------------------------------------
    # During a focus block nothing leaves the machine. A push, publish, send or deploy is stopped
    # before it runs, remembered by its label only, and offered back on the same card as the questions.

    def hold_enabled(self) -> bool:
        value = self._get("hold", "")          # "on" / "off" once set by hand; settings decide until then
        return bool(self.config.get("hold_outward", True)) if value not in ("on", "off") else value == "on"

    def set_hold(self, on: bool) -> bool:
        self._set("hold", "on" if on else "off")
        return bool(on)

    def held_open(self) -> list[dict[str, Any]]:
        return [item for item in self._get("held", []) if item.get("status") == "held"]

    def _would_hold(self, tool_name: str, args: Any) -> str:
        if not self.hold_enabled() or not self.focus().get("active"):
            return ""
        return holdable(tool_name, args)

    def hold_directive(self, tool_name: str, args: Any, *, session_id: str = "") -> Optional[dict[str, Any]]:
        """What ``pre_tool_call`` returns for any tool but ``clarify``. ``None`` lets it run."""
        label = self._would_hold(tool_name, args)
        if not label:
            return None
        with self._lock:
            held = self._get("held", [])
            same = next((item for item in held if item.get("status") == "held" and item.get("label") == label
                         and item.get("session") == (session_id or "*")), None)
            if same:
                same["tries"] = int(same.get("tries", 1)) + 1
            else:
                held.append({"id": _new_id("h"), "label": label, "t": self.now().isoformat(),
                             "session": session_id or "*", "status": "held", "tries": 1})
                self._bump("actions_held")
            self._set("held", held[-HELD_MAX:])
        until = datetime.fromisoformat(self.focus()["until"])
        return {"action": "block", "message": (
            f"Syrinx held this action ({label}). It did not run. The user is in a focus block until {fmt_clock(until)}, "
            "and nothing that leaves this machine runs while they are away. Do not retry it and do not reach the same "
            "result another way. If the same command also did other things, run those again without this part. "
            "Finish everything else, and say in your reply that this is waiting for them. "
            "Syrinx will offer it back on their return card."
        )}

    def offer_held(self) -> list[dict[str, Any]]:
        """Mark every held action as offered back to the person and return them."""
        with self._lock:
            held = self._get("held", [])
            offered = []
            for item in held:
                if item.get("status") == "held":
                    item["status"] = "offered"
                    offered.append(dict(item))
            self._set("held", held)
            return offered

    def _held_in_block(self, session_id: str) -> list[dict[str, Any]]:
        focus = self._get("focus", {})
        since = focus.get("started") if focus.get("active") else focus.get("last_started")
        return [item for item in self._get("held", [])
                if (not since or str(item.get("t", "")) >= since)
                and (session_id in ("", "*") or item.get("session") in (session_id, "*"))]

    # ----- night -----------------------------------------------------------------------------

    def night(self) -> dict[str, Any]:
        return self._get("night", {})

    def cutoff(self) -> dtime:
        night = self.night()
        return parse_hhmm(str(night.get("cutoff", ""))) or self._cfg_time("cutoff", "22:30")

    def wake(self) -> dtime:
        night = self.night()
        return parse_hhmm(str(night.get("wake", ""))) or self._cfg_time("wake", "08:00")

    def set_night_times(self, cutoff: Optional[str] = None, wake: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            night = self.night()
            if cutoff is not None:
                if parse_hhmm(cutoff) is None:
                    raise ValueError(f"not a time: {cutoff!r}")
                night["cutoff"] = cutoff.strip()
            if wake is not None:
                if parse_hhmm(wake) is None:
                    raise ValueError(f"not a time: {wake!r}")
                night["wake"] = wake.strip()
            self._set("night", night)
            return night

    def late_active(self, moment: Optional[datetime] = None) -> bool:
        moment = moment or self.now()
        late_until = self.night().get("late_until")
        return bool(late_until) and moment < datetime.fromisoformat(late_until)

    def in_night_window(self, moment: Optional[datetime] = None) -> bool:
        """Inside the cutoff-to-wake window, ignoring any /late override."""
        if not bool(self.config.get("night_enabled", True)):
            return False
        moment = moment or self.now()
        cutoff, wake = self.cutoff(), self.wake()
        t = moment.time().replace(second=0, microsecond=0)
        if cutoff > wake:  # crosses midnight, the normal case
            return t >= cutoff or t < wake
        return cutoff <= t < wake

    def is_night(self, moment: Optional[datetime] = None) -> bool:
        """Night as the person experiences it: the window, unless /late is active."""
        moment = moment or self.now()
        return self.in_night_window(moment) and not self.late_active(moment)

    def late(self, minutes: Optional[int] = None) -> datetime:
        with self._lock:
            minutes = max(1, min(LATE_MAX_MINUTES, int(minutes or LATE_DEFAULT_MINUTES)))
            until = self.now() + timedelta(minutes=minutes)
            night = self.night()
            night["late_until"] = until.isoformat()
            self._set("night", night)
            self._bump("late_overrides")
            return until

    def queue_for_morning(self, text: str, *, session_id: str = "") -> dict[str, Any]:
        with self._lock:
            night = self.night()
            queued = night.setdefault("queued", [])
            item = {
                "id": _new_id("n"),
                "text": str(text or "").strip()[:2000],
                "session_id": session_id or "",
                "created": self.now().isoformat(),
                "delivered": False,
            }
            queued.append(item)
            if len(queued) > QUEUE_MAX:
                del queued[: len(queued) - QUEUE_MAX]
            self._set("night", night)
            self._bump("requests_queued")
            return item

    def queued_open(self) -> list[dict[str, Any]]:
        return [item for item in self.night().get("queued", []) if not item.get("delivered")]

    def night_block_message(self) -> str:
        wake = self.wake()
        return (
            f"It is {fmt_clock(self.now())}. Your cutoff is {fmt_clock(datetime.combine(self.now().date(), self.cutoff()))}, "
            f"so Syrinx queued this for the morning brief at {fmt_clock(datetime.combine(self.now().date(), wake))}. "
            f"Nothing is lost. Type /late to keep going for {LATE_DEFAULT_MINUTES} minutes, or /late 45 for longer. "
            "Sleep well."
        )

    def take_morning_brief(self) -> list[dict[str, Any]]:
        """Queued requests not yet delivered, marked delivered. Empty while it is still night.
        During a /late override they are handed back at once, since the person chose to go on."""
        with self._lock:
            if self.is_night():
                return []
            night = self.night()
            items = [item for item in night.get("queued", []) if not item.get("delivered")]
            for item in items:
                item["delivered"] = True
                item["delivered_at"] = self.now().isoformat()
            if items:
                self._set("night", night)
                self._bump("mornings_delivered")
            return [dict(item) for item in items]

    # ----- trace and catch-up ----------------------------------------------------------------

    def record_tool(self, session_id: str, tool_name: str, args: Any, *, duration_ms: int = 0) -> None:
        with self._lock:
            trace = self._get("trace", {})
            if self._would_hold(tool_name, args):
                return                     # held before it ran: nothing to count
            rows = trace.setdefault(session_id or "*", [])
            kind, flag = classify_tool_call(tool_name, args)
            row = {"t": self.now().isoformat(), "what": summarize_tool_call(tool_name, args),
                   "ms": int(duration_ms or 0), "kind": kind}
            if flag:
                row["flag"] = flag
            rows.append(row)
            if len(rows) > TRACE_MAX:
                del rows[: len(rows) - TRACE_MAX]
            self._set("trace", trace)

    def record_reply(self, session_id: str, text: Any) -> None:
        with self._lock:
            notes = self._get("replies", {})
            body = text if isinstance(text, str) else ""
            notes[session_id or "*"] = re.sub(r"\s+", " ", body).strip()[:600]
            self._set("replies", notes)

    def trace_rows(self, session_id: str) -> list[dict[str, Any]]:
        trace = self._get("trace", {})
        if session_id in ("", "*"):        # every session, for the pane, which has no session of its own
            rows = [row for session_rows in trace.values() for row in session_rows]
            return sorted(rows, key=lambda row: str(row.get("t", "")))
        return list(trace.get(session_id, []))

    def clear_trace(self, session_id: str) -> None:
        with self._lock:
            trace = self._get("trace", {})
            trace.pop(session_id or "*", None)
            self._set("trace", trace)

    def _block_rows(self, session_id: str) -> list[dict[str, Any]]:
        """Trace rows of the current block, or of the last one that ended."""
        focus = self._get("focus", {})
        since = focus.get("started") if focus.get("active") else focus.get("last_started")
        rows = self.trace_rows(session_id)
        return [row for row in rows if not since or str(row.get("t", "")) >= since]

    def away_report(self, session_id: str) -> list[str]:
        """What happened during the block, counted by code from the tool calls themselves. No model
        wrote any of it, so it cannot be flattering. Lines, most important first."""
        rows = self._block_rows(session_id)
        held = self._held_in_block(session_id)
        if not rows and not held:
            return []
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_kind.setdefault(row.get("kind", "other"), []).append(row)

        def names(kind_rows: list[dict[str, Any]], limit: int = 5) -> str:
            seen: list[str] = []
            for row in kind_rows:
                label = " ".join(str(row.get("what", "")).split(" ")[1:]) or str(row.get("what", ""))
                if label and label not in seen:
                    seen.append(label)
            extra = f", and {len(seen) - limit} more" if len(seen) > limit else ""
            return ", ".join(seen[:limit]) + extra

        lines: list[str] = []
        if held:
            labels: list[str] = []
            for item in held:
                if item["label"] not in labels:
                    labels.append(item["label"])
            lines.append(f"Held for you, did not run ({len(held)}): {', '.join(labels)}.")
        outward = by_kind.get("outward", [])
        if outward:
            flags: list[str] = []
            for row in outward:
                if row.get("flag") and row["flag"] not in flags:
                    flags.append(row["flag"])
            lines.append(f"Left your machine or cannot be undone ({len(outward)}): {', '.join(flags)}. Check these first.")
        written = by_kind.get("write", [])
        if written:
            lines.append(f"Files changed ({len(written)} edits): {names(written)}.")
        ran = by_kind.get("run", [])
        if ran:
            lines.append(f"Commands run ({len(ran)}): {names(ran)}.")
        if by_kind.get("read"):
            lines.append(f"Read or searched: {len(by_kind['read'])}.")
        if by_kind.get("web"):
            lines.append(f"Web lookups: {len(by_kind['web'])}.")
        if by_kind.get("delegate"):
            lines.append(f"Subagents started: {len(by_kind['delegate'])}.")
        if not outward:
            lines.append("Nothing left your machine.")
        debt = self.assumption_debt(session_id)
        if debt:
            waiting = len(self.parked_open()) or len(self.handed_back_open())
            lines.append(f"Built on {waiting} unconfirmed default{'s' if waiting != 1 else ''}: {debt} step{'s' if debt != 1 else ''}. "
                         "Changing an answer may mean redoing them.")
        return lines

    def away_for_pane(self) -> list[str]:
        """The report for the pane: only while a block runs, while its questions are waiting, or for
        an hour after it ended. Otherwise it is old news."""
        focus = self._get("focus", {})
        if focus.get("active") or self.parked_open() or self.handed_back_open() or self.held_open():
            return self.away_report("*")
        ended = focus.get("ended")
        if ended and (self.now() - datetime.fromisoformat(ended)).total_seconds() < 3600:
            return self.away_report("*")
        return []

    def assumption_debt(self, session_id: str) -> int:
        """How many changing steps (edits, commands, outward actions) were taken after the first
        question was parked and before it was answered. The cost of a wrong default grows with this."""
        waiting = [item for item in self._get("parked", []) if item.get("status") in ("parked", "handed_back")]
        if not waiting:
            return 0
        first = min(str(item.get("created", "")) for item in waiting)
        return sum(1 for row in self.trace_rows(session_id)
                   if row.get("kind") in ("write", "run", "outward") and str(row.get("t", "")) >= first)

    def catchup_text(self, session_id: str, *, llm: Optional[Callable[[str], str]] = None) -> str:
        """The catch-up a person reads when they come back. Deterministic; ``llm`` can tighten it."""
        rows = self.trace_rows(session_id)
        reply = self._get("replies", {}).get(session_id or "*", "")
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get("what", "")).split(" ")[0]
            counts[key] = counts.get(key, 0) + 1
        top = ", ".join(f"{name} x{n}" if n > 1 else name for name, n in
                        sorted(counts.items(), key=lambda kv: -kv[1])[:6])
        lines = ["Syrinx catch-up"]
        focus = self._get("focus", {})
        if focus.get("last_minutes") is not None and not focus.get("active"):
            lines.append(f"Focus kept: {fmt_minutes(int(focus.get('last_minutes', 0)))}.")
        if rows:
            lines.append(f"The agent made {len(rows)} tool calls: {top}.")
        report = self.away_report(session_id)
        if report:
            lines.append("Counted from the tool calls, not written by the model:")
            lines += [f"  {line}" for line in report]
        if reply:
            lines.append(f"Last reply: {reply[:300]}")
        open_items = self.parked_open()
        if open_items:
            lines.append(f"{len(open_items)} question{'s' if len(open_items) != 1 else ''} parked for you:")
            for item in open_items:
                lines.append(f"- {item['id']}: {item['question']} (default taken: {item['default']})")
        else:
            lines.append("No questions were parked.")
        text = "\n".join(lines)
        if llm is not None and rows:
            try:
                tightened = llm(
                    "Rewrite this catch-up for someone returning from a focus block. Three short lines at most: "
                    "what happened, what changed, what needs them. Keep every question id exactly. Plain text.\n\n" + text
                )
                if isinstance(tightened, str) and tightened.strip():
                    proof = "\n".join(f"  {line}" for line in report)
                    return tightened.strip() + (f"\n\nCounted from the tool calls, not written by the model:\n{proof}" if report else "")
            except Exception:
                pass
        return text

    def return_context(self, session_id: str) -> str:
        """Context injected into the first turn after a focus block, so the agent presents the
        catch-up and asks every parked question in one card."""
        handed = self.hand_back()
        focus = self._get("focus", {})
        kept = fmt_minutes(int(focus.get("last_minutes", 0)))
        lines = [
            f"Syrinx: the user is back from a focus block ({kept} kept). Before anything else, give a three-line catch-up "
            "of what you did and what changed while they were away.",
        ]
        report = self.away_report(session_id)
        if report:
            lines.append("After your catch-up, show this list exactly as written, under the heading "
                         "\"Counted by Syrinx\". It was counted by code from your tool calls; do not reword or drop lines:")
            lines += [f"  - {line}" for line in report]
        if handed:
            lines.append(
                f"Then ask ALL of these {len(handed)} parked questions in ONE clarify call (one card, several questions), "
                "or in one single message if you have no clarify tool here, "
                "with the default you already used marked as recommended, and redo any piece where they pick differently:"
            )
            for item in handed:
                lines.append(f"- {item['id']}: {item['question']} (default used: {item['default']})")
        held = self.offer_held()
        if held:
            labels = ", ".join(dict.fromkeys(item["label"] for item in held))
            where = "Put one more question per held action on the SAME card" if handed else \
                "Ask about them in ONE clarify call, one question per held action"
            lines.append(
                f"Syrinx also HELD {len(held)} action{'s' if len(held) != 1 else ''} that would have left this machine, "
                f"and none of them ran: {labels}. {where} (\"Run {held[0]['label']} now?\", choices: Run it now, Leave it). "
                "Run only the ones they approve, and only after they answer."
            )
        if not handed and not held:
            lines.append("No questions were parked. Say so in one line.")
        elif not handed:
            lines.append("No questions were parked.")
        return "\n".join(lines)

    def morning_context(self, items: list[dict[str, Any]], *, late: bool = False) -> str:
        count = f"{len(items)} request{'s' if len(items) != 1 else ''}"
        if late:
            lines = [
                f"Syrinx: the user chose /late, so the {count} Syrinx had queued for the morning come back now. "
                "Acknowledge in one line and start on the first one unless they redirect you:",
            ]
        else:
            lines = [
                f"Syrinx morning brief: the user queued {count} after their cutoff last night. Greet them in one "
                "line, list the requests, and start on the first one unless they redirect you:",
            ]
        for item in items:
            created = datetime.fromisoformat(item["created"])
            lines.append(f"- ({fmt_clock(created)}) {item['text']}")
        if not late:
            yesterday = (self.now().date() - timedelta(days=1)).isoformat()
            row = self._get("stats", {}).get("days", {}).get(yesterday, {})
            kept, parked = int(row.get("focus_minutes", 0)), int(row.get("questions_parked", 0))
            if kept or parked:
                lines.append(f"Also tell them in one short line: yesterday Syrinx kept {fmt_minutes(kept)} of focus "
                             f"and parked {parked} question{'s' if parked != 1 else ''}.")
            waiting = len(self.parked_open())
            if waiting:
                lines.append(f"{waiting} parked question{'s are' if waiting != 1 else ' is'} still waiting; "
                             "mention /catchup.")
        return "\n".join(lines)

    # ----- status and stats ------------------------------------------------------------------

    def status_line(self) -> str:
        focus = self.focus()
        parked = len(self.parked_open())
        if focus.get("active"):
            until = datetime.fromisoformat(focus["until"])
            line = f"Syrinx · focus until {fmt_clock(until)} · {fmt_minutes(self.focus_elapsed_minutes())} in"
        elif self.is_night():
            line = f"Syrinx · night until {fmt_clock(datetime.combine(self.now().date(), self.wake()))}"
        else:
            line = "Syrinx · open"
        if parked:
            line += f" · {parked} parked"
        held = len(self.held_open())
        if held:
            line += f" · {held} held"
        return line

    def stats(self) -> dict[str, Any]:
        stats = dict(self._get("stats", {}))
        stats.pop("days", None)
        return stats

    def receipt_text(self) -> str:
        stats = self._get("stats", {})
        minutes = int(stats.get("focus_minutes", 0))
        parked = int(stats.get("questions_parked", 0))
        batched = int(stats.get("questions_batched", 0))
        queued = int(stats.get("requests_queued", 0))
        urgent = int(stats.get("interruptions_urgent", 0))
        blocks = int(stats.get("blocks_ended", 0))
        lines = ["Syrinx receipt"]
        lines.append(f"Focus kept: {fmt_minutes(minutes)} across {blocks} block{'s' if blocks != 1 else ''}.")
        lines.append(f"Questions parked: {parked}, handed back in batches: {batched}, urgent interruptions: {urgent}.")
        lines.append(f"Late-night requests queued for the morning: {queued}.")
        kept, changed = int(stats.get("defaults_kept", 0)), int(stats.get("defaults_changed", 0))
        if kept + changed:
            lines.append(f"Defaults you kept: {kept} of {kept + changed}. That is how often the agent guessed right.")
        auto = int(stats.get("questions_auto_answered", 0))
        if auto:
            lines.append(f"Questions you never had to answer again: {auto}.")
        held = int(stats.get("actions_held", 0))
        if held:
            lines.append(f"Pushes, sends and deploys held until you were back: {held}.")
        necessary = int(stats.get("interruptions_necessary", 0))
        if necessary:
            lines.append(f"Approvals that still reached you during focus: {necessary}.")
        return "\n".join(lines)

    def week_text(self) -> str:
        """The last seven days, one line each, from the per-day counters."""
        days = self._get("stats", {}).get("days", {})
        lines = ["Syrinx, last 7 days"]
        today = self.now().date()
        for offset in range(6, -1, -1):
            day = (today - timedelta(days=offset)).isoformat()
            row = days.get(day, {})
            kept = fmt_minutes(int(row.get("focus_minutes", 0)))
            parked = int(row.get("questions_parked", 0))
            queued = int(row.get("requests_queued", 0))
            label = "today" if offset == 0 else datetime.fromisoformat(day).strftime("%a")
            lines.append(f"{label:>5}: {kept} focus, {parked} parked, {queued} queued")
        return "\n".join(lines)

    def card_data(self) -> dict[str, Any]:
        """Numbers only, for the shareable receipt card: totals plus seven daily rows."""
        stats = self._get("stats", {})
        days = stats.get("days", {})
        today = self.now().date()
        rows = []
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            row = days.get(day.isoformat(), {})
            rows.append({"label": day.strftime("%a"), "focus_minutes": int(row.get("focus_minutes", 0)),
                         "questions_parked": int(row.get("questions_parked", 0))})
        totals = {key: int(value) for key, value in stats.items() if key != "days" and isinstance(value, int)}
        return {"date": today.strftime("%b %d, %Y").replace(" 0", " "), "totals": totals, "days": rows}

    def status_text(self) -> str:
        focus = self.focus()
        lines = [self.status_line()]
        if focus.get("active"):
            lines.append(f"{fmt_minutes(self.focus_remaining_minutes())} left. /flow off ends it early.")
        cutoff = datetime.combine(self.now().date(), self.cutoff())
        wake = datetime.combine(self.now().date(), self.wake())
        night_state = "on" if bool(self.config.get("night_enabled", True)) else "off"
        lines.append(f"Night {night_state}: cutoff {fmt_clock(cutoff)}, morning brief {fmt_clock(wake)}.")
        open_items = self.parked_open()
        if open_items:
            lines.append(f"Parked: {len(open_items)}. /catchup hands them back.")
        queued = self.queued_open()
        if queued:
            lines.append(f"Queued for the morning: {len(queued)}.")
        return "\n".join(lines)
