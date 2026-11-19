#!/usr/bin/env python3
"""Build the one-page report of the first night from results/night1/results.json.

  scripts/build_page.py        # writes results/night1/page/index.html and copies the charts and videos beside it
"""
import html
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "night1"
PAGE = RES / "page"
PAGE.mkdir(parents=True, exist_ok=True)
R = json.loads((RES / "results.json").read_text())
G = R["groups"]

NAMES = {
    "claude-opus-5-5": "Claude Opus 5.5", "claude-fable-5-2": "Claude Fable 5.2", "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5", "gpt-6.2-astra": "GPT-6.2 Astra", "gpt-6.2-sol": "GPT-6.2 Sol",
}
LAB = {"claude": "Anthropic", "gpt": "OpenAI"}


def n(value: float) -> str:
    return f"{value:,.0f}"


def usd(value: float) -> str:
    return f"${value:,.2f}"


def run(path: str) -> list[dict]:
    return [row for row in R["runs"] if row["run"] == path]


def team(path: str, name: str = "player") -> dict | None:
    return next((row for row in run(path) if row["team"] == name), None)


def chart(key: str, alt: str) -> str:
    rel = R["charts"].get(key)
    if not rel:
        return ""
    src = ROOT / rel
    shutil.copy(src, PAGE / src.name)
    return f'<figure class="chart"><img src="{src.name}" alt="{html.escape(alt)}"></figure>'


def video(src: Path, caption: str, poster_at: float = 30.0) -> str:
    """A video beside the page, with a frame from part-way through as its poster."""
    if not src.exists():
        return ""
    name = "-".join(src.parts[-3:])
    shutil.copy(src, PAGE / name)
    poster = name.replace(".mp4", ".jpg")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(poster_at), "-i", str(src), "-frames:v", "1",
                    "-q:v", "4", str(PAGE / poster)], check=False)
    poster_attr = f' poster="{poster}"' if (PAGE / poster).exists() else ""
    return (f'<figure class="video"><video controls muted playsinline preload="metadata" src="{name}"{poster_attr}></video>'
            f"<figcaption>{caption}</figcaption></figure>")


def quote(who: str, text: str) -> str:
    return f'<blockquote><p>{html.escape(text)}</p><cite>{html.escape(who)}</cite></blockquote>'


runs_done = sorted({row["run"] for row in R["runs"] if row["stop"] == "deadline"})
runs_all = sorted({row["run"] for row in R["runs"]})
solo = G["solo"]
scal = G["scaling"]
means, speed = scal.get("pooled_mean", {}), scal.get("speedup", {})

# ----------------------------------------------------------------------------- solo table
solo_rows = ""
for model, v in sorted(solo.items(), key=lambda kv: -kv[1]["mean"]):
    built = v["built"]
    games = len(v["scores"])
    spread = f' <span class="dim">({n(min(v["scores"]))} to {n(max(v["scores"]))}, {games} games)</span>' if games > 1 else ""
    solo_rows += (f"<tr><td>{NAMES[model]}</td><td>{LAB[model.split('-')[0]]}</td><td class='num'>{n(v['mean'])}{spread}</td>"
                  f"<td class='num'>{n(v['turns'])}</td><td class='num'>{usd(v['usd'])}</td>"
                  f"<td class='num'>{built.get('burner-mining-drill', 0)}</td><td class='num'>{built.get('stone-furnace', 0)}</td></tr>")

# ----------------------------------------------------------------------------- matches
ffa = {row["team"]: row for row in run("night1/ffa4-a")}
vs_oa = {row["team"]: row for row in run("night1/vs2-opus55-astra62")}
vs_fa = {row["team"]: row for row in run("night1/vs2-fable52-astra62")}


def match_table(teams: dict, alone: dict[str, float] | None = None) -> str:
    out = "<table><thead><tr><th>Team</th><th>Models</th><th class='num'>Score</th>"
    if alone:
        out += "<th class='num'>Same model alone</th>"
    out += "<th class='num'>Turns</th><th class='num'>Cost</th><th class='num'>Drills</th></tr></thead><tbody>"
    for name, row in sorted(teams.items(), key=lambda kv: -kv[1]["score"]):
        models = row["models"]
        label = NAMES[models[0]] + (f" \u00d7{len(models)}" if len(models) > 1 else "")
        out += f"<tr><td><span class='swatch {name}'></span>{name}</td><td>{label}</td><td class='num'>{n(row['score'])}</td>"
        if alone:
            out += f"<td class='num'>{n(alone[models[0]])}</td>"
        out += (f"<td class='num'>{row['turns']}</td><td class='num'>{usd(row['usd'])}</td>"
                f"<td class='num'>{row['built'].get('burner-mining-drill', 0)}</td></tr>")
    return out + "</tbody></table>"


alone = {model: v["mean"] for model, v in solo.items()}

# ----------------------------------------------------------------------------- notes and org
chain = G.get("handbook_chain", [])
transfer = G.get("handbook_transfer", [])
org = G.get("org", {})
def games(values: list[float]) -> str:
    return f" <span class='dim'>({len(values)} games)</span>" if len(values) > 1 else ""


