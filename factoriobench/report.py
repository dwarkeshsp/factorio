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
        f"  mode        {summary['mode']}, seed {summary['seed']}, {'peaceful' if summary['peaceful'] else 'hostile'} natives"
        + (f", {'cease-fire' if summary['cease_fire'] else 'teams at war'}" if summary["mode"] == "versus" else ""),
        f"  stopped     {summary['stop']}" + (" (see log.jsonl for the error)" if summary.get("error") else ""),
        f"  game time   {summary['game_time']} of {summary['deadline_minutes']:g} minutes",
        f"  cost        ${summary['usd']:.2f}  ({sum(tokens.values()):,} tokens)",
        f"  integrity   {'clean' if summary['integrity_clean'] else 'NOT CLEAN' if summary['integrity_clean'] is False else 'unknown'}"
        f" ({summary['commands_denied']} console commands refused, {summary['commands_run']} run)",
    ]
    if summary.get("winner"):
        lines.append(f"  winner      {summary['winner']}")
    for team, result in summary["teams"].items():
        lines += [
            "",
            f"  team {team}: {', '.join(result['models'])}",
            f"    production score  {result['score']:,.0f}",
            f"    turns / cost      {result['turns']} / ${result['usd']:.2f}",
            f"    furthest          rung {result['furthest_rung']}: {result['furthest_label'] or 'none'}; "
            f"{result['technologies_researched']} technologies",
        ]
        for rung in milestones[team]["ladder"]:
            if rung["game_time"]:
                lines.append(f"      {rung['rung']:>2}  {rung['game_time']:>8}  {rung['label']}")
    return "\n".join(lines)


def timelapse(run_dir: Path, agent: str = "agent-1", fps: int = 6) -> Path:
    """An mp4 of one agent's end-of-turn screenshots, one frame per turn."""
    out = run_dir / f"timelapse-{agent}.mp4"
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-pattern_type", "glob",
         "-i", str(run_dir / "agents" / agent / "shots" / "[0-9][0-9][0-9][0-9][0-9].jpg"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {result.stderr.strip()}")
    return out
