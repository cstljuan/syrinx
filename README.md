# Kairos

**Your agent is fast. Kairos makes sure it waits for the right moment.**

The Greeks had two words for time. *Chronos* is clock time. *Kairos* is the right moment. Hermes gives your agent a computer and a chat window. Kairos gives it manners about your attention.

Kairos is a Hermes Agent plugin. It does four things, all of them with hooks that no prompt or skill can do:

1. **Flow.** Start a focus block with `/flow 45`. While it runs, the agent's non-urgent questions are parked with the default it chose instead of pulling you back into the chat. The agent keeps working. Approvals and sudo prompts always reach you; Kairos never touches the approval system.
2. **Return.** When the block ends, your next message gets a three-line catch-up of what happened and what changed, and the agent asks every parked question in one card. Pick differently and it redoes that piece.
3. **Night.** After your cutoff (10:30 PM by default), a new request is queued instead of started, with a kind note. It arrives as a morning brief at your wake time, and the agent starts on it. `/late 20` is the guilt-free override.
4. **Receipt.** `/kairos receipt` shows the time it gave back: focus kept, questions batched, late nights queued. `/kairos week` shows the last seven days, and `/kairos card` saves the receipt as a shareable image, a cyanotype print of Argus asleep while Hermes plays to him, with your total in hand-painted numerals and the week as seven small feathers: each as tall as the focus you kept, the eye at its tip closed on a day you kept focus. It holds numbers only: no question text, no file names.

In the Hermes Desktop app and the TUI, a one-line status (`Kairos · focus until 3:45 PM · 12 min in · 2 parked`) is kept up to date in place.

In the Desktop app, Kairos also adds a **status-bar chip** (click it to start or end a block), a **Kairos pane** (Argus at the top, whose tail eyes close while you are in flow and open one by one for each question he is holding; then now, the parked questions with a "keep default" button and an answer field, the night queue, seven daily bars, the receipt with a "copy receipt card" button), and, if you have adopted a Hermes pet, the pet's speech bubble carries the Kairos line ("2 parked", "night until 08:00"). Answers typed in the pane reach the agent on its next turn.

### Auto-focus (optional, macOS)

Set `auto_focus: true` and Kairos opens a block on its own when you are active in another app (your editor, a browser), and ends it when a Hermes app or a terminal is in front again. Your next message then carries the catch-up. It reads two local facts, idle time (`ioreg`) and the front app's bundle id (`lsappinfo`), keeps neither, and is off by default.

## Why a peacock

Argus was the watchman with a hundred eyes, and nothing got past him. Hermes played him to sleep, one eye after another, and his eyes ended up in the peacock's tail. Kairos does the same to your agent's interruptions: while you are in flow every eye is shut, and one eye opens for each question waiting for you.

## Install

```bash
hermes plugins install https://github.com/cstljuan/kairos
hermes plugins enable kairos
```

Then, in any session:

```
/flow 45          start a 45 minute focus block
/flow off         end it early
/catchup          what happened, and the parked questions
/late 20          keep going past the cutoff for 20 minutes
/night 22:30 08:00   set the cutoff and the morning time
/kairos           status; /kairos receipt for the time receipt
/kairos week      the last seven days
/kairos card      save the receipt as a shareable image
```

Settings live under `plugins.entries.kairos.settings` (also editable in Desktop under Settings, Plugins):

| Key | Default | Meaning |
|---|---|---|
| `cutoff` | `"22:30"` | After this local time, new requests are queued for the morning. |
| `wake` | `"08:00"` | When the night ends and the morning brief is delivered. |
| `focus_minutes` | `45` | Length of `/flow` with no number. |
| `night_enabled` | `true` | Set `false` to keep only the focus features. |
| `auto_focus` | `false` | macOS only. Open and close focus blocks from presence (see above). |
| `auto_focus_minutes` | `30` | Length of an automatic block; extended while you stay in another app. |
| `hermes_apps` | `""` | Extra bundle ids, comma separated, that count as "you are with Hermes". |

## How it works

| Piece | Hermes surface |
|---|---|
| Park a question the agent tries to ask during a block | `pre_tool_call` on the built-in `clarify` tool returns a block directive with the parked defaults, so the agent continues |
| Let the agent park or escalate on its own | tools `kairos_park`, `kairos_interrupt`, `kairos_status` |
| Tell the agent how to behave during a block, deliver the catch-up and the morning brief | `pre_llm_call` context injection |
| Queue a late-night request | `pre_llm_call` block directive (the message is kept and delivered in the morning) |
| Record what happened for the catch-up | `post_tool_call` (tool names and file names only, never arguments) and `post_llm_call` |
| Count the interruptions that still had to reach you | `on_human_input_request` for approvals and sudo prompts |
| The live status line | `ctx.post_message` and `handle.edit` |
| Tighten the catch-up (optional) | `ctx.llm.complete` on the user's own active model, no overrides |
| Desktop chip, pane and pet lines | `desktop/plugin.js` on the Desktop plugin SDK; `dashboard/plugin_api.py` routes under `/api/plugins/kairos/`; `broadcast_plugin_event` for live updates |

State is profile-scoped plugin state (`ctx.state`), under the Hermes plugin data directory. Nothing is written into the plugin folder.

## Disclosure

- **No network calls.** Kairos makes none of its own. The optional catch-up tightening goes through `ctx.llm` on whatever provider and model you already use.
- **Shell commands: two, read-only, and only when you turn `auto_focus` on.** `ioreg -c IOHIDSystem -d 4` for the idle time and `lsappinfo front` / `lsappinfo info` for the front app's bundle id, at most once every 10 seconds, with a 3 second timeout. The bundle id is compared in memory and never written anywhere. With `auto_focus` off (the default) Kairos runs no commands at all.
- **No background processes, no binaries.** The Desktop half is plain ES module source that only imports the plugin SDK and React; the backend is a FastAPI router mounted by Hermes behind the dashboard's own auth gate, reachable only from the connected Desktop app.
- **Approvals are untouched.** Kairos never auto-approves, never answers a prompt, and never changes approval routing. It only blocks the agent's own `clarify` questions during a focus block and tells the agent to continue with the default it had in mind.
- **Stored data:** focus blocks and their lengths, parked questions and the defaults taken, queued late-night requests (the text of your message, so it can be delivered in the morning), per-session tool names with file basenames and durations, the last reply of each session (first 600 characters) for the catch-up, and counters. All of it stays in your Hermes profile's plugin state. `/kairos card` writes one file, `kairos-receipt.svg`, into the same plugin data folder; it contains counters only. `kairos_status` exposes only flags and counts to the model.
- **Unattended runs:** cron-driven turns are never blocked or queued. Night and Flow only act on turns a person started.
- **No telemetry.**

## Development

```bash
uv run --with pytest python -m pytest -q tests
hermes plugins doctor . --ci
hermes plugins validate . --install-deps
```

Built by [cstljuan](https://github.com/cstljuan) for the Hermes Agent Plugin Hackathon. MIT license.
