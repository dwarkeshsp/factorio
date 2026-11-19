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


def overview_timelapse(run_dir: Path, fps: int = 12) -> Path:
    """An mp4 of the whole base from above, one frame every 20 game seconds, with a clock and score caption."""
    from PIL import Image, ImageDraw, ImageFont

    frames = sorted(run_dir.glob("agents/*/client/script-output/overview/*.jpg"))
    if not frames:
        raise SystemExit(f"{run_dir} has no overview frames")
    scores: list[tuple[int, dict]] = []
    for line in (run_dir / "log.jsonl").read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("event") == "pause":
            scores.append((row["game_ticks"], row.get("scores") or {}))
    config = json.loads((run_dir / "config.json").read_text())
    models: dict[str, list[str]] = {}
    for agent in config["agents"]:
        models.setdefault(agent["team"], []).append(agent["model"])
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    work = run_dir / "overview-frames"
    work.mkdir(exist_ok=True)
    for old in work.glob("*.jpg"):
        old.unlink()
    for index, frame in enumerate(frames):
        ticks = int(frame.stem) - 0  # overview frames are named by game ticks since the start of play
        at = {}
        for tick, values in scores:
            if tick <= ticks:
                at = values
        image = Image.open(frame).convert("RGB")
        draw = ImageDraw.Draw(image)
        seconds = max(0, ticks) // 60
        parts = [f"{seconds // 60}:{seconds % 60:02d}"]
        for team, value in at.items():
            who = team if len(at) > 1 else ""
            parts.append(f"{who + ' ' if who else ''}{' + '.join(m.replace('claude-', '') for m in models.get(team, []))}: {value:,.0f}")
        text = "    ".join(parts)
        box = draw.textbbox((0, 0), text, font=font)
        draw.rectangle((0, 0, box[2] + 28, box[3] + 22), fill=(15, 15, 15))
        draw.text((14, 9), text, font=font, fill=(245, 245, 240))
        image.save(work / f"{index:06d}.jpg", quality=88)
    out = run_dir / "overview.mp4"
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(work / "%06d.jpg"),
         "-c:v", "libx264", "-crf", "26", "-pix_fmt", "yuv420p", str(out)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {result.stderr.strip()}")
    for old in work.glob("*.jpg"):
        old.unlink()
    work.rmdir()
    return out


def grid_timelapse(run_dir: Path, step_seconds: float = 5.0, fps: int = 12) -> Path:
    """An mp4 of every agent's own screen side by side, one frame per `step_seconds` of game time,
    each cell showing what that agent last saw, under a clock and the scores."""
    from PIL import Image, ImageDraw, ImageFont

    config = json.loads((run_dir / "config.json").read_text())
    agents = config["agents"]
    shots: dict[str, list[tuple[int, str]]] = {a["name"]: [(0, "00000.jpg")] for a in agents}
    scores: list[tuple[int, dict]] = []
    last_tick = 0
    for line in (run_dir / "log.jsonl").read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("event") == "turn" and row.get("shot"):
            shots[row["agent"]].append((row.get("game_ticks", 0), row["shot"]))
        elif row.get("event") == "pause":
            scores.append((row["game_ticks"], row.get("scores") or {}))
            last_tick = row["game_ticks"]
    colors = {"red": (227, 73, 72), "blue": (42, 120, 214), "green": (0, 131, 0), "yellow": (237, 161, 0), "player": (90, 90, 90)}
    columns = 1 if len(agents) == 1 else 2
    rows = -(-len(agents) // columns)
    cell_w, cell_h, head = (1280, 720, 44) if len(agents) == 1 else (640, 360, 44)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
    except OSError:
        font = small = ImageFont.load_default()
    work = run_dir / "grid-frames"
    work.mkdir(exist_ok=True)
    for old in work.glob("*.jpg"):
        old.unlink()
    cache: dict[str, Image.Image] = {}
    step = int(step_seconds * 60)
    index = 0
    for tick in range(0, last_tick + 1, step):
        frame = Image.new("RGB", (cell_w * columns, head + cell_h * rows), (15, 15, 15))
        draw = ImageDraw.Draw(frame)
        at: dict = {}
        for when, values in scores:
            if when <= tick:
                at = values
        seconds = tick // 60
        parts = [f"{seconds // 60}:{seconds % 60:02d}"] + [
            (f"{team} {value:,.0f}" if len(at) > 1 else f"score {value:,.0f}") for team, value in at.items()]
        draw.text((14, 10), "     ".join(parts), font=font, fill=(245, 245, 240))
        for n, agent in enumerate(agents):
            name = agent["name"]
            current = shots[name][0][1]
            for when, shot in shots[name]:
                if when <= tick:
                    current = shot
            path = run_dir / "agents" / name / "shots" / current
            key = str(path)
            if key not in cache:
                cache.clear()  # keep memory flat: an agent's shot changes rarely within a few frames
                cache[key] = Image.open(path).convert("RGB").resize((cell_w, cell_h), Image.LANCZOS) if path.exists() \
                    else Image.new("RGB", (cell_w, cell_h), (30, 30, 30))
            x, y = (n % columns) * cell_w, head + (n // columns) * cell_h
            frame.paste(cache[key], (x, y))
            label = f"{name}  {agent['model'].replace('claude-', '')}"
            box = draw.textbbox((0, 0), label, font=small)
            draw.rectangle((x, y, x + box[2] + 22, y + box[3] + 12), fill=(15, 15, 15))
            draw.rectangle((x, y, x + 6, y + box[3] + 12), fill=colors.get(agent["team"], (90, 90, 90)))
            draw.text((x + 14, y + 4), label, font=small, fill=(245, 245, 240))
        frame.save(work / f"{index:06d}.jpg", quality=85)
        index += 1
    out = run_dir / "screens.mp4"
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(work / "%06d.jpg"),
         "-c:v", "libx264", "-crf", "27", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", str(out)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {result.stderr.strip()}")
    for old in work.glob("*.jpg"):
        old.unlink()
    work.rmdir()
    return out
