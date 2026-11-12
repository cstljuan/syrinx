"""Syrinx runtime: wires the rules in ``core.py`` to the Hermes plugin context.

Every hook callback is wrapped so it can never break a turn, accepts ``**kwargs`` for forward
compatibility, and stays fast (``pre_tool_call`` fails closed in Hermes if a callback hangs).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from . import card, core, presence, schemas

logger = logging.getLogger(__name__)

PRESENCE_CACHE_SECONDS = 10

_PLUGIN_DIR = Path(__file__).resolve().parent

DEBT_LIMIT = 25      # changing steps built on unconfirmed defaults before the agent is told to stop
NIGHT_LOCAL_PLATFORMS = ("cli", "tui", "desktop")   # where a person sits at this machine
OWNERS_MAX = 500     # subagent sessions remembered with the conversation that started them


def parse_platforms(value: Any) -> frozenset[str]:
    """``night_platforms``: a comma-separated string or a list of platform names, lower-cased."""
    if isinstance(value, (list, tuple, set, frozenset)):
        parts = [str(item) for item in value]
    else:
        parts = str(value or "").split(",")
    return frozenset(part.strip().lower() for part in parts if part.strip())

HELP = (
    "Syrinx commands\n"
    "/flow [minutes|off]    start or end a focus block (default from settings)\n"
    "/catchup               what happened, and hand back the parked questions\n"
    "/late [minutes]        keep working past the cutoff for a while\n"
    "/night HH:MM [HH:MM]   set the cutoff and, optionally, the morning time\n"
    "/always [q = a]        standing answers: settle a question once, never be asked again\n"
    "/syrinx [receipt|week] status, the time receipt, or the last 7 days\n"
    "/syrinx card           save the receipt as a shareable image (numbers only)\n"
    "/syrinx pet            add Argus, the Syrinx mascot, to your Hermes pets\n"
    "/syrinx demo           the whole loop in ten seconds, no model needed\n"
    "/flow weekdays 09:00-11:00   deep-work hours: a flow that starts by itself\n"
    "/syrinx budget N       at most N question cards an hour outside a flow\n"
    "/syrinx hold on|off    during a flow, hold pushes, sends and deploys until you are back (on by default)\n"
    "/syrinx auto on|off    auto-focus from presence (macOS)\n"
    "/syrinx night on|off   queue late-night requests, or not"
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
                logger.debug("syrinx: ctx.state.get failed, using memory", exc_info=True)
                self._broken = True
        return self._fallback.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if not self._broken:
            try:
                self._ctx.state.set(key, value)
                return
            except Exception:
                logger.debug("syrinx: ctx.state.set failed, using memory", exc_info=True)
                self._broken = True
        self._fallback.set(key, value)


class Runtime:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        config = {}
        for key, default in (("cutoff", "22:30"), ("wake", "08:00"), ("focus_minutes", 45), ("night_enabled", True),
                             ("auto_focus", False), ("auto_focus_minutes", 30), ("hermes_apps", ""),
                             ("question_budget", 0), ("hold_outward", True), ("night_platforms", "")):
            try:
                config[key] = ctx.get_config(key, default=default)
            except Exception:
                config[key] = default
        self.k = core.Syrinx(_CtxStore(ctx), config=config)
        self._status_handles: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._presence_run = presence._run
        self._presence_checked = 0.0
        self._hermes_apps = presence.parse_apps(config.get("hermes_apps"))
        self._night_platforms = parse_platforms(config.get("night_platforms"))
        self._owners: dict[str, str] = {}

    # ----- whose turn is this ----------------------------------------------------------------

    def _note_parent(self, session_id: str, parent_session_id: str) -> None:
        """A subagent runs in a session of its own. Remember which conversation started it, so what
        it parks or has held is handed back there, and nowhere else."""
        if not session_id or not parent_session_id or session_id == parent_session_id:
            return
        with self._lock:
            if len(self._owners) >= OWNERS_MAX:
                self._owners.pop(next(iter(self._owners)))
            self._owners[session_id] = parent_session_id

    def _sid(self, session_id: str = "", task_id: str = "") -> str:
        """The conversation a hook call belongs to: the session, or the one that delegated to it."""
        sid = session_id or task_id or ""
        for _ in range(8):
            parent = self._owners.get(sid)
            if not parent:
                break
            sid = parent
        return sid

    def _night_applies(self, platform: str, parent_session_id: str) -> bool:
        """The cutoff is for a person sitting at this machine. It applies on the interactive local
        surfaces (cli, tui, desktop) and on platforms the user opted in to with ``night_platforms``.
        Messaging platforms, the API server, kanban workers, subagents and any run with no platform
        are never refused."""
        if parent_session_id:
            return False
        name = str(platform or "").strip().lower()
        return bool(name) and (name in NIGHT_LOCAL_PLATFORMS or name in self._night_platforms)

    # ----- presence (auto-focus) -------------------------------------------------------------

    def presence_tick(self, *, force: bool = False) -> None:
        """Open or close an automatic focus block from the OS presence probe. Off unless
        ``auto_focus`` is set; never runs more than once per PRESENCE_CACHE_SECONDS."""
        try:
            if self.k.schedule_tick():
                self._changed("flow_on")
        except Exception:
            logger.debug("syrinx: schedule tick failed", exc_info=True)
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
        """True only while a scheduled (cron) run is executing. Unattended runs are never held back."""
        try:
            current = self.ctx.current_cron_execution
            if callable(current):          # Hermes exposes it as a method; older hosts as a value
                current = current()
            return current is not None
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
                logger.debug("syrinx: status post failed", exc_info=True)

    def _changed(self, kind: str) -> None:
        """Tell the Desktop half (pane, chip, pet bubble) that state moved. No-op without Desktop."""
        try:
            from hermes_cli.plugin_events import broadcast_plugin_event  # type: ignore

            broadcast_plugin_event("syrinx", "state.changed", {"kind": kind, "line": self.k.status_line()})
        except Exception:
            logger.debug("syrinx: broadcast skipped", exc_info=True)

    def _llm(self, prompt: str) -> str:
        result = self.ctx.llm.complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=240,
            temperature=0.2,
            purpose="syrinx.catchup",
        )
        return getattr(result, "text", "") or ""

    # ----- hooks -----------------------------------------------------------------------------

    def pre_tool_call(self, tool_name: str = "", args: Optional[dict] = None, task_id: str = "",
                      session_id: str = "", **kwargs: Any) -> Optional[dict]:
        try:
            if tool_name == "clarify":
                directive = self.k.clarify_directive(args or {}, session_id=self._sid(session_id, task_id))
                if directive is not None:
                    self._changed("parked")
                return directive
            if tool_name.startswith("syrinx_") or self._in_cron():
                return None
            # Hold: during a focus block the known outward actions wait. Unattended runs are never held.
            directive = self.k.hold_directive(tool_name, args or {}, session_id=self._sid(session_id, task_id))
            if directive is not None:
                self._changed("held")
            return directive
        except Exception:
            logger.debug("syrinx: pre_tool_call failed open", exc_info=True)
            return None

    def _learn_from_clarify(self, args: Any, result: Any) -> None:
        """Read the answers the user gave to a clarify card: close handed-back questions, and notice a
        question that got the same answer twice."""
        try:
            data = json.loads(result) if isinstance(result, str) else result
        except Exception:
            return
        if not isinstance(data, dict):
            return
        responses = data.get("responses")
        questions = core.clarify_questions(args)
        if not isinstance(responses, list):
            return
        learned = False
        for question, response in zip(questions, responses):
            if not isinstance(response, dict) or response.get("status") != "answered":
                continue
            answer = response.get("user_response")
            if isinstance(answer, list):
                answer = ", ".join(str(part) for part in answer)
            if self.k.note_answer(question["question"], answer):
                learned = True
        self._changed("learned" if learned else "answered")

    def post_tool_call(self, tool_name: str = "", args: Optional[dict] = None, result: str = "",
                       task_id: str = "", duration_ms: int = 0, session_id: str = "", **kwargs: Any) -> None:
        try:
            if tool_name.startswith("syrinx_"):
                return
            if tool_name == "clarify":
                self._learn_from_clarify(args, result)
            self.k.record_tool(self._sid(session_id, task_id), tool_name, args, duration_ms=duration_ms)
            self.presence_tick()
        except Exception:
            logger.debug("syrinx: post_tool_call failed", exc_info=True)

    def pre_llm_call(self, session_id: str = "", user_message: Any = "", is_first_turn: bool = False,
                     platform: str = "", parent_session_id: str = "", **kwargs: Any) -> Optional[Any]:
        try:
            if self._in_cron():
                return None
            text = user_message if isinstance(user_message, str) else ""
            contexts: list[str] = []
            self.presence_tick(force=True)
            self._note_parent(session_id, parent_session_id)
            if parent_session_id:
                # A subagent's turn. Its work is counted for the conversation that started it, and
                # that conversation gets the hand-back. Nothing is queued or handed over here.
                return None

            # Night: queue the request and stop the turn before any inference. Only for a person at
            # this machine, and only when the request can be given back to the same conversation.
            if (self.k.is_night() and session_id and text.strip() and not text.lstrip().startswith("/")
                    and self._night_applies(platform, parent_session_id)):
                self.k.queue_for_morning(text, session_id=session_id)
                self._changed("queued")
                return {"action": "block", "message": self.k.night_block_message()}

            # Start of a session: the questions the user has settled for good.
            if is_first_turn:
                standing = self.k.standing_context()
                if standing:
                    contexts.append(standing)

            # Morning: hand over what was queued, once.
            morning = self.k.take_morning_brief(session_id)
            if morning:
                contexts.append(self.k.morning_context(morning, late=self.k.late_active(), session_id=session_id))
                self._changed("morning")

            # Return from a focus block: catch-up plus the parked questions, once.
            if self.k.take_pending_return(session_id):
                contexts.append(self.k.return_context(session_id))
                self._changed("returned")

            # Answers typed in the Syrinx pane since the last turn.
            answered = self.k.take_answered(session_id)
            if answered:
                contexts.append(self.k.answers_context(answered))

            # During a block: tell the agent how to behave.
            focus = self.k.focus()
            if focus.get("active"):
                until = core.datetime.fromisoformat(focus["until"])
                contexts.append(
                    f"Syrinx: the user is in a focus block until {core.fmt_clock(until)} and will not read the chat "
                    "until then. Do not ask them anything now: park questions with syrinx_park(question, default, why) "
                    "and continue with sensible defaults, saying which ones you took. Use syrinx_interrupt only if the "
                    "task cannot move at all."
                    + (" If the task includes something that leaves this machine (push, publish, send, deploy), call it "
                       "once as you normally would: Syrinx will hold it, record it, and offer it back on the user's return "
                       "card. Do not skip it silently, and do not retry it once it is held." if self.k.hold_enabled() else "")
                )
                debt = self.k.assumption_debt(session_id)
                if debt >= DEBT_LIMIT:
                    contexts.append(
                        f"Syrinx: {debt} changing steps now rest on defaults the user has not confirmed. Stop stacking "
                        "work on them. Finish only what does not depend on those answers, then stop and say what is waiting."
                    )
            return {"context": "\n\n".join(contexts)} if contexts else None
        except Exception:
            logger.debug("syrinx: pre_llm_call failed open", exc_info=True)
            return None

    def post_llm_call(self, session_id: str = "", assistant_response: Any = "", **kwargs: Any) -> None:
        try:
            self.k.record_reply(session_id, assistant_response)
            if self.k.focus().get("active") or self.k.parked_open():
                self._post_status(session_id)
        except Exception:
            logger.debug("syrinx: post_llm_call failed", exc_info=True)

    def on_human_input_request(self, kind: str = "", request_id: str = "", **kwargs: Any) -> None:
        try:
            if kind in ("approval", "sudo") and self.k.focus().get("active"):
                self.k._bump("interruptions_necessary")
        except Exception:
            logger.debug("syrinx: on_human_input_request failed", exc_info=True)

    def on_human_input_resolved(self, **kwargs: Any) -> None:
        return None

    # ----- tools -----------------------------------------------------------------------------

    @staticmethod
    def _tool_args(args: Any, extra: dict[str, Any]) -> dict[str, Any]:
        """Hermes calls a tool as ``handler(args_dict, **context)``. Accept that, and plain keywords."""
        merged = dict(args) if isinstance(args, dict) else {}
        for key in ("question", "default", "why"):
            if key not in merged and key in extra:
                merged[key] = extra[key]
        return merged

    def tool_park(self, args: Any = None, *, task_id: str = "", session_id: str = "", **kwargs: Any) -> str:
        try:
            given = self._tool_args(args, kwargs)
            question = str(given.get("question") or "").strip()
            if not question:
                return _json_error("question is required")
            item = self.k.park(question, str(given.get("default") or ""), str(given.get("why") or ""),
                               session_id=self._sid(session_id, task_id))
            self._changed("parked")
            return _json({"parked": item["id"], "proceed_with": item["default"],
                          "note": "Continue with the default and say so in your reply."})
        except Exception as exc:
            return _json_error(f"syrinx_park failed: {exc}")

    def tool_interrupt(self, args: Any = None, *, task_id: str = "", session_id: str = "", **kwargs: Any) -> str:
        try:
            given = self._tool_args(args, kwargs)
            sid = self._sid(session_id, task_id)
            self.k.allow_next_clarify(sid)
            self.k.park(str(given.get("question") or ""), "", str(given.get("why") or ""), session_id=sid,
                        urgent=True, source="interrupt")
            return _json({"ok": True, "note": "Ask now with clarify. This counted as an interruption."})
        except Exception as exc:
            return _json_error(f"syrinx_interrupt failed: {exc}")

    def tool_flow(self, args: Any = None, *, task_id: str = "", session_id: str = "", **kwargs: Any) -> str:
        try:
            given = args if isinstance(args, dict) else kwargs
            minutes = int(given.get("minutes") or 0)
            if minutes <= 0:
                ended = self.k.end_focus("user said so")
                self._changed("flow_off")
                return _json({"ended": bool(ended.get("ended")), "parked": ended.get("parked", 0),
                              "note": "Hand back any parked questions in one card now."})
            focus = self.k.start_focus(minutes, source="said")
            self._post_status(session_id or task_id)
            self._changed("flow_on")
            return _json({"focus_until": focus["until"], "minutes": focus["minutes"],
                          "note": "Park questions with syrinx_park until then. Confirm in one short line."})
        except Exception as exc:
            return _json_error(f"syrinx_flow failed: {exc}")

    def tool_status(self, args: Any = None, *, task_id: str = "", session_id: str = "", **kwargs: Any) -> str:
        try:
            focus = self.k.focus()
            sid = self._sid(session_id, task_id) or "*"
            return _json({
                "focus_active": bool(focus.get("active")),
                "focus_until": focus.get("until") if focus.get("active") else None,
                "minutes_left": self.k.focus_remaining_minutes(),
                "night": self.k.is_night(),
                "parked": len(self.k.parked_open(sid)),
                # Questions already handed back to the user this turn and still waiting for an answer.
                "handed_back_waiting": len(self.k.handed_back_open(sid)),
            })
        except Exception as exc:
            return _json_error(f"syrinx_status failed: {exc}")

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
        # Deep-work hours: /flow weekdays 09:00-11:00, /flow hours, /flow hours clear
        if arg in ("hours", "schedule"):
            return self.k.windows_text()
        if arg in ("hours clear", "schedule clear"):
            count = self.k.clear_windows()
            self._changed("hours")
            return f"Removed {count} deep-work window{'s' if count != 1 else ''}."
        window = re.match(r"(daily|weekdays|weekends)\s+(\d{1,2}:\d{2})\s*(?:-|to)\s*(\d{1,2}:\d{2})$", arg)
        if window:
            try:
                made = self.k.add_window(*window.groups())
            except ValueError as exc:
                return f"Could not set that: {exc}."
            self.k.schedule_tick()
            self._changed("hours")
            return (f"Deep-work hours set: {made['days']} {made['start']} to {made['end']}. A flow starts by itself "
                    "then. /flow hours lists them, /flow off ends today's early.")
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
        if not session_id:
            return ("Syrinx cannot tell which conversation this is, so there is nothing to hand back here. "
                    "The Syrinx pane lists everything that is parked.")
        text = self.k.catchup_text(session_id, llm=llm)
        handed = self.k.hand_back(session_id)
        if handed:
            text += "\n\nReply with your answers in one message (quote the ids), or just say \"defaults are fine\"."
        return text

    def cmd_late(self, raw_args: str = "", **kwargs: Any) -> str:
        match = re.match(r"\s*(\d{1,3})", raw_args or "")
        until = self.k.late(int(match.group(1)) if match else None)
        self._changed("late")
        return f"Okay. Syrinx steps aside until {core.fmt_clock(until)}. It will remind you once after that."

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

    def _add_pet(self) -> str:
        """Put Argus among this profile's pets through Hermes' own pet store. Adopting him stays your call."""
        sheet = _PLUGIN_DIR / "assets" / "pet" / "argus" / "spritesheet.webp"
        try:
            data = sheet.read_bytes()
        except OSError:
            return "This copy of Syrinx has no pet art. Reinstall the plugin and try again."
        try:
            from agent.pet.store import register_local_pet  # type: ignore

            register_local_pet(data, slug="argus", display_name="Argus",
                               description="The hundred-eyed watchman Hermes played to sleep. He keeps your questions until the right moment.")
        except Exception:
            logger.debug("syrinx: could not add the pet", exc_info=True)
            return "Syrinx could not add Argus on this Hermes version. Pets need Hermes with the pet feature."
        return "Argus is now among your pets. Adopt him with /pet argus (and /pet off sends him away)."

    def _save_card(self) -> str:
        """Write the receipt card into the plugin's own data folder and say where it is."""
        svg = card.receipt_svg(self.k.card_data())
        try:
            folder = self.ctx.state.data_dir
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "syrinx-receipt.svg"
            path.write_text(svg, encoding="utf-8")
        except Exception:
            logger.debug("syrinx: could not save the card", exc_info=True)
            return "Syrinx could not save the card on this system.\n\n" + self.k.receipt_text()
        return f"Receipt card saved: {path}\nIt holds numbers only, no question text and no file names.\n\n" + self.k.receipt_text()

    def cmd_always(self, raw_args: str = "", **kwargs: Any) -> str:
        """/always, /always <question> = <answer>, /always yes N, /always forget N."""
        arg = (raw_args or "").strip()
        if not arg:
            return self.k.standing_text()
        head, _, rest = arg.partition(" ")
        if head.lower() == "forget":
            gone = self.k.forget_standing(rest)
            self._changed("standing")
            return f"Forgotten: {gone['question']}" if gone else "No standing answer with that number. /always lists them."
        if head.lower() in ("yes", "accept"):
            made = self.k.accept_suggestion(rest)
            self._changed("standing")
            return (f"Settled for good: {made['question']} -> {made['answer']}. The agent will not ask again."
                    if made else "No suggestion with that number. /always lists them.")
        question, sep, answer = arg.partition("=")
        if not sep or not question.strip() or not answer.strip():
            return "Use /always <question> = <answer>, for example: /always tabs or spaces = spaces"
        made = self.k.add_standing(question, answer)
        self._changed("standing")
        return f"Settled for good: {made['question']} -> {made['answer']}. The agent will not ask again."

    def cmd_syrinx(self, raw_args: str = "", **kwargs: Any) -> str:
        arg = (raw_args or "").strip().lower()
        if arg in ("receipt", "stats"):
            return self.k.receipt_text()
        if arg == "week":
            return self.k.week_text()
        if arg in ("help", "?"):
            return HELP
        if arg == "card":
            return self._save_card()
        if arg == "pet":
            return self._add_pet()
        if arg == "demo":
            return demo_text()
        budget = re.match(r"budget(?:\s+(\d{1,2}|off))?$", arg)
        if budget:
            if budget.group(1) is None:
                now = self.k.budget()
                return (f"Question budget: {now} card{'s' if now != 1 else ''} an hour outside a flow." if now else
                        "No question budget. /syrinx budget 3 lets the agent show you at most 3 question cards an hour.")
            value = self.k.set_budget(0 if budget.group(1) == "off" else int(budget.group(1)))
            self._changed("settings")
            return (f"Question budget set: {value} an hour. Extra questions are parked and come back with your next message."
                    if value else "Question budget off.")
        parts = arg.split()
        if parts and parts[0] == "hold" and (len(parts) == 1 or parts[1] in ("on", "off")):
            if len(parts) == 2:
                self.k.set_hold(parts[1] == "on")
                self._changed("settings")
            waiting = self.k.held_open()
            state = ("Hold on: during a flow, anything that leaves this machine (push, publish, send, deploy) waits "
                     "until you are back." if self.k.hold_enabled() else
                     "Hold off: outward actions run during a flow and are only flagged in the report.")
            if waiting:
                state += " Waiting now: " + ", ".join(item["label"] for item in waiting) + "."
            return state
        if len(parts) == 2 and parts[0] in ("auto", "night") and parts[1] in ("on", "off"):
            key = "auto_focus" if parts[0] == "auto" else "night_enabled"
            value = parts[1] == "on"
            if key == "auto_focus" and value and not presence.is_supported():
                return "Auto-focus needs macOS. On this system Syrinx cannot read idle time or the front app."
            self.k.config[key] = value
            try:
                self.ctx.set_config(key, value)
            except Exception:
                logger.debug("syrinx: set_config failed", exc_info=True)
            self._changed("settings")
            if key == "auto_focus":
                return ("Auto-focus on: a block opens when you are active in another app and ends when a Hermes app is in front."
                        if value else "Auto-focus off. /flow still works by hand.")
            return "Night on: requests after the cutoff are queued for the morning." if value else "Night off."
        return self.k.status_text() + "\n\n" + HELP


