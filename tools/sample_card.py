"""Development helper: write a receipt card filled with a plausible week, to look at the design.

    python3 tools/sample_card.py out.svg
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import card  # noqa: E402
import core  # noqa: E402


def main(target: str) -> None:
    clock = {"t": datetime(2026, 11, 10, 15, 0)}
    syrinx = core.Syrinx(core.MemoryStore(), now=lambda: clock["t"])
    random.seed(3)
    for days_ago in range(6, -1, -1):
        clock["t"] = datetime(2026, 11, 10, 10, 0) - timedelta(days=days_ago)
        for _ in range(random.randint(0, 3)):
            syrinx.start_focus(random.choice([25, 45, 90]))
            syrinx.park("q", "d")
            clock["t"] += timedelta(minutes=200)
            syrinx.focus()
    syrinx.queue_for_morning("x")
    syrinx._bump("questions_batched", 5)
    Path(target).write_text(card.receipt_svg(syrinx.card_data()), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "syrinx-receipt-sample.svg")
