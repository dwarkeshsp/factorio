# Factorio bench

An eval in which language models play [Factorio](https://factorio.com) the way a person does: they see the screen
and move the mouse and keyboard. The score comes from the game's own statistics. It is being built to test one
question: do groups of AI agents accomplish more than individuals, and does competition between groups push
capability up? Background and plan: [`docs/HANDOFF.md`](docs/HANDOFF.md).

> Work in progress. Unofficial; not affiliated with Wube Software. You need your own copy of Factorio.

## How a run works

- A Factorio server holds the map (fixed seed, freeplay, base game 2.1). Each agent plays through an ordinary
  graphical client on its own virtual screen, joined to that server as a non-admin player.
- The game is paused while models think and runs only while their actions execute, so game time measures play,
  not API latency. Time is counted in the game's own ticks.
- The harness reads the score from the server over RCON, which no agent can reach: production, buildings placed,
  research and the rocket launch counter. It records the game time of every first.
- Because agents are not admins, the game itself refuses Lua console commands and the map editor, and logs each
  attempt. A run's summary says whether it was clean.
- With several agents the game advances in rounds: it stays paused until every agent has replied, then all their
  actions run at once. Agents talk through the in-game chat.

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

A team is a comma-separated list, one agent per entry:
`--model claude-opus-5-5,claude-opus-5-5`.

No GPU is needed: the client renders in software. Each client uses about two cores and 2 GB of memory.

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
| `factoriobench/llm.py` | Model conversations, prices, context compaction |
| `factoriobench/scoring.py` | The score snapshot and the milestone ladder |
| `factoriobench/run.py` | The round loop for one or more agents |
| `factoriobench/prompts.py` | Everything a model is told (versioned) |
| `tests/` | Unit tests |
| `runs/` | Each run's config, summary and milestones |
