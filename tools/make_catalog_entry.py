"""Development helper: write the one file the catalog pull request adds.

    python3 tools/make_catalog_entry.py [repo-url] > syrinx.yaml

It pins the current commit, so run it only after that commit is pushed to the public repo. The image
and screenshot links point at that same commit, which makes them as fixed as the code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DESCRIPTION = (
    "Your agent is fast; Syrinx makes it wait for the right moment. In a focus block (/flow 45) the agent's "
    "questions are parked with the default it took and it keeps working; when you return you get a catch-up, "
    "a list counted by code from the tool calls (files changed, commands run, anything that left your machine, "
    "and how much work rests on unconfirmed defaults), and every question in one card. During the block a fixed list of outward actions (git push, "
    "publish, send, deploy) is held before it runs and offered back on that card. Settle a question once "
    "with /always and it is never asked again. Late-night requests become a morning brief. Deep-work hours, a "
    "question budget, a time receipt, a Desktop pane and Argus, a pet whose pose shows the state. "
    "Disclosure: pre_tool_call can block the built-in clarify tool (during a focus block, over the question "
    "budget you set, or when a standing answer covers it) and tells the agent which default to use, and "
    "during a focus block only it blocks tool calls that match a fixed list of outward actions (push, publish, "
    "gh create, curl with a body, ssh, docker push, kubectl, terraform, send/post/deploy/upload/pay tools), "
    "storing a label, never the command (a guard, not a sandbox: scripts, execute_code and browser or MCP "
    "tools still run); hold_outward: false turns that off; parked questions, held actions and queued requests "
    "are handed back only to the session that created them; "
    "pre_llm_call appends short blocks to your message (standing answers, focus notes, the hand-back, the "
    "morning brief) and, after your cutoff and only on cli, tui and desktop (or platforms you add with "
    "night_platforms), ends the turn to queue the request; post_tool_call stores tool "
    "names, file basenames and program names, never arguments, plus your answers to clarify cards; with "
    "auto_focus on (macOS, off by default) it runs ioreg and lsappinfo read-only; /syrinx pet writes the bundled "
    "sprite sheet through Hermes' pet store. No network calls of its own, approvals untouched; cron runs, "
    "subagents, the API server, kanban workers and messaging users are never refused at night."
)


def main() -> None:
    repo = sys.argv[1] if len(sys.argv) > 1 else "https://github.com/cstljuan/syrinx"
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    version = next(line.split(":", 1)[1].strip().strip('"') for line in (ROOT / "plugin.yaml").read_text().splitlines()
                   if line.startswith("version:"))
    raw = repo.replace("https://github.com/", "https://raw.githubusercontent.com/") + f"/{sha}"
    shots = ["flow-parked.jpg", "hold-return.jpg", "return-card.jpg", "receipt-card.jpg", "argus-poses.jpg"]
    lines = [
        "name: syrinx",
        "title: Syrinx",
        f"repo: {repo}",
        f"sha: {sha}",
        f'description: "{DESCRIPTION}"',
        "maintainer: cstljuan",
        "tier: community",
        "category: general",
        'requires_hermes: ">=0.23.0"',
        f"docs_url: {repo}#readme",
        f'version: "{version}"',
        f"image: {raw}/docs/hero.jpg",
        "screenshots:",
        *[f"  - {raw}/docs/screenshots/{name}" for name in shots],
        "readme: true",
        "platforms: []",
        "capabilities:",
        "  provides_tools:",
        "    - syrinx_park",
        "    - syrinx_interrupt",
        "    - syrinx_status",
        "    - syrinx_flow",
        "  provides_hooks:",
        "    - pre_tool_call",
        "    - post_tool_call",
        "    - pre_llm_call",
        "    - post_llm_call",
        "    - on_human_input_request",
        "    - on_human_input_resolved",
        "  provides_middleware: []",
        "  requires_env: []",
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
