# How the harness works, and why

This records the decisions behind the harness and what was checked on the real game (Factorio 2.1.24, base
game, Linux, no GPU). The plan it serves is in [`HANDOFF.md`](HANDOFF.md); what the runs showed is in
[`RESULTS.md`](RESULTS.md).

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
- **Teams and matches need nothing new.** More agents are more clients on the same server.

The same binary is used for the server and the clients, so their versions always match.

## Game time, not wall time

The harness sets `game.tick_paused` on the server while models think and clears it while their actions run.
Time is counted in `game.tick`, 60 to the second. (`game.ticks_played` keeps counting while paused, so it is not
used.) While paused nothing responds, menus included, so reading a tooltip or the technology screen costs the
game time it takes to open it, as it would for a person in a multiplayer game.

Fixed delays surround the actions and are charged as game time, the same for every model:

| Delay | Seconds | Why |
|---|---:|---|
| Before the first input after an unpause | 0.15 | The client needs a few ticks to see the unpause. In a test, 5 of 6 key presses sent immediately after unpausing did nothing; 6 of 6 worked after 0.03 s. |
| Between moving the pointer and clicking | 0.15 | The game learns the pointer's position a few ticks late. Clicking 0.05 s after a move opened the intended chest in 4 of 6 tries (2 of 6 at 0.02 s, 6 of 6 from 0.10 s up). |
| Between actions | 0.1 | Lets one input register before the next. |
| After the last action | 0.4 | Lets it take effect and be drawn. Input takes 3 to 5 ticks to reach the server and a frame takes about 0.1 s to render in software. |

The end-of-turn screenshot is taken just before the pause, not after it. While paused the client does not draw
the outline of a building held in the hand, so a screenshot taken paused shows only a small icon at the pointer
and the model cannot see where the building would go.

About 40 to 50% of a run's game time is this overhead rather than the durations the model asked for (holds and
waits). It is a constant tax, and the reason game times here are not comparable with a human's.

## Several agents: a continuous schedule

With several agents, each acts on its own schedule. The game is paused whenever any agent is thinking and runs
while batches are being carried out. When one agent's batch ends, the game pauses, that agent gets its screenshot
and thinks, and the others' batches freeze in place and carry on afterwards: a key held for four seconds is held
for four seconds of running game however many pauses fall inside it (measured: 36.7 tiles walked across four
pauses, against 35.9 expected).

The first version ran teams in rounds instead: wait for every agent, run all the batches together, end the
round when the longest batch ends. In the first two-agent run each agent then spent about a third of the game
time standing idle, waiting for the other's longer batch. Rounds are still available (`--schedule rounds`).

Agents on one side talk through the in-game chat, which reaches only their own side.

## Two sides on one map

`--against` puts a second team on the same map with its own force: its own research, production statistics and
buildings. Both sides start at the same spot with the same items and the same charted area, so the start is
symmetric. Ore, trees and land are shared and finite. The two forces have a cease-fire (turrets and stray shots
do not start a war by accident) and both are friends with the game's default force, so either can open the
crashed ship's containers. Each side is scored separately; the winner is the side that launches first, or
failing that the side that got furthest.

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

OpenAI's API does not let one response mix computer-tool actions with function calls, so a GPT model could not
walk and then click in one reply, while Claude can. `click` and `press_keys` are therefore also offered to GPT as
functions, which can share a response with the holds. (In the runs so far GPT-6.2 Astra has not used them: it
still sends a hold on its own and looks at the result.)

Screens are 1280x720 and screenshots are sent at that size as JPEG (quality 90), so coordinates need no
scaling. A screenshot is about 1,200 tokens on Claude and 1,105 on GPT-6.2.

Batches run in order and stop at the first action that fails; the failure and the skipped actions are reported
to the model.

## What a model is told

The whole prompt is in [`factoriobench/prompts.py`](../factoriobench/prompts.py) and is versioned. It says how
the session works, names the three inputs a model might not expect (`hold_key`, `mouse_hold`, `zoom`), says the
console and editor are off and that leaving the game ends the run, and gives the objective. It gives no advice
about Factorio. GPT models get a few extra sentences about their tool's wait, scroll units and function calls.

