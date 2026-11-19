# Factorio bench

An eval in which language models play [Factorio](https://factorio.com) the way a person does: they see the screen
and move the mouse and keyboard. The score comes from the game's own statistics. It is being built to test one
question: do groups of AI agents accomplish more than individuals, and does competition between groups push
capability up? Background and plan: [`docs/HANDOFF.md`](docs/HANDOFF.md).

> Work in progress. Unofficial; not affiliated with Wube Software. You need your own copy of Factorio.

## Where it stands

First results are in [`docs/RESULTS.md`](docs/RESULTS.md). In short, from one run per condition:

- In 500 turns ($17 to $25) one model alone builds steam power, labs and assemblers and starts on green science.
  Nobody is near a rocket.
- GPT-6.2 Astra reaches each early milestone in roughly a third to a half of the game time Claude Opus 5.5
  needs, alone and in a head-to-head match on a shared map.
- Two agents on a team get about twice as much done per game minute as one, and about a third as much per
  dollar.

## How a run works

- A Factorio server holds the map (fixed seed, freeplay, base game 2.1). Each agent plays through an ordinary
  graphical client on its own virtual screen, joined to that server as a non-admin player.
- The game is paused while models think and runs only while their actions execute, so game time measures play,
  not API latency. Time is counted in the game's own ticks.
- The harness reads the score from the server over RCON, which no agent can reach: production, buildings placed,
  research and the rocket launch counter. It records the game time of every first.
- Because agents are not admins, the game itself refuses Lua console commands and the map editor, and logs each
  attempt. A run's summary says whether it was clean.
- With several agents, each acts on its own schedule: the game pauses whenever any of them is thinking, and a
  batch in progress freezes and carries on afterwards. Teammates talk through the in-game chat.
- Two sides can share one map, each with its own factory, research and score.

The reasons behind each of these, and what was checked on the real game, are in [`docs/DESIGN.md`](docs/DESIGN.md).

## Quick start

```sh
sudo apt-get update && sudo apt-get install -y xvfb xdotool ffmpeg
python -m venv .venv && . .venv/bin/activate    # Python 3.11+
pip install -e '.[dev]'
python -m pytest                                 # no game and no API calls

export FACTORIO_USERNAME=... FACTORIO_TOKEN=...  # a factorio.com account that owns the game
python -m factoriobench setup                    # downloads the full game to ~/.factorio-bench

export ANTHROPIC_API_KEY=...
python -m factoriobench run --out runs/demo/opus --model claude-opus-5-5 --max-turns 30 --max-usd 2
python -m factoriobench report runs/demo/opus
python -m factoriobench timelapse runs/demo/opus
```

Teams and matches:

```sh
# Two agents of one model sharing a factory
python -m factoriobench run --out runs/demo/duo --model claude-opus-5-5,claude-opus-5-5 --max-turns 30 --max-usd 4
# Two sides on one map, each with its own factory, research and score
python -m factoriobench run --out runs/demo/match --model claude-opus-5-5 --against gpt-6.2-astra --max-turns 30 --max-usd 4
python -m factoriobench compare runs/demo/*      # runs side by side; works while they are still running
python -m factoriobench ratio runs/v0.2/solo/astra62-s1001 runs/v0.3/duo/astra62x2-s1001   # team over solo at equal game time
python -m factoriobench timelapse runs/demo/duo --team   # every agent's view side by side
```

Models: `claude-opus-5-5`, `claude-fable-5-2`, `claude-sonnet-5-5`, `claude-haiku-5-5` (needs `ANTHROPIC_API_KEY`) and
`gpt-6.2-astra` (needs `OPENAI_API_KEY`).

No GPU is needed: the client renders in software. Each client uses one or two cores and about 2.5 GB of memory;
four fit on a 4-core, 15 GB machine.

A run directory holds `config.json`, `summary.json`, `milestones.json` (kept in git), and `log.jsonl` (every turn:
reasoning summary, actions, cost, game time), each agent's screenshots and conversation, and the server's save and
console log (not in git). `touch <run>/STOP` ends a run at its next turn. Spend is appended to `runs/ledger.jsonl`,
and `--budget` caps the total across runs.

## Repository map

| Path | What it holds |
|---|---|
| `factoriobench/server.py` | The game server: map creation, the pause clock, Lua over RCON, the console-log audit |
| `factoriobench/client.py` | The virtual display and the graphical client |
| `factoriobench/desktop.py` | Screen capture and every mouse and keyboard action |
| `factoriobench/llm.py`, `llm_openai.py` | Claude and GPT conversations, prices, context compaction |
| `factoriobench/analyze.py`, `report.py` | Run comparison tables, single-run reports, timelapses |
| `factoriobench/scoring.py` | The score snapshot and the milestone ladder |
| `factoriobench/run.py` | The loop for one or more agents, in rounds or on the continuous schedule |
| `factoriobench/clock.py` | Game time for the code that presses keys: it stops while the game is paused |
| `factoriobench/prompts.py` | Everything a model is told (versioned) |
| `tests/` | Unit tests |
| `runs/` | Each run's config, summary and milestones, filed by harness version |
| `docs/` | Results, design notes, and the brief this project started from |
