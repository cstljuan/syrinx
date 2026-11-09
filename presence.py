"""Optional presence probe for auto-focus (off by default, macOS only).

When ``auto_focus`` is on, Kairos asks two read-only questions of the OS: how long since the
last key or mouse event, and which app is in front. Both come from stock macOS tools with no
permission prompt: ``ioreg -c IOHIDSystem`` (HIDIdleTime) and ``lsappinfo`` (the front app's
bundle id). Nothing is stored: the bundle id is compared in memory and dropped.

The rule: if the person is active at the computer (idle under ``ACTIVE_SECONDS``) and the front
app is not Hermes or a terminal, they are heads-down somewhere else, and Kairos opens an automatic
focus block. When a Hermes app is in front again, the block ends and the catch-up follows.
"""

from __future__ import annotations

import platform
import re
import subprocess
from typing import Callable, Optional

ACTIVE_SECONDS = 120
DEFAULT_HERMES_APPS = (
    "com.nousresearch.hermes",
    "com.apple.Terminal",
    "com.googlecode.iterm2",
    "com.mitchellh.ghostty",
    "net.kovidgoyal.kitty",
    "dev.warp.Warp",
    "com.github.wez.wezterm",
    "io.alacritty",
)

Runner = Callable[[list[str]], str]


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3, check=False).stdout


def is_supported() -> bool:
    return platform.system() == "Darwin"


def idle_seconds(run: Runner = _run) -> Optional[float]:
    """Seconds since the last keyboard or mouse event, from IOHIDSystem (nanoseconds)."""
    try:
        out = run(["ioreg", "-c", "IOHIDSystem", "-d", "4"])
    except Exception:
        return None
    match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out or "")
    if not match:
        return None
    return int(match.group(1)) / 1_000_000_000


def front_bundle_id(run: Runner = _run) -> Optional[str]:
    """Bundle id of the frontmost app, through lsappinfo (no accessibility permission needed)."""
    try:
        front = run(["lsappinfo", "front"]).strip()
        if not front:
            return None
        info = run(["lsappinfo", "info", "-only", "bundleid", front])
    except Exception:
        return None
    match = re.search(r'"?CFBundleIdentifier"?\s*=\s*"?([A-Za-z0-9._-]+)"?', info or "")
    return match.group(1) if match else None


def parse_apps(value: object) -> tuple[str, ...]:
    """``hermes_apps`` setting: a comma-separated string or a list, merged with the defaults."""
    extra: list[str] = []
    if isinstance(value, str):
        extra = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple)):
        extra = [str(part).strip() for part in value if str(part).strip()]
    return tuple(dict.fromkeys(list(DEFAULT_HERMES_APPS) + extra))


def heads_down_elsewhere(*, idle: Optional[float], front: Optional[str],
                         hermes_apps: tuple[str, ...] = DEFAULT_HERMES_APPS) -> Optional[bool]:
    """True: active in another app. False: in a Hermes app. None: cannot tell."""
    if front is None or idle is None:
        return None
    if front in hermes_apps:
        return False
    return idle < ACTIVE_SECONDS


def sample(run: Runner = _run, hermes_apps: tuple[str, ...] = DEFAULT_HERMES_APPS) -> Optional[bool]:
    if not is_supported():
        return None
    return heads_down_elsewhere(idle=idle_seconds(run), front=front_bundle_id(run), hermes_apps=hermes_apps)