transfer_rows = "".join(
    f"<tr><td>{row['model']}</td><td class='num'>{n(row['alone'])}{games(row.get('alone_games', []))}</td>"
    f"<td class='num'>{n(row['with_notes'])}{games(row.get('with_notes_games', []))}</td>"
    f"<td class='num'>{row['with_notes'] / row['alone']:.2f}x</td></tr>" for row in transfer)
org_rows = "".join(
    f"<tr><td>{label}</td><td class='num'>{', '.join(n(v) for v in values) or 'not run'}</td></tr>" for label, values in org.items())

# ----------------------------------------------------------------------------- every run
all_rows = ""
for row in sorted(R["runs"], key=lambda r: (r["run"].split("/")[1], r["team"])):
    models = row["models"]
    label = NAMES[models[0]] + (f" \u00d7{len(models)}" if len(models) > 1 else "")
    extras = []
    if row["org"] != "flat":
        extras.append(row["org"])
    if row["handbook"]:
        extras.append("notes from " + row["handbook"].split("/")[-2])
    if row["seed"] != 1001:
        extras.append(f"map {row['seed']}")
    note = "" if row["stop"] == "deadline" else f" <span class='warn'>ended early at {row['game_time']} ({row['stop'].replace('_', ' ')})</span>"
    all_rows += (f"<tr><td>{row['run'].split('/')[1]}{note}</td><td>{row['mode']}</td><td>{row['team'] if row['mode'] == 'versus' else ''}</td>"
                 f"<td>{label}</td><td>{'; '.join(extras)}</td><td class='num'>{n(row['score'])}</td>"
                 f"<td class='num'>{row['turns']}</td><td class='num'>{usd(row['usd'])}</td></tr>")

PROSE = json.loads((RES / "prose.json").read_text()) if (RES / "prose.json").exists() else {}


def prose(key: str) -> str:
    return PROSE.get(key, "")


