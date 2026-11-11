"""Syrinx: your agent is fast. Syrinx makes it wait for the right moment.

Hermes Agent plugin. Parks non-urgent questions while you are heads-down, hands them back in one
pass with a catch-up when you return, queues late-night requests into a morning brief, and keeps a
receipt of the time it gave back. See README.md for the disclosure.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx):
    from . import runtime

    return runtime.register(ctx)
