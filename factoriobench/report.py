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
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-pattern_type", "glob",
         "-i", str(run_dir / "agents" / agent / "shots" / "[0-9][0-9][0-9][0-9][0-9].jpg"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {result.stderr.strip()}")
    return out
