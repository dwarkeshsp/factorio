#!/usr/bin/env python3
"""Fill README.md's results sections from results/night1 (the same words and numbers as the report page).

  scripts/build_readme.py      # docs/README.template.md -> README.md
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "night1"
P = json.loads((RES / "prose.json").read_text())
R = json.loads((RES / "results.json").read_text())

NAMES = {
    "claude-opus-5-5": "Claude Opus 5.5", "claude-fable-5-2": "Claude Fable 5.2", "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5", "gpt-6.2-astra": "GPT-6.2 Astra", "gpt-6.2-sol": "GPT-6.2 Sol",
}


def md(text: str) -> str:
    """The page's small HTML vocabulary as Markdown."""
    text = re.sub(r"<blockquote><p>(.*?)</p><cite>(.*?)</cite></blockquote>", r"> \1\n> *\2*\n\n", text, flags=re.S)
    text = re.sub(r"<li>(.*?)</li>", r"- \1\n", text, flags=re.S)
    text = text.replace("<strong>", "**").replace("</strong>", "**")
    return re.sub(r"<[^>]+>", "", text).strip()


def chart(key: str, alt: str) -> str:
    rel = R["charts"].get(key)
    return f"![{alt}]({rel})\n" if rel else ""


def table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(out) + "\n"


def match(path: str) -> str:
    teams = sorted((row for row in R["runs"] if row["run"] == path), key=lambda row: -row["score"])
    if not teams:
        return ""
    return table(["Team", "Models", "Score", "Turns", "Cost"], [
        [row["team"], NAMES[row["models"][0]] + (f" \u00d7{len(row['models'])}" if len(row["models"]) > 1 else ""),
         f"{row['score']:,.0f}", str(row["turns"]), f"${row['usd']:.2f}"] for row in teams])


solo = R["groups"]["solo"]
solo_table = table(["Model", "Score at 20 min", "Games", "Turns", "Cost per game", "Drills placed", "Furnaces placed"], [
    [NAMES[m], f"{v['mean']:,.0f}", str(len(v["scores"])), f"{v['turns']:,.0f}", f"${v['usd']:.2f}",
     str(v["built"].get("burner-mining-drill", 0)), str(v["built"].get("stone-furnace", 0))]
    for m, v in sorted(solo.items(), key=lambda kv: -kv[1]["mean"])])
transfer = table(["Model given Fable's notes", "Alone, no notes", "With the notes"], [
    [row["model"], f"{row['alone']:,.0f}", f"{row['with_notes']:,.0f}"] for row in R["groups"]["handbook_transfer"]])
org = table(["Organisation of a team of four", "Scores"], [
    [label, ", ".join(f"{v:,.0f}" for v in values) or "not run"] for label, values in R["groups"]["org"].items()])

results = "\n".join([
    md(P["headlines"]), "",
    "Videos sit beside each game under `runs/`: the bases from above (`overview.mp4`) and, for most games with "
    "several agents, every agent's screen side by side (`screens.mp4`).", "",
    "### One agent alone", "", md(P["solo"]), "", chart("solo_over_time", "Production score over game time, one agent alone"), solo_table,
    "### Does a team beat an individual?", "", md(P["teams"]), "",
    chart("team_scaling", "Team production score for one, two and four agents"),
    chart("team_scaling_per_agent", "Production score per agent"), md(P["team_quotes"]), "",
    "### Teams against each other", "", md(P["versus"]), "", chart("ffa4-a", "Four teams on one map"), match("night1/ffa4-a"),
    md(P["versus_quotes"]), "", md(P["two_v_two"]), "",
    chart("vs2-fable52-astra62", "Fable against Astra, two on two"), match("night1/vs2-fable52-astra62"),
    chart("vs2-opus55-astra62", "Opus against Astra, two on two"), match("night1/vs2-opus55-astra62"),
    "### Notes from one team to the next", "", md(P["notes"]), "",
    chart("handbook_chain", "Four generations of teams passing notes down"), transfer, md(P["notes_quotes"]), "",
    "### Three ways to organise four agents", "", md(P["org"]), "", chart("org", "Team of four: no structure, a manager, assigned roles"), org,
])

text = (ROOT / "docs" / "README.template.md").read_text()
text = text.replace("RESULTS_PLACEHOLDER", results.strip())
text = text.replace("CAVEATS_PLACEHOLDER", md(P["distrust"]))
text = text.replace("NEXT_PLACEHOLDER", md(P["next"]))
(ROOT / "README.md").write_text(text)
print("wrote README.md", len(text), "chars")
