# How the harness works, and why

This records the decisions behind the harness and what was checked on the real game (Factorio 2.1.24, base
game, Linux, no GPU). The plan it serves is in [`HANDOFF.md`](HANDOFF.md).

## A server holds the game; agents are ordinary players

One Factorio process runs as a server with the map. Each agent gets its own virtual screen (Xvfb) with one
graphical client on it, connected to that server over the local network. The harness talks to the server over
RCON.

This is what makes the rest possible:

- **Cheating is refused by the game, not by the prompt.** Agents join as non-admin players. Typing a Lua command
  into the in-game console gives "agent-1 tried to run a command, which isn't allowed for them", and `/editor`
  gives "you are not an admin". Both were tried by hand. The server's console log records every attempt, and a
  run's summary counts them (`commands_denied`, `commands_run`) and says whether the run was clean.
- **The score cannot be reached by the agent.** An agent has a screen, a mouse and a keyboard, and the only
  window on that screen is the game. RCON listens on localhost with a random password that exists only in the
  harness's memory.
- **Teams need nothing new.** More agents are more clients on the same server.

The same binary is used for the server and the clients, so their versions always match.

## Game time, not wall time

The harness sets `game.tick_paused` on the server while models think and clears it while their actions run.
Time is counted in `game.tick`, 60 to the second. (`game.ticks_played` keeps counting while paused, so it is not
used.) While paused nothing responds, menus included, so reading a tooltip or the technology screen costs the
game time it takes to open it, as it would for a person in a multiplayer game.

Three fixed delays surround each batch of actions and are charged as game time, the same for every model:

| Delay | Seconds | Why |
|---|---:|---|
| Before the first action | 0.15 | The client needs a few ticks to see the unpause. Input sent sooner is lost: in a test, 5 of 6 key presses sent immediately after unpausing did nothing, and 6 of 6 worked after 0.03 s. |
| Between actions | 0.1 | Lets one input register before the next. |
| After the last action | 0.3 | Lets it take effect before the pause. Input takes 3 to 5 ticks to reach the server. |

After pausing, the harness waits 0.4 s (free; the game is paused) so the client has drawn the frozen state, then
captures the screen.

With several agents the game advances in rounds: it stays paused until every agent has replied, then all the
batches run at once, and the round lasts as long as the longest batch.

## What a model can do

Every model gets the same hands, built from its own lab's computer-use tool plus whatever that tool lacks:

| Input | Claude (`computer_toolset_20260801`) | GPT (`computer` tool, Responses API) |
|---|---|---|
| Click, double click, move, drag, scroll, type, key chord, screenshot | built in | built in |
| Hold keys for a duration (walking) | built in (`hold_key`) | function `hold_key` |
| Wait for a duration | built in (`wait`) | built-in `wait` is 2 s; function `wait` for other durations |
| Enlarge part of the screen | built in (`zoom`) | function `zoom` |
| Hold a mouse button for a duration (mining) | function `mouse_hold` | function `mouse_hold` |

Factorio mines with a held right mouse button and neither lab's tool can hold one. In the prototype the model
worked around this by rebinding the game's controls, which tests the tool rather than the play, so `mouse_hold`
is given to everyone.

Screens are 1280x720 and screenshots are sent at that size as JPEG (quality 90), so coordinates need no
scaling. A screenshot is about 1,200 tokens on Claude and 1,105 on GPT-6.2.

Batches run in order and stop at the first action that fails; the failure and the skipped actions are reported
to the model.

## What a model is told

The whole prompt is in [`factoriobench/prompts.py`](../factoriobench/prompts.py) and is versioned. It says how
the session works, names the three inputs a model might not expect (`hold_key`, `mouse_hold`, `zoom`), says the
console and editor are off and that leaving the game ends the run, and gives the objective. It gives no advice
about Factorio. GPT models get three extra sentences about their tool's wait and scroll units.

The conversation starts with text only. The model asks for its first screenshot, as it would at any other time.
(GPT's compaction keeps user messages word for word forever, so an opening screenshot would be carried and paid
for on every later request.)

A model that replies without any action has ended its run. There are no reminders to continue, and no fallback
model if one refuses: a run is served by one model.

## Long runs: each lab's own compaction

A run of thousands of turns cannot keep every screenshot. Both labs advise against deleting old messages
yourself, because their models' reasoning is bound to the exact history. So the harness uses each lab's own
compaction, at the same threshold (150,000 tokens of context by default), with default settings:

- **Claude:** on-demand compaction. The harness asks the model to summarise everything but the last 6 turns,
  which are kept word for word, screenshots included.
- **GPT:** server-side compaction. The API replaces the history with an opaque summary when the threshold is
  crossed. It keeps no screenshots, so the model's first reply after a compaction is made without a current view
  of the screen unless it asks for one. This is the one known difference in treatment.

Prompt caching is on for both, which is what makes the cost per turn small.

## Scoring

One Lua call over RCON returns the force's production, fluid and building statistics, the researched
technologies and `rockets_launched`. It runs at the end of every round, while paused. The harness records the
game time of every first: each item first produced, each kind of building first placed, each technology first
researched. A run is complete only when the game's own launch counter rises.

The headline is a ladder of 24 rungs from the first iron plate to the launch
([`factoriobench/scoring.py`](../factoriobench/scoring.py)); a run's score is the highest rung reached, with the
game time, turn and dollars at which each rung was reached. The ladder's names are checked against the running
game at startup, so a renamed item in a new version fails loudly.

Report game time, turns and dollars together. Game time alone rewards hand-carrying a bad factory; cost alone
ignores quality.

## Fixed conditions

- Map: freeplay, fixed seed, peaceful mode on (enemies exist but do not attack first), everything else default.
- Client graphics: clouds, fog, animated water, tree distortion, terrain effects, light occlusion and
  high-quality animations are off. They cost render time on a CPU-only machine and carry no game information.
  Everything else is a fresh install's default, including the in-game tips.
- Each client renders in software on two threads. With two clients on a four-core machine the simulation held
  59 to 60 ticks per second; every round's rate is logged (`ups` in `log.jsonl`).
- Model settings: each lab's defaults (reasoning effort `medium` on both Claude Opus 5.5 and GPT-6.2 Astra).

## Not done yet

- Resuming a run after a crash of the harness. The server autosaves every 10 minutes and each conversation is
  on disk without its images, but nothing reloads them.
- Google models.
- Hostile enemies have a flag (`--hostile`) but no run has used it.
- Whether Factorio's terms allow several clients on one licence for this use has not been checked.
