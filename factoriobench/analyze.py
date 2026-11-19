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
    start_tick = 0
    for line in (run_dir / "log.jsonl").read_text().splitlines():
        record = json.loads(line)
        event = record.get("event")
        if event == "start":
            agents = record.get("agents", [])
            start_tick = record.get("start_tick", 0)
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
        "usd": last_round.get("usd", 0.0), "stop": stop, "start_tick": start_tick,
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
    minutes = [m for m in (5, 10, 15, 20, 25, 30, 40, 50) if any(at_game_minute(run, m) for run in runs)]
    if minutes:
        lines += ["", "Items produced by game time (same items; from the last snapshot at or before that time, "
                  "taken every 25 turns, so slightly behind):", "",
                  "| Game minutes | " + " | ".join(run["name"] for run in runs) + " |", "|---:|" + "---|" * len(runs)]
        for minute in minutes:
            cells = []
            for run in runs:
                snap = at_game_minute(run, minute)
                cells.append(" / ".join(str(_count(snap.get("items"), item)) for item in KEY_ITEMS) if snap else "-")
            lines.append(f"| {minute} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def at_game_minute(run: dict[str, Any], minute: int) -> dict | None:
    """The last snapshot taken at or before a game time, if the run got that far."""
    limit = minute * 60 * 60
    if run["ticks"] < limit:
        return None
    best = None
    for turn in sorted(run["snapshots"]):
        snapshot = run["snapshots"][turn]
        if snapshot["tick"] - run["start_tick"] <= limit:
            best = snapshot
    return best


def production_curve(run_dir: Path, force: str = "player") -> list[tuple[float, int, dict[str, float]]]:
    """(game minutes, turn, items produced so far) at the start, at every snapshot and at the end of a run."""
    start_tick = 0
    points: list[tuple[float, int, dict[str, float]]] = [(0.0, 0, {})]
    last_round: dict[str, Any] = {}
    for line in (run_dir / "log.jsonl").read_text().splitlines():
        record = json.loads(line)
        event = record.get("event")
        if event == "start":
            start_tick = record.get("start_tick", 0)
        elif event == "round":
            last_round = record
        elif event == "snapshot":
            snapshot = (record.get("snapshots") or {"player": record["snapshot"]}).get(force)
            if snapshot:
                items = snapshot["items"] if isinstance(snapshot["items"], dict) else {}
                points.append(((snapshot["tick"] - start_tick) / 3600, record["turn"], items))
        elif event == "end" and last_round:
            side = (record.get("sides") or {}).get(force) or record
            items = (side.get("production") or {}).get("items") or {}
            points.append((last_round["game_ticks"] / 3600, last_round["turn"], items))
    return points


def produced_at(points: list[tuple[float, int, dict[str, float]]], minute: float, item: str) -> float | None:
    """Production of one item at a game time, interpolated between snapshots; None past the end of the run."""
    if minute > points[-1][0]:
        return None
    for (m0, _, a), (m1, _, b) in zip(points, points[1:]):
        if m0 <= minute <= m1:
            share = (minute - m0) / (m1 - m0) if m1 > m0 else 0.0
            return a.get(item, 0) + share * (b.get(item, 0) - a.get(item, 0))
    return float(points[-1][2].get(item, 0))


def team_ratio(solo_dir: Path, team_dir: Path, items: tuple[str, ...] = ("iron-plate", "automation-science-pack")) -> str:
    """Team output over solo output at equal game time, every five game minutes both runs reached."""
    solo, team = production_curve(solo_dir), production_curve(team_dir)
    lines = ["| Game minutes | " + " | ".join(f"{item}: solo | team | ratio" for item in items) + " |",
             "|---:|" + "---:|---:|---:|" * len(items)]
    minute = 5
    while minute <= min(solo[-1][0], team[-1][0]):
        cells = []
        for item in items:
            a, b = produced_at(solo, minute, item), produced_at(team, minute, item)
            cells.append(f"{a:.0f} | {b:.0f} | {b / a:.2f}" if a else f"{a:.0f} | {b:.0f} | –")
        lines.append(f"| {minute} | " + " | ".join(cells) + " |")
        minute += 5
    return "\n".join(lines)