page = f"""<title>Factorio Bench: First Night</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column, results first; charts and videos sit on paper-white plates in both themes. */
:root {{
  --bg: #f4f3ef; --plate: #fcfcfb; --fg: #16181a; --dim: #5a5f63; --rule: #d9d7cf;
  --accent: #b5521a; --warn: #a23b2c;
  --red: #e34948; --blue: #2a78d6; --green: #008300; --yellow: #eda100;
  --display: "Space Grotesk", "Inter", system-ui, sans-serif;
  --body: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #15171a; --plate: #fcfcfb; --fg: #e9e7e1; --dim: #a3a7a9; --rule: #33373b; --accent: #f08a4b; --warn: #f0806f;
  color-scheme: dark }} }}
:root[data-theme="dark"] {{
  --bg: #15171a; --plate: #fcfcfb; --fg: #e9e7e1; --dim: #a3a7a9; --rule: #33373b; --accent: #f08a4b; --warn: #f0806f;
  color-scheme: dark }}
body {{ background: var(--bg); color: var(--fg); font: 16px/1.6 var(--body); }}
main {{ max-width: 860px; margin: 0 auto; padding-block: 40px 80px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: flex; flex-direction: column; gap: 22px; }}
header {{ display: flex; flex-direction: column; gap: 10px; }}
h1 {{ font: 600 clamp(30px, 6vw, 44px)/1.1 var(--display); margin: 0; text-wrap: balance; letter-spacing: -0.01em; }}
h2 {{ font: 600 24px/1.25 var(--display); margin: 26px 0 0; text-wrap: balance; padding-top: 22px; border-top: 1px solid var(--rule); }}
h3 {{ font: 600 17px/1.3 var(--body); margin: 8px 0 0; }}
p {{ margin: 0; max-width: 68ch; }}
.lede {{ font-size: 19px; line-height: 1.5; }}
.meta {{ font: 500 13px/1.4 var(--mono); color: var(--dim); display: flex; flex-wrap: wrap; gap: 6px 18px; }}
ul {{ margin: 0; padding-left: 20px; max-width: 68ch; display: flex; flex-direction: column; gap: 8px; }}
li strong {{ font-weight: 600; }}
figure {{ margin: 0; }}
.chart img, video {{ display: block; width: 100%; height: auto; background: var(--plate); border: 1px solid var(--rule); border-radius: 4px; }}
figcaption {{ font-size: 13.5px; color: var(--dim); margin-top: 6px; max-width: 68ch; }}
.scroll {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14.5px; font-variant-numeric: tabular-nums; }}
th, td {{ text-align: left; padding: 7px 10px 7px 0; border-bottom: 1px solid var(--rule); vertical-align: top; }}
th {{ font: 500 12px/1.3 var(--mono); color: var(--dim); text-transform: uppercase; letter-spacing: 0.04em; white-space: nowrap; }}
.num {{ text-align: right; white-space: nowrap; }}
td.num .dim {{ white-space: normal; }}
.dim {{ color: var(--dim); }}
.warn {{ color: var(--warn); font-size: 13px; }}
.swatch {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 7px; }}
.swatch.red {{ background: var(--red); }} .swatch.blue {{ background: var(--blue); }}
.swatch.green {{ background: var(--green); }} .swatch.yellow {{ background: var(--yellow); }}
blockquote {{ margin: 0; padding: 2px 0 2px 16px; border-left: 3px solid var(--accent); max-width: 66ch; }}
blockquote p {{ font: 400 14.5px/1.55 var(--mono); }}
cite {{ display: block; font: 500 12.5px/1.4 var(--body); color: var(--dim); font-style: normal; margin-top: 4px; }}
.quotes {{ display: flex; flex-direction: column; gap: 14px; }}
details {{ border-top: 1px solid var(--rule); padding-top: 12px; }}
summary {{ cursor: pointer; font-weight: 600; }}
summary:focus-visible, a:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 3px; }}
a {{ color: var(--accent); }}
code {{ font: 400 0.92em var(--mono); }}
</style>
<main>
<header>
  <div class="meta"><span>19 November 2026</span><span>{len(runs_all)} games on 4 machines</span><span>{len(runs_done)} played to the deadline</span><span>{usd(R['total_usd'])} of model calls</span></div>
  <h1>AI teams playing Factorio by hand, with and against each other</h1>
  <p class="lede">{prose('lede')}</p>
</header>

{video(ROOT / 'runs/night1/ffa4-a/screens.mp4', "Four models on one map, each on its own team: what each one saw, in step with the game clock. Twenty game minutes in 40 seconds.")}

<h2>What the night showed</h2>
<ul>{prose('headlines')}</ul>

<h2>One agent alone</h2>
<p>{prose('solo')}</p>
{chart('solo_over_time', 'Production score over game time for each model playing alone')}
<div class="scroll"><table><thead><tr><th>Model</th><th>Lab</th><th class="num">Score at 20 min</th><th class="num">Turns</th><th class="num">Cost</th><th class="num">Drills placed</th><th class="num">Furnaces placed</th></tr></thead><tbody>{solo_rows}</tbody></table></div>

<h2>Does a team beat an individual?</h2>
<p>{prose('teams')}</p>
{chart('team_scaling', 'Team production score for one, two and four Claude Opus 5.5 agents')}
{chart('team_scaling_per_agent', 'Production score per agent for one, two and four agents')}
<div class="quotes">{prose('team_quotes')}</div>
{video(ROOT / 'runs/night1/team4-opus55-r2/screens.mp4', "A team of four Claude Opus 5.5 agents sharing one factory.")}

<h2>Teams against each other</h2>
<p>{prose('versus')}</p>
{chart('ffa4-a', 'Production score of four teams on one map')}
<div class="scroll">{match_table(ffa, alone) if ffa else ''}</div>
<div class="quotes">{prose('versus_quotes')}</div>
<h3>Two against two</h3>
<p>{prose('two_v_two')}</p>
{chart('vs2-fable52-astra62', 'Production score of two Fable agents against two Astra agents')}
<div class="scroll">{match_table(vs_fa) if vs_fa else ''}</div>
{video(ROOT / 'runs/night1/vs2-fable52-astra62/screens.mp4', "Claude Fable 5.2 (red) against GPT-6.2 Astra (blue), two agents each.")}
{chart('vs2-opus55-astra62', 'Production score of two Opus agents against two Astra agents')}
<div class="scroll">{match_table(vs_oa) if vs_oa else ''}</div>

<h2>Notes from one team to the next, and how a team is organised</h2>
<p>{prose('notes')}</p>
{chart('handbook_chain', 'Score of four successive two-agent teams, each starting from the previous team notes')}
<div class="scroll"><table><thead><tr><th>Model given Fable's notes</th><th class="num">Alone, no notes</th><th class="num">With the notes</th><th class="num">Change</th></tr></thead><tbody>{transfer_rows}</tbody></table></div>
<div class="quotes">{prose('notes_quotes')}</div>
<h3>Three ways to organise four agents</h3>
<p>{prose('org')}</p>
{chart('org', 'Score of four-agent teams with no structure, a manager, or assigned roles')}
<div class="scroll"><table><thead><tr><th>Organisation</th><th class="num">Scores</th></tr></thead><tbody>{org_rows}</tbody></table></div>

<h2>What to distrust</h2>
<ul>{prose('distrust')}</ul>

<h2>What I would do next</h2>
<ul>{prose('next')}</ul>

<h2>How a game works</h2>
<ul>{prose('method')}</ul>

<details><summary>Every game</summary>
<div class="scroll"><table><thead><tr><th>Game</th><th>Shape</th><th>Team</th><th>Models</th><th>Variant</th><th class="num">Score</th><th class="num">Turns</th><th class="num">Cost</th></tr></thead><tbody>{all_rows}</tbody></table></div>
</details>
</main>
"""
(PAGE / "index.html").write_text(page)
print(PAGE / "index.html", f"{len(page):,} chars;", "files:", sorted(p.name for p in PAGE.iterdir()))
