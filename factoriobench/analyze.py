"""Compare runs: when each ladder rung was reached, in game time, turns and dollars."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .scoring import LADDER, game_clock

KEY_ITEMS = ["iron-plate", "copper-plate", "iron-gear-wheel", "electronic-circuit", "automation-science-pack"]


def read_run(run_dir: Path) -> list[dict[str, Any]]:
    """Everything the comparison needs from one run's log, finished or not: one entry per side."""
    agents: list[dict[str, str]] = []
    firsts: dict[str, dict[str, dict[str, Any]]] = {}
    snapshots: dict[str, dict[int, dict]] = {}
    last_round: dict[str, Any] = {}
    stop = None
    for line in (run_dir / "log.jsonl").read_text().splitlines():
        record = json.loads(line)
        event = record.get("event")
        if event == "start":
            agents = record.get("agents", [])
        elif event == "round":
            last_round = record
            by_force = record.get("new_by_force") or {"player": record.get("new") or []}
            for force, keys in by_force.items():
                for key in keys:
                    firsts.setdefault(force, {}).setdefault(
                        key, {"turn": record["turn"], "ticks": record["game_ticks"], "usd": record["usd"]})
        elif event == "snapshot":
            for force, snapshot in (record.get("snapshots") or {"player": record["snapshot"]}).items():
                snapshots.setdefault(force, {})[record["turn"]] = snapshot
        elif event == "end":
            stop = record.get("stop")
    forces = sorted({agent.get("force", "player") for agent in agents}) or ["player"]
    name = "/".join(run_dir.parts[-2:])
    return [{
        "name": name if len(forces) == 1 else f"{name} [{force}]",
        "agents": [agent["model"] for agent in agents if agent.get("force", "player") == force],
        "firsts": firsts.get(force, {}), "snapshots": snapshots.get(force, {}),
        "turns": last_round.get("turn", 0), "ticks": last_round.get("game_ticks", 0),
        "usd": last_round.get("usd", 0.0), "stop": stop,
    } for force in forces]


def furthest(run: dict[str, Any]) -> tuple[int, str]:
    best = (0, "none")
    for index, (key, label) in enumerate(LADDER, start=1):
        if key in run["firsts"]:
            best = (index, label)
    return best


def _count(table: Any, name: str) -> int:
    return int(table.get(name, 0)) if isinstance(table, dict) else 0


def compare(run_dirs: list[Path]) -> str:
    runs = [side for path in run_dirs for side in read_run(path)]
    lines = ["| Run | Agents | Turns | Game time | Cost | Furthest rung | Stop |", "|---|---|---:|---:|---:|---|---|"]
    for run in runs:
        rung, label = furthest(run)
        lines.append(f"| {run['name']} | {', '.join(run['agents'])} | {run['turns']} | {game_clock(run['ticks'])} | "
                     f"${run['usd']:.2f} | {rung} of {len(LADDER)}: {label} | {run['stop'] or 'running'} |")
    reached = [(key, label) for key, label in LADDER if any(key in run["firsts"] for run in runs)]
    if reached:
        lines += ["", "When each rung was first reached (game time / turn / dollars spent by then):", "",
                  "| Rung | " + " | ".join(run["name"] for run in runs) + " |", "|---|" + "---|" * len(runs)]
        for key, label in reached:
            cells = []
            for run in runs:
                first = run["firsts"].get(key)
                cells.append(f"{game_clock(first['ticks'])} / {first['turn']} / ${first['usd']:.2f}" if first else "-")
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
    checkpoints = sorted({turn for run in runs for turn in run["snapshots"] if turn % 100 == 0})
    if checkpoints:
        lines += ["", "Items produced by turn (" + ", ".join(KEY_ITEMS) + "):", "",
                  "| Turn | " + " | ".join(run["name"] for run in runs) + " |", "|---:|" + "---|" * len(runs)]
        for turn in checkpoints:
            cells = []
            for run in runs:
                snap = run["snapshots"].get(turn)
                cells.append(" / ".join(str(_count(snap.get("items"), item)) for item in KEY_ITEMS) if snap else "-")
            lines.append(f"| {turn} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
