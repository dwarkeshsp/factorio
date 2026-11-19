#!/usr/bin/env python3
"""Turn the first night's runs (this machine's and the workers') into charts and one results file.

  scripts/analyze_night.py            # writes results/night1/

Runs that are missing or did not reach the deadline are left out of the charts and listed
separately, so this can be re-run as games finish.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from factoriobench import charts  # noqa: E402

RUNS = ROOT / "runs"
OUT = ROOT / "results" / "night1"
OUT.mkdir(parents=True, exist_ok=True)

NAMES = {
    "claude-opus-5-5": "Claude Opus 5.5", "claude-fable-5-2": "Claude Fable 5.2", "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5", "gpt-6.2-astra": "GPT-6.2 Astra", "gpt-6.2-sol": "GPT-6.2 Sol",
}


def load(path: str) -> dict | None:
    """A finished run's summary plus where it lives, or None."""
    summary = RUNS / path / "summary.json"
    if not summary.exists():
        return None
    data = json.loads(summary.read_text())
    data["path"] = path
    data["dir"] = RUNS / path
    return data


def done(path: str) -> dict | None:
    run = load(path)
    return run if run and run["stop"] == "deadline" else None


def score(run: dict, team: str = "player") -> float:
    return run["teams"][team]["score"]


def scores(paths: list[str]) -> list[float]:
    return [score(run) for run in map(done, paths) if run]


results: dict = {"charts": {}, "groups": {}}

# --- every run, for the table ------------------------------------------------------------
rows = []
for summary in sorted(RUNS.glob("*/*/summary.json")):
    if summary.parts[-3] == "shakedown":
        continue
    run = load(f"{summary.parts[-3]}/{summary.parts[-2]}")
    for team, result in run["teams"].items():
        rows.append({
            "run": run["path"], "mode": run["mode"], "team": team, "models": result["models"], "seed": run["seed"],
            "org": run.get("org", "flat"), "handbook": run.get("handbook"), "stop": run["stop"],
            "game_time": run["game_time"], "score": result["score"], "turns": result["turns"], "usd": result["usd"],
            "built": result["production"]["built"], "won": run.get("winner") == team,
            "technologies": result["technologies_researched"],
        })
results["runs"] = rows
results["total_usd"] = round(sum(json.loads(p.read_text())["usd"] for p in RUNS.glob("*/*/summary.json")
                                 if p.parts[-3] != "shakedown"), 2)

# --- 1. one agent, by model ----------------------------------------------------------------
solo_runs = {
    "gpt-6.2-astra": ["night1/solo-astra62"],
    "claude-fable-5-2": ["night1/solo-fable52"],
    "claude-opus-5-5": ["night1/solo-opus55", "w3/rep-solo-opus55-b", "w3/rep-solo-opus55-c", "w3/s2-solo-opus55"],
    "claude-sonnet-5-5": ["night1/solo-sonnet55"],
    "gpt-6.2-sol": ["night1/solo-sol62"],
    "claude-haiku-5-5": ["night1/solo-haiku55"],
}
solo = {}
for model, paths in solo_runs.items():
    finished = [run for run in map(done, paths) if run]
    if finished:
        values = [score(run) for run in finished]
        solo[model] = {"scores": values, "mean": sum(values) / len(values),
                       "usd": sum(run["usd"] for run in finished) / len(finished),
                       "turns": sum(run["teams"]["player"]["turns"] for run in finished) / len(finished),
                       "built": finished[0]["teams"]["player"]["production"]["built"]}
results["groups"]["solo"] = solo
if solo:
    results["charts"]["solo_scores"] = str(charts.bars(
        OUT / "solo-scores.png", [(NAMES[m], v["mean"]) for m, v in solo.items()],
        "One agent, twenty game minutes",
        "Production score at the deadline, playing alone by screen, mouse and keyboard (mean where a model played more than once)"))
    first = [(NAMES[m], RUNS / paths[0]) for m, paths in solo_runs.items() if done(paths[0])]
    results["charts"]["solo_over_time"] = str(charts.lines(
        OUT / "solo-over-time.png", first, "One agent, twenty game minutes", "Production score over game time, playing alone"))

# --- 2. does a team beat an individual? ----------------------------------------------------
scaling = {
    "seed 1001": {
        1: ["night1/solo-opus55", "w3/rep-solo-opus55-b", "w3/rep-solo-opus55-c"],
        2: ["night1/team2-opus55", "w1/gen1-team2", "w3/rep-team2-opus55-c"],
        4: ["night1/team4-opus55-r2", "w1/rep-team4-opus55-b"],
    },
    "seed 2002": {1: ["w3/s2-solo-opus55"], 2: ["w3/s2-team2-opus55"], 4: ["w3/s2-team4-opus55"]},
}
pooled = {n: [] for n in (1, 2, 4)}
results["groups"]["scaling"] = {}
for seed, sizes in scaling.items():
    results["groups"]["scaling"][seed] = {n: scores(paths) for n, paths in sizes.items()}
    for n, paths in sizes.items():
        pooled[n] += scores(paths)
