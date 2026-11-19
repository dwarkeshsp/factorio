# Factorio bench

Language models play [Factorio](https://factorio.com) the way a person does: they see the screen and use the
mouse and keyboard. They play alone, in teams that share a factory, and against other teams on the same map. The
score is the game's own production score, read from the game server.

It exists to test one claim: that AIs can be put into rich simulated worlds where they have to cooperate and
compete with other AIs over long stretches, and that this can be measured. Factorio is a first, small example of
such a world.

> Work in progress from one night of runs (19 November 2026). Unofficial; not affiliated with Wube Software. You
> need your own copy of Factorio. Every number below comes from `results/night1/results.json`, built from the run
> files under `runs/` by `scripts/analyze_night.py`.

![Four agents' screens side by side during a four-team game](results/night1/ffa-frame.jpg)

*Four models, one map, sixteen minutes in. Each panel is what that model sees. GPT-6.2 Astra (blue) has covered
the coal field with mining drills; Claude Sonnet 5.5 (yellow) is standing next to them.*

## What one night showed

RESULTS_PLACEHOLDER

## How a game works

- **The models play the real game by hand.** Each agent has its own copy of Factorio 2.1 on its own virtual
  screen. It sees screenshots (1280x720) and acts with the mouse and keyboard: click, drag, type, hold a key, hold
  a mouse button, scroll, zoom in on part of the screen. Nothing reads the game's memory for it and there is no
  scripting interface. Claude models use Anthropic's computer-use toolset; GPT models get the same actions, with
  the same names and inputs, as function tools (`factoriobench/tools.py`).
- **The clock only runs while someone is acting.** The game is paused whenever any agent is thinking, so a slow
  API does not cost game time. Every agent acts at its own pace, as players do in a real multiplayer game: when
  the game runs, each agent's current actions run at once, and it pauses again as soon as one of them has finished
  and needs to look at its screen. An agent in the middle of a long action (holding a key to walk, say) is frozen
  through the pause and carries on afterwards.
- **The score is the game's own.** A game server holds the map and the agents join it as ordinary players. The
  harness reads the score from the server, which no agent can reach. The score is the production score from
  Factorio's own PvP mode: the value, at the game's built-in price list, of everything a team has produced and not
  used up. Two things differ from the game's formula. Science packs spent on research keep their value, so
  research is not scored as a loss. Wood and fish are worth nothing, because at the game's prices chopping trees
  would beat building a factory.
- **Cheating is closed off by the game.** Agents are not admins, so the game refuses console commands and the map
  editor and logs each attempt. Every run's summary records whether it was clean. Every run so far was.
- **One start, one deadline.** Every game is the game's standard freeplay on a fixed map seed, with the standard
  starting items, peaceful natives and permanent daylight (a night-time screenshot is close to black). Games run
  for 20 game minutes, which takes 35 to 110 minutes of real time.

A game takes one of three shapes:

| Shape | What it is | What it measures |
|---|---|---|
| Solo | One agent | How well one model plays |
| Team | Two or four agents of one model sharing a factory and a score, talking through the in-game chat | Whether a group out-produces an individual |
| Versus | Two to four teams on the same map, each with its own buildings, research and score, sharing the same ore | Who wins when models compete for the same land |

Two more switches exist for team games. `--org` sets how a team is organised: no structure, a manager, or roles
assigned in advance. `--handbook` starts a game from the notes an earlier team wrote; every agent is asked for
such notes when its game ends.

## What to distrust

CAVEATS_PLACEHOLDER

## Running it

```sh
sudo apt-get update && sudo apt-get install -y xvfb xdotool ffmpeg
python -m venv .venv && . .venv/bin/activate    # Python 3.11+
pip install -e '.[dev]' matplotlib
python -m pytest                                 # no game and no API calls
```

The game has to be downloaded with a factorio.com account that owns it. `python -m factoriobench setup` does this
from `FACTORIO_USERNAME` and `FACTORIO_TOKEN`, but factorio.com currently refuses Python's default user agent; if
it fails, download `https://factorio.com/get-download/stable/alpha/linux64?username=...&token=...` with curl and
unpack it to `~/.factorio-bench/full`.

```sh
export ANTHROPIC_API_KEY=... OPENAI_API_KEY=...

# one agent
python -m factoriobench run --out runs/demo/solo --model claude-opus-5-5 --minutes 20

# a team of two sharing a factory, with a manager
python -m factoriobench run --out runs/demo/team --model claude-opus-5-5,claude-opus-5-5 --org manager

# two teams on one map
python -m factoriobench run --out runs/demo/match \
    --team red=claude-fable-5-2,claude-fable-5-2 --team blue=gpt-6.2-astra,gpt-6.2-astra

python -m factoriobench report runs/demo/match
python -m factoriobench timelapse runs/demo/match --screens    # every agent's screen, side by side
python -m factoriobench timelapse runs/demo/match --overview   # the bases from above
```

No GPU is needed: the clients render in software. Each client wants about 2 GB of memory and most of a core, so a
4-core, 16 GB machine holds five clients. `scripts/runq.py` runs a queue of games and makes a game wait until the
machine has room. `--max-usd` caps one game and `--budget` caps the total on the spend ledger.

A run directory holds `config.json`, `summary.json`, `milestones.json`, `log.jsonl` (every turn: what the model
said, its reasoning summary, its actions, cost, game time, and the score at every pause), the server's chat log,
each agent's `handbook.md`, and two videos. Screenshots, conversations and saves stay out of git.

## Repository map

| Path | What it holds |
|---|---|
| `factoriobench/run.py` | One game: the scheduler that lets every agent act at its own pace, teams, the deadline, reconnection, handbooks |
| `factoriobench/scenario/control.lua` | The game's freeplay plus teams: puts each joining player on its team's force |
| `factoriobench/server.py` | The game server: Lua over RCON, the pause switch, team setup, the price list, the console-log audit |
| `factoriobench/client.py`, `desktop.py`, `clock.py` | The virtual screen and game client, every mouse and keyboard action, and the clock that suspends them through a pause |
| `factoriobench/llm.py`, `tools.py` | Model conversations for Claude and GPT models, prices, context compaction, the shared action set |
| `factoriobench/scoring.py` | The production score and the milestone ladder |
| `factoriobench/prompts.py` | Everything a model is told (versioned) |
| `factoriobench/report.py`, `charts.py` | Reports, videos and charts |
| `scripts/` | The queue runner, live status, and the analysis that builds `results/` |
| `runs/night1`, `runs/w1`, `runs/w3`, `runs/w4` | The first night's games, from four machines |
| `results/night1` | Charts, videos and `results.json` |
| `prototype/`, `docs/HANDOFF.md` | The first single-file prototype and the brief the project started from |

## What I would do next

NEXT_PLACEHOLDER
