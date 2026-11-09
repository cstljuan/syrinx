"""Kairos core: the state and the rules, with no Hermes imports.

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
TRACE_MAX = 60
PARKED_MAX = 40
QUEUE_MAX = 40
SUMMARY_MAX_CHARS = 80


class Store:
    """The two calls Kairos needs from storage. ``ctx.state`` already has this shape."""

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


def summarize_tool_call(tool_name: str, args: Any) -> str:
    """One short, safe line about a tool call. Never the full arguments: a command line or a
    message body can carry something private. Paths keep only their last component."""
    args = args if isinstance(args, dict) else {}
    name = str(tool_name or "tool")
    path = args.get("path") or args.get("file_path") or args.get("filename")
    if isinstance(path, str) and path.strip():
        return f"{name} {os.path.basename(path.rstrip('/'))[:SUMMARY_MAX_CHARS]}"
    if name == "terminal":
        command = str(args.get("command") or "").strip()
        head = command.split()[0] if command else ""
        return f"terminal {os.path.basename(head)[:40]}".strip()
    if name in ("web_search", "web_fetch", "web_extract"):
        query = str(args.get("query") or args.get("url") or "").strip()
        return f"{name} {query[:SUMMARY_MAX_CHARS]}".strip()
    if name == "delegate_task":
        return "delegate_task (subagent)"
    return name


class Kairos:
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
            return False

    # ----- parking ---------------------------------------------------------------------------

    def parked_open(self) -> list[dict[str, Any]]:
        return [item for item in self._get("parked", []) if item.get("status") == "parked"]

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
        args = args if isinstance(args, dict) else {}
        questions = args.get("questions")
        if isinstance(questions, dict):
            questions = [questions]
        if not isinstance(questions, list):
            return []
        items = []
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
            items.append(self.park(text, default or "your own best judgment", "asked while the user was heads-down",
                                   session_id=session_id, source="clarify"))
        return items

    def answer(self, item_id: str, text: str) -> Optional[dict[str, Any]]:
        with self._lock:
            parked = self._get("parked", [])
            for item in parked:
                if item.get("id") == item_id and item.get("status") == "parked":
                    item["status"] = "answered"
                    item["answer"] = str(text or "").strip()[:500]
                    item["answered"] = self.now().isoformat()
                    self._set("parked", parked)
                    return item
            return None

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
        """What ``pre_tool_call`` returns for a ``clarify`` call. ``None`` lets it through."""
        focus = self.focus()
        if not focus.get("active"):
            return None
        if self.consume_clarify_pass(session_id):
            self._bump("interruptions_urgent")
            return None
        items = self.park_from_clarify(args, session_id=session_id)
        until = datetime.fromisoformat(focus["until"])
        lines = [
            f"Kairos: the user is in a focus block until {fmt_clock(until)} and is not reading the chat. "
            "This question was parked for them, not shown.",
        ]
        for item in items:
            lines.append(f"- {item['id']}: \"{item['question']}\" parked. Default to use now: {item['default']}.")
        lines.append(
            "Continue the task with those defaults and say in your reply which defaults you took. "
            "Park anything else with kairos_park(question, default, why). Only if the task truly cannot "
            "move without an answer, call kairos_interrupt(question, why) and then ask with clarify."
        )
        return {"action": "block", "message": "\n".join(lines)}

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
            f"so Kairos queued this for the morning brief at {fmt_clock(datetime.combine(self.now().date(), wake))}. "
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
            rows = trace.setdefault(session_id or "*", [])
            rows.append({"t": self.now().isoformat(), "what": summarize_tool_call(tool_name, args),
                         "ms": int(duration_ms or 0)})
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
        return list(trace.get(session_id or "*", []))

    def clear_trace(self, session_id: str) -> None:
        with self._lock:
            trace = self._get("trace", {})
            trace.pop(session_id or "*", None)
            self._set("trace", trace)

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
        lines = ["Kairos catch-up"]
        focus = self._get("focus", {})
        if focus.get("last_minutes") is not None and not focus.get("active"):
            lines.append(f"Focus kept: {fmt_minutes(int(focus.get('last_minutes', 0)))}.")
        if rows:
            lines.append(f"The agent made {len(rows)} tool calls: {top}.")
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
                    return tightened.strip()
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
            f"Kairos: the user is back from a focus block ({kept} kept). Before anything else, give a three-line catch-up "
            "of what you did and what changed while they were away.",
        ]
        if handed:
            lines.append(
                f"Then ask ALL of these {len(handed)} parked questions in ONE clarify call (one card, several questions), "
                "with the default you already used marked as recommended, and redo any piece where they pick differently:"
            )
            for item in handed:
                lines.append(f"- {item['id']}: {item['question']} (default used: {item['default']})")
        else:
            lines.append("No questions were parked. Say so in one line.")
        return "\n".join(lines)

    def morning_context(self, items: list[dict[str, Any]], *, late: bool = False) -> str:
        count = f"{len(items)} request{'s' if len(items) != 1 else ''}"
        if late:
            lines = [
                f"Kairos: the user chose /late, so the {count} Kairos had queued for the morning come back now. "
                "Acknowledge in one line and start on the first one unless they redirect you:",
            ]
        else:
            lines = [
                f"Kairos morning brief: the user queued {count} after their cutoff last night. Greet them in one "
                "line, list the requests, and start on the first one unless they redirect you:",
            ]
        for item in items:
            created = datetime.fromisoformat(item["created"])
            lines.append(f"- ({fmt_clock(created)}) {item['text']}")
        return "\n".join(lines)

    # ----- status and stats ------------------------------------------------------------------

    def status_line(self) -> str:
        focus = self.focus()
        parked = len(self.parked_open())
        if focus.get("active"):
            until = datetime.fromisoformat(focus["until"])
            line = f"Kairos · focus until {fmt_clock(until)} · {fmt_minutes(self.focus_elapsed_minutes())} in"
        elif self.is_night():
            line = f"Kairos · night until {fmt_clock(datetime.combine(self.now().date(), self.wake()))}"
        else:
            line = "Kairos · open"
        if parked:
            line += f" · {parked} parked"
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
        lines = ["Kairos receipt"]
        lines.append(f"Focus kept: {fmt_minutes(minutes)} across {blocks} block{'s' if blocks != 1 else ''}.")
        lines.append(f"Questions parked: {parked}, handed back in batches: {batched}, urgent interruptions: {urgent}.")
        lines.append(f"Late-night requests queued for the morning: {queued}.")
        return "\n".join(lines)

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