The conversation starts with text only. The model asks for its first screenshot, as it would at any other time.
(GPT's compaction keeps user messages word for word forever, so an opening screenshot would be carried and paid
for on every later request.)

A reply without any action is answered with one fixed reminder. Three such replies in a row end that agent's
run. (At first a single reply without an action ended it. In the first GPT team run one agent said "I'll handle
fuel and copper while my teammate starts iron" on its second turn without calling a tool, and sat out the
remaining 498 rounds.) There is no fallback model if one refuses: a run is served by one model.

## Long runs: each lab's own compaction

A run of thousands of turns cannot keep every screenshot. Both labs advise against deleting old messages
yourself, because their models' reasoning is bound to the exact history. So the harness uses each lab's own
compaction, at the same threshold (150,000 tokens of context by default), with default settings:

- **Claude:** on-demand compaction. The harness asks the model to summarise everything but the last 6 turns,
  which are kept word for word, screenshots included. The summary is readable and is saved in the log.
- **GPT:** server-side compaction. The API replaces the history with an opaque summary when the threshold is
  crossed (in practice at about 175,000 tokens). It keeps no screenshots, so the model's first reply after a
  compaction is made without a current view of the screen unless it asks for one. This is a known difference in
  treatment.

Prompt caching is on for both, which is what makes the cost per turn small.

## Scoring

One Lua call over RCON returns a force's production, fluid and building statistics, the researched technologies
and `rockets_launched`. It runs whenever the game is paused for a reply. The harness records the game time of
every first: each item first produced, each kind of building first placed, each technology first researched. A
run is complete only when the game's own launch counter rises.

The headline is a ladder of 24 rungs from the first iron plate to the launch
([`factoriobench/scoring.py`](../factoriobench/scoring.py)); a run's score is the highest rung reached, with the
game time, turn and dollars at which each rung was reached. The ladder's names are checked against the running
game at startup, so a renamed item in a new version fails loudly.

Report game time, turns and dollars together, and compare teams with individuals at equal game time and at equal
spend, never only turn for turn: a team's turn buys more game time and costs more.

Known weaknesses: "placed" rungs count any placement, including one made by mistake or removed again, and the
rungs after the tenth are far apart (no run has yet passed the twelfth).

## Fixed conditions

- Map: freeplay, fixed seed, peaceful mode on (enemies exist but do not attack first), everything else default.
- Client graphics: clouds, fog, animated water, tree distortion, terrain effects, light occlusion and
  high-quality animations are off. They cost render time on a CPU-only machine and carry no game information.
  Everything else is a fresh install's default, including the in-game tips.
- Each client renders in software on one or two threads (about 10 frames a second) and uses about 2.5 GB of
  memory. Four clients fit on a 4-core, 15 GB machine with the simulation at 59 to 60 ticks per second; a fifth
  runs it out of memory. Every span's tick rate is logged (`ups` in `log.jsonl`).
- Model settings: each lab's defaults (reasoning effort `medium` on both Claude Opus 5.5 and GPT-6.2 Astra).

## Harness versions

| Version | What changed | Why |
|---|---|---|
| 0.1 | First full-game harness. Teams in rounds. Click 0.05 s after moving; screenshot taken paused; one reply without an action ends an agent's run. | |
| 0.2 | Click 0.15 s after moving. Screenshot taken before the pause. 0.4 s after the last action. A reply without an action gets a reminder; three in a row end the run. GPT gets `click` and `press_keys` as functions. | Reviews of the 0.1 runs found clicks landing on the previous target and models placing buildings blind; both were reproduced and measured (table above). A GPT agent was lost to one remark. |
| 0.3 | Teams on a continuous schedule. | In rounds each agent idled about a third of the game time. A solo run is identical in 0.2 and 0.3. |

Runs are filed by the harness version that made them (`runs/v0.1`, `runs/v0.2`, `runs/v0.3`), and results from
different versions should not be compared as if they were the same benchmark.

## Not done yet

- Resuming a run after a crash of the harness. The server autosaves every 10 minutes and each conversation is
  on disk without its images, but nothing reloads them.
- Google models.
- Hostile enemies have a flag (`--hostile`) but no run has used it.
- Per-agent production. The game keeps statistics per force, so a team's output cannot be split between its
  members without reading their reasoning.
- Whether Factorio's terms allow several clients on one licence for this use has not been checked.
