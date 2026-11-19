#!/usr/bin/env python3
"""Build the charts, timelapses and tables for a directory of runs.

  scripts/night_report.py runs/night1 results/night1

Writes PNG charts, MP4 timelapses, chat logs and a results.json into the output directory.
Runs that are missing or unfinished are skipped, so it can be re-run as games finish.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from factoriobench import charts, report  # noqa: E402

root, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)

NAMES = {
    "claude-opus-5-5": "Claude Opus 5.5", "claude-fable-5-2": "Claude Fable 5.2", "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5", "gpt-6.2-astra": "GPT-6.2 Astra", "gpt-6.2-sol": "GPT-6.2 Sol",
}


def summary(name: str) -> dict | None:
    path = root / name / "summary.json"
    return json.loads(path.read_text()) if path.exists() else None


def score_at(name: str, minutes: float, team: str | None = None) -> float | None:
    series = charts.score_series(root / name)
    if not series:
        return None
    points = series[team] if team else next(iter(series.values()))
    best = None
    for at, score in points:
        if at <= minutes + 1e-6:
            best = score
    return best


def chat(name: str) -> list[dict]:
    log = root / name / "server" / "console.log"
    lines = []
    if log.exists():
        for line in log.read_text(errors="replace").splitlines():
            match = re.match(r"^(\S+ \S+) \[(CHAT|SHOUT)\] ([^:]+): (.*)$", line)
            if match:
                lines.append({"time": match[1], "kind": match[2].lower(), "player": match[3], "text": match[4]})
    return lines


results: dict = {"runs": {}, "charts": [], "videos": []}
finished = sorted(p.parent.name for p in root.glob("*/summary.json"))
for name in finished:
    s = summary(name)
    results["runs"][name] = {
        "mode": s["mode"], "stop": s["stop"], "game_time": s["game_time"], "usd": s["usd"], "winner": s.get("winner"),
        "integrity_clean": s["integrity_clean"], "wall_minutes": round(s["wall_seconds"] / 60),
        "teams": {team: {k: r[k] for k in ("models", "score", "gross_production", "usd", "turns", "furthest_label", "technologies_researched")}
                  | {"built": r["production"]["built"]} for team, r in s["teams"].items()},
        "chat_messages": len(chat(name)),
    }
    messages = chat(name)
    if messages:
        (out / f"{name}-chat.txt").write_text("\n".join(f"{m['time']} {m['player']}: {m['text']}" for m in messages) + "\n")

# 1. solo leaderboard
solos = [(name, summary(name)) for name in finished if name.startswith("solo-")]
solos = [(name, s) for name, s in solos if s["stop"] == "deadline"]
if solos:
    rows = [(NAMES.get(s["teams"]["player"]["models"][0], s["teams"]["player"]["models"][0]), s["teams"]["player"]["score"]) for _, s in solos]
    results["charts"].append(str(charts.bars(out / "solo-scores.png", rows, "One agent, twenty minutes",
                                             "Production score at the deadline, playing alone by screen, mouse and keyboard")))
    runs = [(NAMES.get(s["teams"]["player"]["models"][0], name), root / name) for name, s in solos]
    results["charts"].append(str(charts.lines(out / "solo-over-time.png", runs, "One agent, twenty minutes",
                                              "Production score over game time, playing alone")))

# 2. does a team beat an individual?
for model in ("opus55", "sonnet55", "haiku55", "astra62"):
    family = [(n, label) for n, label in ((f"solo-{model}", "1 agent"), (f"team2-{model}", "2 agents"), (f"team4-{model}", "4 agents"))
              if (root / n / "log.jsonl").exists() and charts.score_series(root / n)]
    if len(family) >= 2:
        runs = [(label, root / n) for n, label in family]
        results["charts"].append(str(charts.lines(out / f"team-scaling-{model}.png", runs, "Does a team beat an individual?",
                                                  f"Team production score over game time, {model}")))
        results["charts"].append(str(charts.lines(out / f"team-scaling-{model}-per-agent.png", runs, "Output per agent",
                                                  f"Production score divided by team size, {model}", per_agent=True)))
        results.setdefault("scaling", {})[model] = {
            label: {"at_10_min": score_at(n, 10), "at_20_min": score_at(n, 20), "usd": (summary(n) or {}).get("usd")}
            for n, label in family}

# 3. matches
for name in finished:
    s = summary(name)
    if s["mode"] == "versus":
        results["charts"].append(str(charts.versus(out / f"{name}.png", root / name)))

# 4. timelapses of the base from above
for name in finished:
    try:
        video = report.overview_timelapse(root / name, fps=12)
        target = out / f"{name}-overview.mp4"
        subprocess.run(["cp", str(video), str(target)], check=True)
        results["videos"].append(str(target))
    except SystemExit as err:
        print(f"no timelapse for {name}: {err}")

(out / "results.json").write_text(json.dumps(results, indent=2))
print(charts.table(root))
print(json.dumps(results.get("scaling", {}), indent=1))
