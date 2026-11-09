"""Kairos runtime: wires the rules in ``core.py`` to the Hermes plugin context.

Every hook callback is wrapped so it can never break a turn, accepts ``**kwargs`` for forward
compatibility, and stays fast (``pre_tool_call`` fails closed in Hermes if a callback hangs).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Optional

from . import core, presence, schemas

logger = logging.getLogger(__name__)

PRESENCE_CACHE_SECONDS = 10

HELP = (
    "Kairos commands\n"
    "/flow [minutes|off]    start or end a focus block (default from settings)\n"
    "/catchup               what happened, and hand back the parked questions\n"
    "/late [minutes]        keep working past the cutoff for a while\n"
    "/night HH:MM [HH:MM]   set the cutoff and, optionally, the morning time\n"
    "/kairos [receipt|week] status, the time receipt, or the last 7 days\n"
    "/kairos auto on|off    auto-focus from presence (macOS)\n"
    "/kairos night on|off   queue late-night requests, or not"
)


def _json(data: Any) -> str:
    try:
        from tools.registry import tool_result  # type: ignore
        return tool_result(data)
    except Exception:
        return json.dumps(data, ensure_ascii=False)


def _json_error(message: str) -> str:
    try:
        from tools.registry import tool_error  # type: ignore
        return tool_error(message)
    except Exception:
        return json.dumps({"error": message}, ensure_ascii=False)


class _CtxStore(core.Store):
    """``ctx.state`` adapter that falls back to memory if state is unavailable."""

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx
        self._fallback = core.MemoryStore()
        self._broken = False

    def get(self, key: str, default: Any = None) -> Any:
        if not self._broken:
            try:
                return self._ctx.state.get(key, default=default)
            except Exception:
                logger.debug("kairos: ctx.state.get failed, using memory", exc_info=True)
                self._broken = True
        return self._fallback.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if not self._broken:
            try:
                self._ctx.state.set(key, value)
                return
            except Exception:
                logger.debug("kairos: ctx.state.set failed, using memory", exc_info=True)
                self._broken = True
        self._fallback.set(key, value)


class Runtime:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        config = {}
        for key, default in (("cutoff", "22:30"), ("wake", "08:00"), ("focus_minutes", 45), ("night_enabled", True),
                             ("auto_focus", False), ("auto_focus_minutes", 30), ("hermes_apps", "")):
            try:
                config[key] = ctx.get_config(key, default=default)
            except Exception:
                config[key] = default
        self.k = core.Kairos(_CtxStore(ctx), config=config)
        self._status_handles: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._presence_run = presence._run
        self._presence_checked = 0.0
        self._hermes_apps = presence.parse_apps(config.get("hermes_apps"))

    # ----- presence (auto-focus) -------------------------------------------------------------

    def presence_tick(self, *, force: bool = False) -> None:
        """Open or close an automatic focus block from the OS presence probe. Off unless
        ``auto_focus`` is set; never runs more than once per PRESENCE_CACHE_SECONDS."""
        if not bool(self.k.config.get("auto_focus", False)):
            return
        now = time.monotonic()
        if not force and now - self._presence_checked < PRESENCE_CACHE_SECONDS:
            return
        self._presence_checked = now
        if not presence.is_supported():
            return
        verdict = presence.heads_down_elsewhere(
            idle=presence.idle_seconds(self._presence_run),
            front=presence.front_bundle_id(self._presence_run),
            hermes_apps=self._hermes_apps,
        )
        focus = self.k.focus()
        if verdict is True and not focus.get("active"):
            minutes = int(self.k.config.get("auto_focus_minutes", 30) or 30)
            self.k.start_focus(minutes, source="auto")
            self._changed("flow_on")
        elif verdict is True and focus.get("active") and focus.get("source") == "auto":
            self.k.extend_focus(int(self.k.config.get("auto_focus_minutes", 30) or 30))
        elif verdict is False and focus.get("active") and focus.get("source") == "auto":
            self.k.end_focus("back")
            self._changed("flow_off")

    # ----- helpers ---------------------------------------------------------------------------

    def _in_cron(self) -> bool:
        try:
            return self.ctx.current_cron_execution is not None
        except Exception:
            return False

    def _post_status(self, session_id: str) -> None:
        """One live status line per session, edited in place where the surface allows it."""
        text = self.k.status_line()
        with self._lock:
            handle = self._status_handles.get(session_id)
            try:
                if handle is not None and getattr(handle, "ok", False):
                    handle.edit(text)
                else:
                    self._status_handles[session_id] = self.ctx.post_message(text)
            except Exception:
                logger.debug("kairos: status post failed", exc_info=True)

    def _changed(self, kind: str) -> None:
        """Tell the Desktop half (pane, chip, pet bubble) that state moved. No-op without Desktop."""
        try:
            from hermes_cli.plugin_events import broadcast_plugin_event  # type: ignore

            broadcast_plugin_event("kairos", "state.changed", {"kind": kind, "line": self.k.status_line()})
        except Exception:
            logger.debug("kairos: broadcast skipped", exc_info=True)

    def _llm(self, prompt: str) -> str:
        result = self.ctx.llm.complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=240,
            temperature=0.2,
            purpose="kairos.catchup",
        )
        return getattr(result, "text", "") or ""

    # ----- hooks -----------------------------------------------------------------------------

    def pre_tool_call(self, tool_name: str = "", args: Optional[dict] = None, task_id: str = "",
                      session_id: str = "", **kwargs: Any) -> Optional[dict]:
        try:
            if tool_name != "clarify":
                return None
            directive = self.k.clarify_directive(args or {}, session_id=session_id or task_id)
            if directive is not None:
                self._changed("parked")
            return directive
        except Exception:
            logger.debug("kairos: pre_tool_call failed open", exc_info=True)
            return None

    def post_tool_call(self, tool_name: str = "", args: Optional[dict] = None, result: str = "",
                       task_id: str = "", duration_ms: int = 0, session_id: str = "", **kwargs: Any) -> None:
        try:
            if tool_name.startswith("kairos_"):
                return
            self.k.record_tool(session_id or task_id, tool_name, args, duration_ms=duration_ms)
            self.presence_tick()
        except Exception:
            logger.debug("kairos: post_tool_call failed", exc_info=True)

    def pre_llm_call(self, session_id: str = "", user_message: Any = "", is_first_turn: bool = False,
                     platform: str = "", **kwargs: Any) -> Optional[Any]:
        try:
            if self._in_cron():
                return None
            text = user_message if isinstance(user_message, str) else ""
            contexts: list[str] = []
            self.presence_tick(force=True)

            # Night: queue the request and stop the turn before any inference.
            if self.k.is_night() and text.strip() and not text.lstrip().startswith("/"):
                self.k.queue_for_morning(text, session_id=session_id)
                self._changed("queued")
                return {"action": "block", "message": self.k.night_block_message()}

            # Morning: hand over what was queued, once.
            morning = self.k.take_morning_brief()
            if morning:
                contexts.append(self.k.morning_context(morning, late=self.k.late_active()))
                self._changed("morning")

            # Return from a focus block: catch-up plus the parked questions, once.
            if self.k.take_pending_return():
                contexts.append(self.k.return_context(session_id))
                self._changed("returned")

            # Answers typed in the Kairos pane since the last turn.
            answered = self.k.take_answered()
            if answered:
                contexts.append(self.k.answers_context(answered))

            # During a block: tell the agent how to behave.
            focus = self.k.focus()
            if focus.get("active"):
                until = core.datetime.fromisoformat(focus["until"])
                contexts.append(
                    f"Kairos: the user is in a focus block until {core.fmt_clock(until)} and will not read the chat "
                    "until then. Do not ask them anything now: park questions with kairos_park(question, default, why) "
                    "and continue with sensible defaults, saying which ones you took. Use kairos_interrupt only if the "
                    "task cannot move at all."
                )
            return {"context": "\n\n".join(contexts)} if contexts else None
        except Exception:
            logger.debug("kairos: pre_llm_call failed open", exc_info=True)
            return None

    def post_llm_call(self, session_id: str = "", assistant_response: Any = "", **kwargs: Any) -> None:
        try:
            self.k.record_reply(session_id, assistant_response)
            if self.k.focus().get("active") or self.k.parked_open():
                self._post_status(session_id)
        except Exception:
            logger.debug("kairos: post_llm_call failed", exc_info=True)

    def on_human_input_request(self, kind: str = "", request_id: str = "", **kwargs: Any) -> None:
        try:
            if kind in ("approval", "sudo") and self.k.focus().get("active"):
                self.k._bump("interruptions_necessary")
        except Exception:
            logger.debug("kairos: on_human_input_request failed", exc_info=True)

    def on_human_input_resolved(self, **kwargs: Any) -> None:
        return None

    # ----- tools -----------------------------------------------------------------------------

    def tool_park(self, question: str = "", default: str = "", why: str = "", task_id: str = "",
                  session_id: str = "", **kwargs: Any) -> str:
        try:
            if not str(question).strip():
                return _json_error("question is required")
            item = self.k.park(question, default, why, session_id=session_id or task_id)
            self._changed("parked")
            return _json({"parked": item["id"], "proceed_with": item["default"],
                          "note": "Continue with the default and say so in your reply."})
        except Exception as exc:
            return _json_error(f"kairos_park failed: {exc}")

    def tool_interrupt(self, question: str = "", why: str = "", task_id: str = "",
                       session_id: str = "", **kwargs: Any) -> str:
        try:
            sid = session_id or task_id
            self.k.allow_next_clarify(sid)
            self.k.park(question, "", why, session_id=sid, urgent=True, source="interrupt")
            return _json({"ok": True, "note": "Ask now with clarify. This counted as an interruption."})
        except Exception as exc:
            return _json_error(f"kairos_interrupt failed: {exc}")

    def tool_status(self, **kwargs: Any) -> str:
        try:
            focus = self.k.focus()
            return _json({
                "focus_active": bool(focus.get("active")),
                "focus_until": focus.get("until") if focus.get("active") else None,
                "minutes_left": self.k.focus_remaining_minutes(),
                "night": self.k.is_night(),
                "parked": len(self.k.parked_open()),
            })
        except Exception as exc:
            return _json_error(f"kairos_status failed: {exc}")

    # ----- slash commands --------------------------------------------------------------------

    def cmd_focus(self, raw_args: str = "", *, session_id: str = "", **kwargs: Any) -> str:
        arg = (raw_args or "").strip().lower()
        if arg in ("off", "stop", "end"):
            ended = self.k.end_focus("manual")
            if not ended.get("ended"):
                return "No focus block is running."
            self._changed("flow_off")
            tail = f" {ended['parked']} question{'s' if ended['parked'] != 1 else ''} parked; /catchup hands them back." \
                if ended.get("parked") else ""
            return f"Focus ended: {core.fmt_minutes(ended['minutes'])} kept.{tail}"
        if arg in ("status", "?"):
            return self.k.status_text()
        minutes = None
        match = re.match(r"(\d{1,3})", arg)
        if match:
            minutes = int(match.group(1))
        focus = self.k.start_focus(minutes)
        until = core.datetime.fromisoformat(focus["until"])
        self._post_status(session_id)
        self._changed("flow_on")
        return (f"Focus until {core.fmt_clock(until)} ({focus['minutes']} min). The agent keeps working and parks its "
                "questions. Approvals still reach you. /flow off ends it early.")

    def cmd_catchup(self, raw_args: str = "", *, session_id: str = "", **kwargs: Any) -> str:
        llm = None
        try:
            if self.ctx.llm is not None:
                llm = self._llm
        except Exception:
            llm = None
        text = self.k.catchup_text(session_id, llm=llm)
        handed = self.k.hand_back()
        if handed:
            text += "\n\nReply with your answers in one message (quote the ids), or just say \"defaults are fine\"."
        return text

    def cmd_late(self, raw_args: str = "", **kwargs: Any) -> str:
        match = re.match(r"\s*(\d{1,3})", raw_args or "")
        until = self.k.late(int(match.group(1)) if match else None)
        self._changed("late")
        return f"Okay. Kairos steps aside until {core.fmt_clock(until)}. It will remind you once after that."

    def cmd_night(self, raw_args: str = "", **kwargs: Any) -> str:
        parts = (raw_args or "").split()
        if not parts:
            return self.k.status_text()
        try:
            night = self.k.set_night_times(parts[0], parts[1] if len(parts) > 1 else None)
        except ValueError as exc:
            return f"{exc}. Use /night 22:30 08:00"
        cutoff = core.datetime.combine(self.k.now().date(), self.k.cutoff())
        wake = core.datetime.combine(self.k.now().date(), self.k.wake())
        return f"Night set: cutoff {core.fmt_clock(cutoff)}, morning brief {core.fmt_clock(wake)}."

    def cmd_kairos(self, raw_args: str = "", **kwargs: Any) -> str:
        arg = (raw_args or "").strip().lower()
        if arg in ("receipt", "stats"):
            return self.k.receipt_text()
        if arg == "week":
            return self.k.week_text()
        if arg in ("help", "?"):
            return HELP
        parts = arg.split()
        if len(parts) == 2 and parts[0] in ("auto", "night") and parts[1] in ("on", "off"):
            key = "auto_focus" if parts[0] == "auto" else "night_enabled"
            value = parts[1] == "on"
            if key == "auto_focus" and value and not presence.is_supported():
                return "Auto-focus needs macOS. On this system Kairos cannot read idle time or the front app."
            self.k.config[key] = value
            try:
                self.ctx.set_config(key, value)
            except Exception:
                logger.debug("kairos: set_config failed", exc_info=True)
            self._changed("settings")
            if key == "auto_focus":
                return ("Auto-focus on: a block opens when you are active in another app and ends when a Hermes app is in front."
                        if value else "Auto-focus off. /flow still works by hand.")
            return "Night on: requests after the cutoff are queued for the morning." if value else "Night off."
        return self.k.status_text() + "\n\n" + HELP


def register(ctx: Any) -> None:
    rt = Runtime(ctx)

    ctx.register_tool(name="kairos_park", toolset="kairos", schema=schemas.KAIROS_PARK, handler=rt.tool_park)
    ctx.register_tool(name="kairos_interrupt", toolset="kairos", schema=schemas.KAIROS_INTERRUPT,
                      handler=rt.tool_interrupt)
    ctx.register_tool(name="kairos_status", toolset="kairos", schema=schemas.KAIROS_STATUS, handler=rt.tool_status)

    ctx.register_hook("pre_tool_call", rt.pre_tool_call)
    ctx.register_hook("post_tool_call", rt.post_tool_call)
    ctx.register_hook("pre_llm_call", rt.pre_llm_call)
    ctx.register_hook("post_llm_call", rt.post_llm_call)
    ctx.register_hook("on_human_input_request", rt.on_human_input_request)
    ctx.register_hook("on_human_input_resolved", rt.on_human_input_resolved)

    # "/focus" is a built-in Hermes command (focus view), so the block is "/flow".
    ctx.register_command("flow", rt.cmd_focus, description="Start or end a Kairos focus block",
                         args_hint="[minutes|off]")
    ctx.register_command("catchup", rt.cmd_catchup, description="What happened while you were away, and the parked questions")
    ctx.register_command("late", rt.cmd_late, description="Keep working past the Kairos cutoff for a while",
                         args_hint="[minutes]")
    ctx.register_command("night", rt.cmd_night, description="Set the Kairos cutoff and morning time",
                         args_hint="HH:MM [HH:MM]")
    ctx.register_command("kairos", rt.cmd_kairos, description="Kairos status, receipt and help",
                         args_hint="[receipt|help]")
    return rt
