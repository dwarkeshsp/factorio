# Factorio agent benchmark: handoff brief

You are picking up a project from scratch in a new repository. This brief covers what we are trying to show, what has been decided, what has been checked, and what is still open. A working prototype harness, `agent.py`, comes with it.

## What we are trying to show

Dwarkesh Patel's essay on recursive self-improvement (<https://www.dwarkesh.com/p/rsi>) argues that AIs will become capable by cooperating and competing with teams of other AIs in simulated worlds, over long horizons. Skeptics doubted that such simulations could be built or would mean anything.

The project is an eval that tests this directly: **do groups of AI agents accomplish more than individuals, and does competition between groups push capability up?** It should have an objective score, difficulty that rises with the opponents, and replays people want to watch. The precedent is Dwarkesh's Clocktower benchmark (models play Blood on the Clocktower against each other, rated with a Bradley–Terry fit, with a public leaderboard and replay site). Aim for that level of rigour and presentation.

## Decisions already made

Do not reopen these without a new reason.

- **The game is Factorio.** It has a built-in production record, a clear end goal (launch a rocket), multiplayer, and good timelapses. Screeps, Victoria 3, Freeciv and others were considered and set aside.
- **Agents play natively**: screenshots in, mouse and keyboard out, as a human would. Dwarkesh considers this the cleanest design because it gives full parity with human affordances and removes arguments about what a custom API exposes. Code interfaces exist (below) but are not the primary path.
- **Single agent first.** Establish that one agent can play at all before building anything multi-agent.

## The staged plan

Each stage is a gate for the next.

1. **Smoke test**: one agent, native play, small task. *Done on the free demo; see results below.*
2. **Solo full game**: one agent attempts a rocket launch on the full game, across several models and several map seeds. Output is a single-agent leaderboard.
3. **Co-op scaling curve**: teams of 2, 4 and 8 agents of one model on one map with the same goal. Plot game time to rocket against team size. This is the core test of the "corporation" idea and needs no competition. Compare at equal total spend as well as equal spend per agent, or "more agents" just means "more money". Try both self-organised teams and a designated manager. Agents should talk through in-game chat and map markers.
4. **Team versus team**: the Biter Battles community scenario (two teams build factories; output strengthens the enemies attacking the other side), rated as Elo across labs.

## What is verified

**Native play works on a CPU-only Linux container** (4 cores, 16 GB, no GPU, Ubuntu 24.04).

- The Factorio demo (version 2.1.23) downloads without login from `https://factorio.com/get-download/stable/demo/linux64` (1.4 GB) and runs under `Xvfb` with Mesa software rendering (`LIBGL_ALWAYS_SOFTWARE=1`, `--disable-audio`). Startup takes about 40 seconds and uses about 3.5 cores.
- `xdotool` drives it. It needed `apt-get update` before `apt-get install xdotool`.
- On a 1280x720 virtual screen the game drew only a 1216x656 area at the top-left. The harness crops captures to the drawn area, so coordinates need no conversion.
- Freezing the game process with `SIGSTOP` while the model thinks and resuming with `SIGCONT` to execute actions works. Game time then measures play, not API latency.

**First results, Claude Opus 5.5, effort medium, demo tutorial level 1 ("Crash")**

- Run A: 25 turns, $0.38, 87 seconds of game time, about 530,000 tokens (almost all cache reads). It dismissed hints, walked, found and opened the escape pod, and moved items to its inventory. About 15 of 25 turns went on finding the pod.
- Run B (continuing; at turn 16 when this was written): it found the iron ore and needed to mine, which in Factorio means holding the right mouse button. The computer toolset has no right-button hold. The model opened the settings menu, rebound "Mine" to the X key, and mined with `hold_key`. That is a real affordance gap in the tool, solved by the model unprompted. Decide whether to pre-bind such keys for every model or leave it as part of the test.
- The demo contains only five tutorial levels, no free play. The full game is needed for stage 2.

**The Anthropic computer-use tool** (docs: <https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool.md>)

- Use `{"type": "computer_toolset_20260801"}`, no beta header, no display dimensions. Supported by Claude Fable 5.2, Opus 5.5, Sonnet 5.5 and Haiku 5.5.
- Calls arrive as `tool_use` blocks named for the member (`left_click`, `hold_key`, `zoom`, ...) with `toolset_name: "computer"`. Every `tool_result` must echo `toolset_name: "computer"`. Several actions per turn are normal; run them in order and stop at the first failure.
- Screenshots must already fit the model's limits; the API does not downscale.

**Prior work**

