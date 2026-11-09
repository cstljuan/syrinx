"""Presence probe tests with a fake command runner. No macOS calls are made."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import presence  # noqa: E402

IOREG = '''+-o IOHIDSystem  <class IOHIDSystem, id 0x100000456, registered, matched, active, busy 0 (0 ms), retain 20>
    {
      "HIDIdleTime" = 4300000000
      "HIDParameters" = {"HIDKeyboardModifierMappingPairs"=()}
    }
'''


def fake_runner(front: str, idle_output: str = IOREG):
    def run(cmd):
        if cmd[0] == "ioreg":
            return idle_output
        if cmd[:2] == ["lsappinfo", "front"]:
            return "ASN:0x0-0x1a01a:\n"
        if cmd[:2] == ["lsappinfo", "info"]:
            return f'"CFBundleIdentifier"="{front}"\n'
        return ""
    return run


def test_idle_seconds_parses_nanoseconds():
    assert presence.idle_seconds(fake_runner("x")) == 4.3
    assert presence.idle_seconds(lambda cmd: "no such key") is None


def test_front_bundle_id():
    assert presence.front_bundle_id(fake_runner("com.apple.Safari")) == "com.apple.Safari"
    assert presence.front_bundle_id(lambda cmd: "") is None


def test_heads_down_rule():
    apps = presence.DEFAULT_HERMES_APPS
    assert presence.heads_down_elsewhere(idle=4.3, front="com.apple.Safari", hermes_apps=apps) is True
    assert presence.heads_down_elsewhere(idle=4.3, front="com.nousresearch.hermes", hermes_apps=apps) is False
    assert presence.heads_down_elsewhere(idle=900.0, front="com.apple.Safari", hermes_apps=apps) is False
    assert presence.heads_down_elsewhere(idle=None, front="com.apple.Safari", hermes_apps=apps) is None


def test_parse_apps_merges_defaults():
    apps = presence.parse_apps("com.microsoft.VSCode, com.apple.Terminal")
    assert "com.microsoft.VSCode" in apps and apps.count("com.apple.Terminal") == 1
    assert presence.parse_apps(None) == presence.DEFAULT_HERMES_APPS


def test_sample_is_none_off_macos(monkeypatch):
    monkeypatch.setattr(presence.platform, "system", lambda: "Linux")
    assert presence.sample(fake_runner("com.apple.Safari")) is None
