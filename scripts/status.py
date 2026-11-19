#!/usr/bin/env python3
"""One line per run under a directory: where it is, the score, the cost, the tick rate.

  scripts/status.py runs/night1
"""
import json
import sys
import time
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "runs")
total = 0.0
for log in sorted(root.glob("*/log.jsonl")):
    pauses, usd, turns, last_t, stop = [], 0.0, 0, 0.0, ""
    for line in log.read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        last_t = row.get("t", last_t)
        if row["event"] == "pause":
            pauses.append(row)
            usd = row["usd"]
        elif row["event"] == "turn":
            turns += 1
        elif row["event"] == "end":
            stop, usd = row["stop"], row["usd"]
    total += usd
    if not pauses:
        print(f"{log.parent.name:28s} starting")
        continue
    last = pauses[-1]
    recent = [p["ups"] for p in pauses[-40:] if p.get("ups")]
    seconds = last["game_ticks"] // 60
    scores = "  ".join(f"{team} {score:,.0f}" for team, score in last["scores"].items())
    state = stop or f"running ({time.time() - last_t:.0f}s since last event)"
    print(f"{log.parent.name:28s} {seconds // 60:2d}:{seconds % 60:02d}  {scores:32s} turns {turns:4d}  ${usd:6.2f}  "
          f"ups {sum(recent) / max(1, len(recent)):4.0f}  {state}")
print(f"{'total':28s} ${total:.2f}")