- A single model has launched a rocket through a code interface. Ryan Madden's autorio (<https://github.com/ryanmadden/autorio>, post at <https://ryanmadden.net/gpt-56-beats-factorio/>) reports GPT-5.6 Sol finishing in 13.5 game hours on peaceful mode. A secondary source puts that run at about 250 million tokens and $52.
- Autorio exposes 10 actions and 9 observations over a Python library. It has no blueprints, train schedules, circuit wiring, logistics requests, combat or vision. It is macOS-only, runs OpenAI's Codex agent only, uses one map seed, and has no licence file, so reuse needs the author's permission.
- Autorio's scoring design is worth copying: poll the game's own statistics through the console for tick, production, research and rocket count; record first-reached milestones; count a run as complete only when the game's launch counter rises. It gets a player character and a console in one process by having the graphical client host a local multiplayer game.
- The Factorio Learning Environment (<https://arxiv.org/abs/2503.09617>) is a code interface that, as published, lacks trains, robots and circuits.
- I found no published result of a frontier model playing Factorio natively, and none with teams.

## Not verified

- Whether a model stays coherent over the thousands of calls a full game needs. This is the main risk.
- Whether the full game runs acceptably on software rendering once a large factory is on screen. A GPU machine may be needed.
- Full-game cost. My estimate is $100 to $1,500 per run by native play; it is arithmetic, not a measurement.
- Whether Biter Battles works on the current game version.
- Whether Factorio's terms allow several simultaneous clients on one licence (matters from stage 3).
- That the headless server download needs no login, and that the in-game fast-launch achievement is set at 8 hours. Both are from memory.

## Design points to carry forward

- **Cheating.** A native-play agent can open the in-game console and type commands that spawn items. Block or detect this, and audit logs. Autorio also left a raw console endpoint reachable by the agent; do not repeat that.
- **Scores.** Report game time to each milestone, tokens, and dollars together. Game time alone rewards a bad factory finished by hand-carrying; cost alone ignores quality. Record the furthest milestone for runs that do not finish.
- **Fairness across labs.** OpenAI and Google models need their own computer-use adapters. Keep the action set and screenshot size equivalent.
- **Seeds.** Use several fixed map seeds and repeat runs; single runs are noisy.
- **No fallback models.** A benchmark run must be served by one model, so the prototype omits refusal fallbacks and stops on a refusal.
- **Multi-agent pausing.** With several agents, advance the game only when every agent has submitted its next inputs.
- **Context growth.** The prototype keeps every screenshot in context, which is fine for 150 turns and will not survive a full game. Preserved-thinking rules on current Claude models make naive history editing risky; read the docs before pruning.

## The prototype

`agent.py` is about 350 lines: screen capture, a full mapping of the computer toolset onto `xdotool`, freeze and resume, a streaming agent loop with prompt caching, a dollar cap, and a JSONL log with every screenshot saved. Treat it as a starting point to rewrite, not as the design.

To reproduce from an empty Linux container:

```bash
apt-get update && apt-get install -y xdotool xvfb imagemagick
```

```bash
pip install anthropic pillow
```

```bash
curl -L -o demo.tar.xz https://factorio.com/get-download/stable/demo/linux64 && tar -xJf demo.tar.xz
```

```bash
Xvfb :77 -screen 0 1280x720x24 +extension GLX &
```

```bash
DISPLAY=:77 LIBGL_ALWAYS_SOFTWARE=1 ./factorio/bin/x64/factorio --disable-audio &
```

Then click through Single player, New game, Play (in the first session: `xdotool mousemove 607 221 click 1`, then `607 301`, then `1082 634`), and run:

```bash
DISPLAY=:77 python3 agent.py --run-dir runs/test --max-turns 25 --max-usd 5 --task "Complete the first tutorial level of the Factorio demo, following the objectives shown on screen."
```

In the original environment the Anthropic key was stored as `MY_ANTHROPIC_API_KEY` and was not scoped to a workspace, so requests needed an `anthropic-workspace-id` header taken from `ANTHROPIC_WORKSPACE_ID`. Check what your environment provides.

## What to ask Dwarkesh for

- **His factorio.com username.** The full-game download needs username plus token (`https://factorio.com/get-download/stable/alpha/linux64?username=...&token=...`); the token alone redirects to a login page. Have both stored as environment variables, not pasted into chat.
- **A spending cap per stage.** None has been formally agreed. Spend so far is under $1, all on Claude Opus 5.5, with run B still going under a $6 cap.
- **Which models to include**, and keys for the non-Anthropic ones.
- **Whether to approach Ryan Madden** about collaborating or reusing autorio's scoring code.

## Suggested next steps

1. Reproduce the smoke test in the new repository and confirm the numbers above.
2. Get the full game running with a console connection for scoring and a fixed seed, on peaceful mode.
3. Run a capped solo attempt (say 500 turns) to see how far up the technology tree one model gets and where it stalls. That result decides whether stage 2 is a leaderboard or a research problem.