def demo_text() -> str:
    """The whole loop in ten seconds, on a private clock and a throwaway store. It runs the real rules,
    calls no model, and does not touch your state."""
    clock = {"t": core.datetime(2026, 1, 5, 9, 0)}
    k = core.Syrinx(core.MemoryStore(), now=lambda: clock["t"])
    out = ["Syrinx demo (real rules, private clock, your own state is untouched)", ""]

    k.add_standing("Which package manager?", "pnpm")
    out.append("09:00  You once said /always which package manager = pnpm")
    k.start_focus(45)
    out.append("09:00  /flow 45: " + k.status_line())
    card = {"questions": [{"question": "Which package manager should I use?", "choices": ["npm", "pnpm"]},
                          {"question": "Keep the old API route?", "choices": ["Keep it", "Remove it"]}]}
    verdict = k.clarify_directive(card, session_id="demo")
    out.append("09:07  The agent tries to ask two questions. Syrinx answers:")
    out += ["         " + line for line in verdict["message"].splitlines()[:6]]
    for name, args in (("write_file", {"path": "api.py"}), ("terminal", {"command": "pytest -q"}),
                       ("write_file", {"path": "test_api.py"})):
        clock["t"] += core.timedelta(minutes=6)
        k.record_tool("demo", name, args)
    clock["t"] += core.timedelta(minutes=6)
    k.hold_directive("terminal", {"command": "git push origin main"}, session_id="demo")
    out += ["", "09:31  The agent tries git push. Syrinx holds it until you are back."]
    clock["t"] = core.datetime(2026, 1, 5, 9, 46)
    k.focus()
    out += ["", "09:46  The block ends. " + k.status_line(), "       What the agent is told to show you, counted by code:"]
    out += ["         " + line for line in k.away_report("demo")]
    k.take_pending_return("demo")
    k.return_context("demo")
    k.note_answer("Keep the old API route?", "Remove it")
    out += ["", "09:47  You answer the one card: Remove it, and yes, push now. The agent redoes that piece, then pushes."]
    clock["t"] = core.datetime(2026, 1, 5, 23, 10)
    out += ["", "23:10  You send one more idea. " + k.night_block_message()]
    k.queue_for_morning("refactor the auth module", session_id="demo")
    out += ["", k.receipt_text(), "", "Try it for real: /flow 25, then ask the agent for something that needs a decision."]
    return "\n".join(out)