if all(pooled.values()):
    labels = {1: "1 agent", 2: "2 agents", 4: "4 agents"}
    results["charts"]["team_scaling"] = str(charts.dots(
        OUT / "team-scaling.png", [(labels[n], pooled[n]) for n in (1, 2, 4)], "Does a team beat an individual?",
        "Claude Opus 5.5, team production score. Each dot is one 20-minute game on one of two maps; the bar is the mean"))
    results["charts"]["team_scaling_per_agent"] = str(charts.dots(
        OUT / "team-scaling-per-agent.png", [(labels[n], [v / n for v in pooled[n]]) for n in (1, 2, 4)],
        "Output per agent falls as the team grows",
        "Claude Opus 5.5, production score divided by team size", ylabel="Production score per agent"))
    means = {n: sum(v) / len(v) for n, v in pooled.items()}
    results["groups"]["scaling"]["pooled_mean"] = means
    results["groups"]["scaling"]["speedup"] = {n: means[n] / means[1] for n in means}
trio = [("1 agent", "w3/s2-solo-opus55"), ("2 agents", "w3/s2-team2-opus55"), ("4 agents", "w3/s2-team4-opus55")]
if all(done(p) for _, p in trio):
    results["charts"]["team_scaling_seed2"] = str(charts.lines(
        OUT / "team-scaling-seed2-over-time.png", [(label, RUNS / p) for label, p in trio],
        "One, two and four agents on the same map", "Claude Opus 5.5, team production score over game time (map seed 2002)"))

# --- 3. how a team of four is organised -----------------------------------------------------
org = {"No structure": ["night1/team4-opus55-r2", "w1/rep-team4-opus55-b"],
       "A manager": ["w4/org-manager-team4"],
       "Assigned roles": ["w4/org-roles-team4"]}
org_scores = {label: scores(paths) for label, paths in org.items()}
results["groups"]["org"] = org_scores
if sum(1 for v in org_scores.values() if v) >= 2:
    results["charts"]["org"] = str(charts.dots(
        OUT / "org-structures.png", [(label, v) for label, v in org_scores.items() if v], "Three ways to organise four agents",
        "Claude Opus 5.5, team of four, map seed 1001. Each dot is one 20-minute game"))

# --- 4. notes handed from one team to the next -----------------------------------------------
chain = [("Generation 1\n(no notes)", "w1/gen1-team2"), ("Generation 2", "w1/gen2-team2"), ("Generation 3", "w1/gen3-team2"),
         ("Generation 4", "w1/gen4-team2")]
chain_scores = [(label, score(run)) for label, run in ((label, done(p)) for label, p in chain) if run]
results["groups"]["handbook_chain"] = chain_scores
if len(chain_scores) >= 2:
    results["charts"]["handbook_chain"] = str(charts.dots(
        OUT / "handbook-chain.png", [(label, [value]) for label, value in chain_scores],
        "Did each team's notes help the next team?",
        "Two Claude Opus 5.5 agents per generation; each generation starts from the notes the one before it left"))

transfer = [("Claude Opus 5.5", "claude-opus-5-5", "w1/hb-opus55-from-fable52"),
            ("Claude Sonnet 5.5", "claude-sonnet-5-5", "night1/hb-sonnet55-from-fable52"),
            ("Claude Haiku 5.5", "claude-haiku-5-5", "night1/hb-haiku55-from-fable52"),
            ("Claude Fable 5.2", "claude-fable-5-2", "w1/hb-fable52-from-fable52")]
transfer_rows = []
for label, model, path in transfer:
    run = done(path)
    if run and model in solo:
        transfer_rows.append({"model": label, "alone": solo[model]["mean"], "with_notes": score(run)})
results["groups"]["handbook_transfer"] = transfer_rows

# --- 5. matches --------------------------------------------------------------------------------
for path in ("night1/vs2-opus55-astra62", "night1/vs2-fable52-astra62", "night1/ffa4-a"):
    run = load(path)
    if run and charts.score_series(run["dir"]):
        title = "Four teams, one map" if len(run["teams"]) > 2 else "Two teams, one map"
        results["charts"][path.split("/")[1]] = str(charts.versus(OUT / f"{path.split('/')[1]}.png", run["dir"], title))

# --- videos ------------------------------------------------------------------------------------
videos = {}
for row_path in sorted({row["run"] for row in rows}):
    for kind in ("overview", "screens"):
        video = RUNS / row_path / f"{kind}.mp4"
        if video.exists():
            target = OUT / "video" / f"{row_path.replace('/', '-')}-{kind}.mp4"
            target.parent.mkdir(exist_ok=True)
            shutil.copy(video, target)
            videos[f"{row_path}:{kind}"] = str(target.relative_to(ROOT))
results["videos"] = videos

results["charts"] = {key: str(Path(value).relative_to(ROOT)) for key, value in results["charts"].items()}
(OUT / "results.json").write_text(json.dumps(results, indent=2, default=str))

print(f"{len(rows)} team results from {len({r['run'] for r in rows})} runs; ${results['total_usd']} on the summaries")
print(json.dumps(results["groups"], indent=1, default=str)[:2500])
