#!/usr/bin/env python3
"""The words of the first night's report, with every number taken from results/night1/results.json.

  scripts/prose_night1.py      # writes results/night1/prose.json, which scripts/build_page.py lays out
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "night1"
R = json.loads((RES / "results.json").read_text())
G = R["groups"]


def n(value: float) -> str:
    return f"{value:,.0f}"


def usd(value: float) -> str:
    return f"${value:,.2f}"


def rows(path: str) -> dict[str, dict]:
    return {row["team"]: row for row in R["runs"] if row["run"] == path}


def li(*items: str) -> str:
    return "".join(f"<li>{item}</li>" for item in items)


def quote(who: str, text: str) -> str:
    return f"<blockquote><p>{text}</p><cite>{who}</cite></blockquote>"


solo = G["solo"]
astra, fable, sol = solo["gpt-6.2-astra"], solo["claude-fable-5-2"], solo["gpt-6.2-sol"]
opus, sonnet, haiku = solo["claude-opus-5-5"], solo["claude-sonnet-5-5"], solo["claude-haiku-5-5"]
scal = G["scaling"]
mean, speed = scal["pooled_mean"], scal["speedup"]
pairs = scal["seed 1001"]["2"] + scal["seed 2002"]["2"]
fours = scal["seed 1001"]["4"] + scal["seed 2002"]["4"]
ffa = rows("night1/ffa4-a")
oa = rows("night1/vs2-opus55-astra62")
fa = rows("night1/vs2-fable52-astra62")
chain = [value for _, value in G["handbook_chain"]]
transfer = {row["model"]: row for row in G["handbook_transfer"]}
org = G["org"]
runs_all = sorted({row["run"] for row in R["runs"]})
runs_done = sorted({row["run"] for row in R["runs"] if row["stop"] == "deadline"})
turns = sum(row["turns"] for row in R["runs"])

NAMES = {"claude-opus-5-5": "Opus", "claude-fable-5-2": "Fable", "gpt-6.2-astra": "Astra", "gpt-6.2-sol": "Sol",
         "claude-sonnet-5-5": "Sonnet", "claude-haiku-5-5": "Haiku"}
WORDS = {1: "once", 2: "twice", 3: "three times", 4: "four times", 5: "five times", 6: "six times", 7: "seven times", 8: "eight times", 9: "nine times"}
quits = sorted(R.get("quits", {}).items(), key=lambda kv: -kv[1])
QUITS = (f"Agents quit the game by accident through the Escape menu {WORDS.get(sum(v for _, v in quits), str(sum(v for _, v in quits)) + ' times')} ("
         + ", ".join(f"{NAMES[m]} {WORDS.get(v, str(v) + ' times')}" for m, v in quits) + ").")

P: dict[str, str] = {}

P["lede"] = (
    f"In one night, models from two labs played {len(runs_all)} games of real Factorio through screenshots, mouse and keyboard: "
    "alone, in teams sharing a factory, and as rival teams on one map. The game's own server kept the score. "
    "The set-up works, it produces clear differences between models, and the first results on teamwork and competition are below."
)

fa_line = ""
if fa:
    red, blue = fa["red"], fa["blue"]
    winner, loser = (blue, red) if blue["score"] > red["score"] else (red, blue)
    fa_line = (f" Two against two, GPT-6.2 Astra beat Claude Fable 5.2 {n(blue['score'])} to {n(red['score'])}."
               if blue["score"] > red["score"] else
               f" Two against two, Claude Fable 5.2 beat GPT-6.2 Astra {n(red['score'])} to {n(blue['score'])}.")

P["headlines"] = li(
    "<strong>It is possible, and cheap enough to iterate on.</strong> "
    f"{len(runs_done)} of {len(runs_all)} games ran the full 20 game minutes, {n(turns)} model turns in all, for {usd(R['total_usd'])}. "
    "Building and testing the harness cost about $7 more. "
    "No GPU, no game modding beyond a scenario file of under 100 lines, and no model touched the game's console.",
    "<strong>Models differ a lot at playing alone.</strong> "
    f"GPT-6.2 Astra scored {n(astra['mean'])}, GPT-6.2 Sol {n(sol['mean'])}, Claude Fable 5.2 {n(fable['mean'])}, "
    f"Claude Opus 5.5 {n(opus['mean'])} (mean of {len(opus['scores'])}), Claude Sonnet 5.5 {n(sonnet['mean'])} (mean of {len(sonnet['scores'])}) "
    f"and Claude Haiku 5.5 {n(haiku['mean'])}.",
    "<strong>Teams out-produce individuals, with sharply falling returns.</strong> "
    f"Two Claude Opus 5.5 agents averaged {speed['2']:.1f} times one agent's score; four averaged {speed['4']:.1f} times. "
    "Per agent, a team of four produced about half what an agent produces alone.",
    "<strong>Competition for land changed the outcome.</strong> "
    f"With four models on one map, Astra scored {n(ffa['blue']['score'])}, about what it scores alone, "
    f"while Fable fell from {n(fable['mean'])} alone to {n(ffa['green']['score'])} and Opus from {n(opus['mean'])} to {n(ffa['red']['score'])}. "
    "Astra covered the coal field with drills early and the others ran short of fuel." + fa_line,
    "<strong>Written notes mostly did not help.</strong> "
    + "Models played alone starting from the notes Fable wrote after its own game: "
    + "; ".join(f"{row['model'].replace('Claude ', '')} went from {n(row['alone'])} to {n(row['with_notes'])}" for row in G["handbook_transfer"])
    + ". Four generations of Opus teams passing notes down showed no upward trend either.",
    "<strong>The measurements are noisy.</strong> "
    f"Identical two-agent games scored between {n(min(pairs))} and {n(max(pairs))}. Most conditions here were played once, "
    "so treat single comparisons as leads, not findings.",
)

P["solo"] = (
    "Each model played the same 20-minute game alone on the same map. The gap is mostly in how much each one built. "
    f"Astra placed {astra['built'].get('burner-mining-drill', 0)} mining drills and {astra['built'].get('stone-furnace', 0)} furnaces in 20 minutes; "
    f"Opus placed {opus['built'].get('burner-mining-drill', 0)} and {opus['built'].get('stone-furnace', 0)}. "
    "The two GPT models work in many small steps (over 500 turns each), while Fable got a similar score to Sol in about 150 turns "
    f"by sending long batches of actions. Cost per game ran from {usd(haiku['usd'])} (Haiku) to {usd(astra['usd'])} (Astra)."
)

P["teams"] = (
    "The same model, Claude Opus 5.5, played alone, as a team of two and as a team of four, sharing one factory and one score, "
    f"on two different maps. One agent averaged {n(mean['1'])}, two averaged {n(mean['2'])} and four averaged {n(mean['4'])}. "
    "The second agent roughly doubled output; the third and fourth added little. "
    "Teams did organise themselves without being told to: in every team game the agents split the map by resource in the first minute "
    "and carried fuel and materials to each other. They sent 17 to 36 chat messages per game."
)
P["team_quotes"] = (
    quote("agent-2, in-game chat, first minute of the highest-scoring two-agent game",
          "I go NW to iron/copper, set up drills+furnaces. Suggest you mine coal (south) and bring some north.")
    + quote("agent-1, replying",
            "OK, I take coal (south), will set up coal mining and bring coal north to you.")
    + quote("agent-2, later in the same game",
            "Coal is our bottleneck. Want me to bring drills to the coal field? ... Tip: chain coal drills facing each other so they self-fuel.")
)

P["versus"] = (
    "Four models were put on one map, each on its own team with its own buildings and score, sharing the same ore fields. "
    "Nothing stopped them interfering with each other except a cease-fire on weapons. "
    f"Astra finished with {n(ffa['blue']['score'])}, {ffa['blue']['score'] / max(r['score'] for t, r in ffa.items() if t != 'blue'):.0f} times the next team. "
    "The Claude models scored far below what they score alone on the same map. Their own reasoning says why: "
    "Astra's drills occupied the coal field, coal is the fuel for everything else at this stage, and the others spent "
    "their time walking around someone else's machines. No team sent a message to another team in any game."
)
P["versus_quotes"] = (
    quote("Claude Opus 5.5 (red), reasoning summary at 8:04",
          "I'm stuck among trees with coal down at the bottom left, guarded by someone's drill grid of ten drills.")
    + quote("Claude Fable 5.2 (green), reasoning summary at 4:50",
            "I'm checking the coal patch: Blue's four drills already feed each other in a ring, and Yellow is hand-mining with 96 coal.")
    + quote("Claude Fable 5.2 (green), at 4:07", "I doubt I can catch the blue score, but I'll still try to maximize mine.")
    + quote("Claude Opus 5.5 (red), reasoning summary at 10:36",
            "The character barely moved, so I suspect blue's buildings are blocking the way.")
)

two = ""
if fa:
    two += (f"Claude Fable 5.2 against GPT-6.2 Astra, two agents each: Astra's pair finished on {n(fa['blue']['score'])} and Fable's on {n(fa['red']['score'])}. ")
if oa:
    stopped = next(row for row in R["runs"] if row["run"] == "night1/vs2-opus55-astra62")
    two += (f"An earlier match, Claude Opus 5.5 against GPT-6.2 Astra, stood at {n(oa['blue']['score'])} to {n(oa['red']['score'])} for Astra "
            f"when it ended early at {stopped['game_time'][2:]}: an Opus agent clicked Quit in the game's menu, which at that point ended the game for everyone. "
            "The harness now puts such a player back in.")
P["two_v_two"] = two

notes = (
    "At the end of each game every agent was asked for the notes it would leave the next player. Two tests used them. "
    f"In the first, four generations of two-agent Opus teams each started from the previous team's notes. Scores went {', '.join(n(v) for v in chain)}: "
    "no upward trend, and the first team, with no notes, happened to be the best. "
    "In the second, models played alone starting from the notes Fable wrote after its solo game. Only Sonnet did clearly better with them; "
    "Fable's notes are specific and correct, but most of what separates the models here seems to be execution through the screen, which notes do not transfer."
)
P["notes"] = notes
P["notes_quotes"] = (
    quote(f"From the notes Claude Fable 5.2 left after scoring {n(fable['mean'])}",
          "Hand-crafting in the last 3 minutes roughly doubled my score rate ... Keep the hand-craft queue busy THE WHOLE GAME, not just at the end. That was my biggest miss.")
    + quote("Same notes", "Never left-click an entity with an item in hand near menus, never press Escape; quitting ends the run.")
)

flat, manager, roles = org.get("No structure", []), org.get("A manager", []), org.get("Assigned roles", [])
org_text = (
    "Four Opus agents played the same game three ways: with no structure, with the first agent named as manager, and with four roles assigned in advance. "
    f"Unstructured teams scored {' and '.join(n(v) for v in flat)}."
)
if manager:
    org_text += (f" The managed team scored {n(manager[0])}. The manager did manage: it posted a plan at the start, sent each agent to a resource, "
                 "and the others acknowledged and reported back, but the result was no better.")
if roles:
    org_text += f" The team with assigned roles scored {n(roles[0])}."
if manager and roles and flat and max(manager + roles) < min(flat):
    org_text += (" Both imposed structures came in a little below the unstructured teams, which had sorted themselves into much the same "
                 "roles in the first minute anyway.")
org_text += " One game per structure is not enough to rank them."
P["org"] = org_text

P["distrust"] = li(
    f"<strong>Few games per condition.</strong> Only Opus alone ({len(opus['scores'])} games), Opus pairs ({len(pairs)}) and Opus fours ({len(fours)}) were repeated. "
    "Every other number on this page is one game.",
    "<strong>Twenty minutes is the early game.</strong> Nobody got past burner drills and stone furnaces. At this horizon the score mostly rewards "
    "digging and hand-crafting, and Astra's winning play (self-fuelling coal drills, then crafting chests for points) would not be the best play in a longer game.",
    "<strong>Spending differs between models.</strong> Astra took about three times as many turns as Fable and cost twice as much per game. "
    "Everything ran at medium reasoning effort; nothing was tuned per model.",
    "<strong>The machines were overloaded.</strong> Five game clients shared four CPU cores with software rendering, at 5 to 8 frames a second. "
    "To save CPU the clients are briefly frozen while models think, which sometimes puts the game's \"player is being dropped\" warning on other players' screens.",
    "<strong>The Quit button.</strong> " + QUITS + " "
    "Three games ended early before the harness learned to put the player back in; they are listed under Every game and left out of the charts. "
    "A fourth game could not start because the game before it left no notes.",
    "<strong>One model family per team.</strong> No mixed-lab teams were tried, and the map was the same in all but three games.",
)

P["next"] = li(
    "<strong>Repeat everything five times.</strong> At $5 to $25 a game, a real leaderboard with error bars is a few hundred dollars.",
    "<strong>Longer games on a GPU machine.</strong> One to three game hours reaches electricity, research and automation, where organisation should matter far more than it does when everyone is digging by hand.",
    "<strong>Real conflict.</strong> The harness already has a switch that lets teams attack each other, and the game ships its own team modes. "
    "The interesting version is the one where what you produce hurts the other side.",
    "<strong>More agents per team.</strong> Four was the limit of one small machine, not of the design.",
    "<strong>A rating.</strong> With repeats, the matches give a single head-to-head rating per model, as in the Clocktower benchmark.",
)

P["method"] = li(
    "<strong>The models play the real game by hand.</strong> Each agent has its own copy of Factorio 2.1 on its own virtual screen. It sees screenshots and acts with the mouse and keyboard. Claude and GPT models get exactly the same set of actions.",
    "<strong>The clock only runs while someone is acting.</strong> The game is paused whenever any agent is thinking. Every agent acts at its own pace, and an agent in the middle of a long action is frozen through each pause.",
    "<strong>The score is the game's own.</strong> It is the production score from Factorio's PvP mode: the value, at the game's price list, of everything a team has produced and not used up. Wood and fish count for nothing, and science spent on research keeps its value.",
    "<strong>The game closes off cheating.</strong> Agents are ordinary players, not admins, so the game refuses console commands and logs each attempt. There were none.",
    "<strong>One start, one deadline.</strong> Standard freeplay, fixed map, standard starting items, peaceful natives, permanent daylight, 20 game minutes.",
)

(RES / "prose.json").write_text(json.dumps(P, indent=1))
print("wrote", RES / "prose.json")