def register(ctx: Any) -> None:
    rt = Runtime(ctx)

    ctx.register_tool(name="syrinx_park", toolset="syrinx", schema=schemas.SYRINX_PARK, handler=rt.tool_park)
    ctx.register_tool(name="syrinx_interrupt", toolset="syrinx", schema=schemas.SYRINX_INTERRUPT,
                      handler=rt.tool_interrupt)
    ctx.register_tool(name="syrinx_status", toolset="syrinx", schema=schemas.SYRINX_STATUS, handler=rt.tool_status)
    ctx.register_tool(name="syrinx_flow", toolset="syrinx", schema=schemas.SYRINX_FLOW, handler=rt.tool_flow)

    ctx.register_hook("pre_tool_call", rt.pre_tool_call)
    ctx.register_hook("post_tool_call", rt.post_tool_call)
    ctx.register_hook("pre_llm_call", rt.pre_llm_call)
    ctx.register_hook("post_llm_call", rt.post_llm_call)
    ctx.register_hook("on_human_input_request", rt.on_human_input_request)
    ctx.register_hook("on_human_input_resolved", rt.on_human_input_resolved)

    # "/focus" is a built-in Hermes command (focus view), so the block is "/flow".
    ctx.register_command("flow", rt.cmd_focus, description="Start or end a Syrinx focus block",
                         args_hint="[minutes|off]")
    ctx.register_command("catchup", rt.cmd_catchup, description="What happened while you were away, and the parked questions")
    ctx.register_command("late", rt.cmd_late, description="Keep working past the Syrinx cutoff for a while",
                         args_hint="[minutes]")
    ctx.register_command("night", rt.cmd_night, description="Set the Syrinx cutoff and morning time",
                         args_hint="HH:MM [HH:MM]")
    ctx.register_command("always", rt.cmd_always, description="Standing answers: settle a question once so the agent never asks again",
                         args_hint="[<question> = <answer> | yes N | forget N]")
    ctx.register_command("syrinx", rt.cmd_syrinx, description="Syrinx status, receipt and help",
                         args_hint="[receipt|week|card|pet|help]")
    return rt
