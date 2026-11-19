"""Read a finished or running run: its score, and a timelapse of what the model saw."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def load(run_dir: Path) -> tuple[dict, dict]:
    summary = json.loads((run_dir / "summary.json").read_text())
    milestones = json.loads((run_dir / "milestones.json").read_text())
    return summary, milestones


def render(run_dir: Path) -> str:
    summary, milestones = load(run_dir)
    tokens = summary.get("tokens") or {}
    lines = [
        f"{run_dir}",
        f"  agents      {', '.join(a['model'] for a in summary['agents'])}" + (f" (effort {summary['effort']})" if summary.get("effort") else ""),
        f"  map         seed {summary['seed']}, {'peaceful' if summary['peaceful'] else 'hostile'}",
        f"  stopped     {summary['stop']}" + (" (see log.jsonl for the error)" if summary.get("error") else ""),
        f"  turns       {summary['turns']}",
        f"  game time   {summary['game_time']}",
        f"  cost        ${summary['usd']:.2f}  ({sum(tokens.values()):,} tokens, {sum(a['compactions'] for a in summary['agents'])} compactions)",
        f"  rocket      {'launched' if summary['rocket_launched'] else 'not launched'}",
        f"  furthest    rung {summary['furthest_rung']} of {summary['rungs_total']}: {summary['furthest_label'] or 'none'}",
        f"  research    {summary['technologies_researched']} technologies",
        f"  integrity   {'clean' if summary['integrity_clean'] else 'NOT CLEAN' if summary['integrity_clean'] is False else 'unknown'}"
        f" ({summary['commands_denied']} console commands refused, {summary['commands_run']} run)",
        "",
        "  ladder",
    ]
    for rung in milestones["ladder"]:
        mark = rung["game_time"] or "   -   "
        lines.append(f"    {rung['rung']:>2}  {mark:>8}  {rung['label']}")
    return "\n".join(lines)


def timelapse(run_dir: Path, agent: str = "agent-1", fps: int = 6) -> Path:
    """An mp4 of one agent's end-of-turn screenshots, one frame per turn."""
    out = run_dir / f"timelapse-{agent}.mp4"
    result = subprocess.run(
        ["nice", "-n", "19", "ffmpeg", "-y", "-loglevel", "error", "-threads", "1", "-framerate", str(fps), "-pattern_type", "glob",
         "-i", str(run_dir / "agents" / agent / "shots" / "?????.jpg"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {result.stderr.strip()}")
    return out


def team_timelapse(run_dir: Path, speed: float = 40.0, height: int = 540) -> Path:
    """An mp4 of every agent's view side by side, on a common game clock.

    Each agent's end-of-turn screenshot stays up until its next one, for the game time between them
    divided by `speed`. Needs turn records that carry game ticks (the continuous schedule) or round records.
    """
    ticks: dict[str, dict[int, int]] = {}
    round_ticks: dict[int, int] = {}
    for line in (run_dir / "log.jsonl").read_text().splitlines():
        record = json.loads(line)
        if record.get("event") == "round":
            round_ticks[record["turn"]] = record["game_ticks"]
        elif record.get("event") == "turn" and record.get("shot"):
            if "game_ticks" in record:
                ticks.setdefault(record["agent"], {})[record["turn"]] = record["game_ticks"]
            else:
                ticks.setdefault(record["agent"], {})[record["turn"]] = -1
    inputs: list[str] = []
    lists = []
    end = max(round_ticks.values(), default=0)
    for agent in sorted(ticks):
        turns = sorted(ticks[agent])
        when = [ticks[agent][t] if ticks[agent][t] >= 0 else round_ticks.get(t, 0) for t in turns]
        lines = []
        for index, turn in enumerate(turns):
            shot = (run_dir / "agents" / agent / "shots" / f"{turn:05d}.jpg").resolve()
            if not shot.exists():
                continue
            until = when[index + 1] if index + 1 < len(turns) else end
            seconds = max(0.02, (until - when[index]) / 60 / speed)
            lines += [f"file '{shot}'", f"duration {seconds:.3f}"]
        listing = run_dir / f"timelapse-{agent}.txt"
        listing.write_text("\n".join(lines) + "\n")
        lists.append(listing)
        inputs += ["-f", "concat", "-safe", "0", "-i", str(listing)]
    out = run_dir / "timelapse-team.mp4"
    count = len(lists)
    scale = "".join(f"[{i}:v]scale=-2:{height},fps=12[v{i}];" for i in range(count))
    stack = "".join(f"[v{i}]" for i in range(count)) + (f"hstack=inputs={count}[out]" if count > 1 else "copy[out]")
    result = subprocess.run(
        ["nice", "-n", "19", "ffmpeg", "-y", "-loglevel", "error", "-threads", "1", *inputs,
         "-filter_complex", scale + stack, "-map", "[out]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
         "-pix_fmt", "yuv420p", "-threads", "1", str(out)],
        capture_output=True, text=True, check=False,
    )
    for listing in lists:
        listing.unlink()
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {result.stderr.strip()[:500]}")
    return out
