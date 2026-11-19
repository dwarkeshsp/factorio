# Results so far

Runs made on the night of 18–19 November 2026. Every run is on freeplay, peaceful mode, base game 2.1.24, with
each agent limited to 500 turns, on map seed 1001 or 1002. How the harness works is in [`DESIGN.md`](DESIGN.md).

Read this with one caution throughout: every comparison rests on **one or two runs per condition**. Where two
runs of the same condition exist they differ by 20 to 50%, so a difference smaller than about 2x between
conditions is not established.

## What the runs show

1. **Current models can play the full game through the screen.** In 500 turns, for $17 to $25, one model alone
   mines, smelts, builds steam power, labs and assemblers, researches 5 to 8 technologies and starts on green
   science. Nobody came near a rocket: the furthest rung reached was 12 of 24.
2. **GPT-6.2 Astra is well ahead of Claude Opus 5.5** on the same map: it reached each early milestone in
   roughly a third to a half of the game time, alone and in a head-to-head match on a shared map.
3. **Two agents are ahead of one at equal game time, once each agent acts on its own clock**: in all three
   pairings tried they reached the lab and science several minutes sooner and had made 1.6 to 2.5 times the
   science packs by the later minutes. Raw plate output was about double on one map and no higher on the other.
   Per dollar a pair gets about a third as much as one agent. It builds the same kind of factory sooner, not a
   better one.
4. **How the game clock is shared between agents decides the answer.** With agents taking turns in rounds, the
   same pair of Opus agents was no faster than one agent, because each stood idle about a third of the time
   waiting for the other.
5. **Reading the runs found four faults in the harness** that the scores alone would not have shown. Three are
   fixed and one is described; details below.

## Every run

Production columns are iron plates / copper plates / automation science packs made by the end.

| Harness | Run | Agents | Game time | Cost | Rung | Techs | Iron / copper / science |
|---|---|---|---:|---:|---:|---:|---|
| 0.1 | `v0.1/solo/opus55-s1001` | Opus 5.5 | 35:30 | $16.79 | 10 | 5 | 1,437 / 675 / 87 |
| 0.1 | `v0.1/solo/astra62-s1001` | GPT-6.2 Astra | 20:39 | $24.75 | 10 | 6 | 1,997 / 667 / 129 |
| 0.1 | `v0.1/duo/opus55x2-s1001` (rounds) | Opus 5.5 x2 | 56:47 | $32.20 | 10 | 8 | 3,700 / 1,786 / 182 |
| 0.1 | `v0.1/duo/astra62x2-s1001` (see note) | GPT-6.2 Astra, in effect alone | 25:23 | $25.34 | 12 | 8 | 2,533 / 866 / 206 |
| 0.2 | `v0.2/solo/opus55-s1001` | Opus 5.5 | 47:12 | $17.14 | 10 | 6 | 2,237 / 1,031 / 129 |
| 0.2 | `v0.2/solo/astra62-s1001` | GPT-6.2 Astra | 27:17 | $25.15 | 11 | 7 | 2,679 / 842 / 143 |
| 0.3 | `v0.3/duo/opus55x2-s1001` (continuous) | Opus 5.5 x2 | 47:25 | $32.58 | 10 | 8 | 2,836 / 1,019 / 216 |
| 0.3 | `v0.3/duo/astra62x2-s1001` (continuous) | GPT-6.2 Astra x2 | 24:40 | $50.15 | 12 | 8 | 3,288 / 1,238 / 191 |
| 0.3 | `v0.3/versus/opus55-vs-astra62-s1001` | Opus 5.5 against GPT-6.2 Astra | 77:35 | $40.92 | 10 v 12 | 7 v 13 | 1,417 / – / 142 v 6,182 / – / 572 |
| 0.3 | `v0.3/solo/opus55-s1002` (left the game at turn 467) | Opus 5.5 | 42:51 | $15.86 | 9 | 5 | 1,959 / 582 / 70 |
| 0.3 | `v0.3/duo/opus55x2-s1002` (continuous) | Opus 5.5 x2 | 51:55 | $31.95 | 11 | 8 | 3,736 / 2,283 / 208 |
| 0.3 | `v0.3/solo/astra62-s1002` | GPT-6.2 Astra | 28:31 | $24.87 | 12 | 8 | 2,674 / 757 / 190 |

Rungs: 9 is the first technology researched, 10 the first assembling machine placed, 11 the first logistic
(green) science pack, 12 the first steel plate. Every run was clean: no console command was attempted, let alone run.

Note on `v0.1/duo/astra62x2-s1001`: the second agent said "I'll handle fuel and copper while my teammate starts
iron" on its second turn without calling a tool, which under the 0.1 rule ended its run. The other agent played
the remaining 498 rounds alone, so this run is a second GPT-6.2 Astra solo in all but name.

## One model alone

When each rung was first reached, in minutes of game time:

| Rung | Opus 5.5 (0.1) | Opus 5.5 (0.2) | GPT-6.2 Astra (0.1) | GPT-6.2 Astra (0.2) |
|---|---:|---:|---:|---:|
| Iron plate | 2.7 | 2.7 | 1.0 | 1.1 |
| Copper plate | 7.8 | 22.5 | 1.4 | 4.0 |
| Electronic circuit | 17.7 | 25.0 | 2.7 | 6.5 |
| Steam engine placed | 16.0 | 21.1 | 5.1 | 5.9 |
| Lab placed | 18.3 | 27.5 | 5.1 | 8.1 |
| Automation science pack | 18.6 | 25.6 | 4.9 | 7.2 |
| Assembling machine placed | 24.1 | 32.4 | 8.7 | 10.9 |
| Logistic science pack | – | – | – | 26.3 |

How the two models play differently (from a turn-by-turn review of the 0.1 runs):

| | GPT-6.2 Astra | Opus 5.5 |
|---|---:|---:|
| Actions per turn | 3.3 | 7.4 |
| Game seconds per turn | 2.5 | 4.3 |
| Turns that zoom or take an extra screenshot | 1% | 97% |
| Waits | 2 | 936 |
| Ctrl-click transfers (first used on turn) | 358 (3) | 46 (396) |
| Quickbar number keys | 119 | 0 |
| Game seconds of hand-mining | 145 | 411 |
| First transport belt placed | turn 237 | turn 497 |

Astra acts and moves on; Opus checks almost every step. Astra zooms the view out at the start and works from a
picture about 3.5 times wider. It uses the game's shortcuts from its third turn. Its output per turn is tiny:
30 to 120 tokens, usually with no visible reasoning.

Both were limited by the same thing: they carry plates, coal and science packs by hand between sites 70 to 100
tiles apart. Opus laid no belts in its first run. Astra laid a 160-belt coal line but still fed its boiler by
hand at the end.

Long-run coherence held. Opus compacted its history 6 times in 500 turns and each summary's next steps were the
ones it then took; two wrong beliefs were carried in summaries and acted on (that shift-click crafts five, and
that hold durations must be whole seconds). Astra's API compacted 3 times. After one of them it walked into
wreckage it had learned to avoid; otherwise its plan survived, including one turn played blind.

## Two agents on one team

The fair comparison is at equal game time, since machines produce by the clock. Team output divided by solo
output, pairs on the continuous schedule against solos on the same input rules and the same map
(`python -m factoriobench ratio SOLO TEAM` prints these):

| Game minutes | Opus 5.5, seed 1001: iron | science | Opus 5.5, seed 1002: iron | science | GPT-6.2 Astra, seed 1001: iron | science |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 2.4 | – | 1.1 | – | 2.1 | 2.5 |
| 15 | 2.1 | – | 0.8 | – | 2.1 | 2.1 |
| 20 | 3.7 | – | 1.0 | – | 1.8 | 2.4 |
| 25 | 2.2 | 9.0 | 1.1 | 4.9 | | |
| 30 | 2.0 | 2.1 | 0.9 | 1.6 | | |
| 35 | 1.8 | 1.9 | 1.0 | 1.7 | | |
| 40 | 1.3 | 1.8 | 1.1 | 2.0 | | |
| 45 | 1.3 | 1.7 | | | | |

(A dash means the solo had made no science packs yet.)

The two Opus pairings disagree on iron: about double on seed 1001, no gain on seed 1002. The seed-1001 ratios
before minute 30 flatter the pair, because that solo had no copper until minute 22, where another Opus solo on
the same seed had it at minute 8; against that other solo the pair's ratio at 25 to 35 minutes is 0.9 to 1.3.
What all three pairings share is the science: 1.6 to 2.5 times the solo's once the solo has been making packs
for a few minutes.

Milestones, pair against solo, in game minutes:

| | Opus 5.5, seed 1001 | Opus 5.5, seed 1002 | GPT-6.2 Astra, seed 1001 |
|---|---|---|---|
| Lab placed | 14.6 v 27.5 | 17.9 v 21.8 | 6.0 v 8.1 |
| Automation science pack | 10.3 v 25.6 | 14.4 v 21.8 | 5.8 v 7.2 |
| Assembling machine placed | 22.0 v 32.4 | 22.9 v never | 8.0 v 10.9 |
| Logistic science pack | never v never | 42.5 v never | 20.2 v 26.3 |

The other two ways to compare, at the end of the runs:

| | Opus 5.5 | GPT-6.2 Astra |
|---|---|---|
| Equal turns per agent (500 each; the pair costs twice as much): iron / science, pair v solo | 2,836 / 216 v 2,237 / 129 | 3,288 / 191 v 2,679 / 143 |
| Equal total turns and spend (pair at 250 turns each v solo at 500): iron / science | 678 / 25 v 2,237 / 129 | 795 / 56 v 2,679 / 143 |

So a second agent brings the science forward and gets about a third as much per dollar: a team turn buys half
the game time, and the machines do most of the producing.

**The same factory, sooner.** The Opus pair placed the same number of drills as the solo (18 burner and 10
electric against 18 and 11) and a few more assemblers and labs, and reached steam power, a lab and Automation 7
to 14 minutes earlier. Both hand-fed their furnaces.

**What the pairs said to each other.** The Opus pair exchanged 54 to 56 chat messages a run; about 14 to 20
changed what the other did ("Pls prioritize Electric mining drill research" was done three rounds later).
Coordination lost each agent an estimated 6 to 11% of its turns: fuelling the same furnaces, one taking the
coal the other was about to use, both setting out to add the second steam engine. About 8% of chat messages had
faded from the screen before the receiver's next screenshot.

**Simultaneous moves collide.** In all three runs where both teammates played, the two agents opened by each
proposing a split at the same moment. In two of them each then accepted the other's proposal, swapping roles in
mid-air:

> agent-2: I'll set up coal and copper; please handle iron and power/science.
> agent-1: I'll bootstrap iron and coal; please handle power, copper and research.
> agent-1: OK, your plan: you coal+copper, me iron+power/science.
> agent-2: Agreed, I'll handle power, copper, research. You do coal and iron.

(GPT-6.2 Astra pair. The first Opus pair did the same and broke the tie three rounds later with "FINAL: I
(agent-2) take iron/copper". The second Opus pair escaped only because one of the two opening messages failed
to send.)

### Rounds against the continuous schedule

The first Opus pair (harness 0.1) played in rounds: the game waited for both agents, ran both batches, and
ended the round when the longer batch ended. Its ratio to the solo at equal game time was 1.7 at minute 10,
1.0 at minute 25 and 0.75 at minute 35 for iron, and 0.3 or less for science throughout. Each agent's own batch
averaged 4.3 to 5.0 game seconds but rounds lasted 6.8, so agent-1 spent about 38% of the game waiting and
agent-2 about 28%. On the continuous schedule that waiting measured under 4%.

A new gap replaced it: with a budget of turns per agent, the agent that takes shorter turns runs out first. One
Opus agent used its 500 turns by minute 40 and was absent for the last 8 minutes. A budget of game time, or of
turns pooled across the team, would avoid this.

## Two sides on one map

Opus 5.5 against GPT-6.2 Astra, one agent each, same start point, shared ore, separate factories and research.
Astra won on every measure:

| At game minute 40.5 | Opus 5.5 | GPT-6.2 Astra |
|---|---:|---:|
| Iron plates | 1,223 | 2,459 |
| Automation science packs | 110 | 261 |
| Technologies | 6 | 8 |
| Lab placed at minute | 20.3 | 8.8 |
| Automation researched at minute | 22.3 | 13.1 |

The two played side by side rather than against each other. What passed between them:

- Both mined the same big rock in the second minute, and Astra got it. Both then worked the one iron, copper,
  coal and stone patch with their drills interleaved. Nothing ran out.
- Astra's buildings left Opus no room for a coal drill site and a smelting line it had planned, and one wall of
  the pocket Opus got "boxed in" by for three turns was Astra's drill pair (the rest was its own).
- Opus learned it was behind from numbers floating over Astra's furnaces ("Agent-2 has 206 iron plates and is
  ahead") and did not change its plan.
- Astra once ctrl-clicked two of Opus's stone chests. The game answered "Cannot transfer from enemy structures".
- No chat, no console attempts, no shooting, no mining of the other's buildings.

Neither claimed land or resources early. "Launch a rocket first" was too far off to shape what either did, and
sharing the map cost them almost nothing. For the two sides to compete, something has to be scarce.

This match also shows the turn-budget problem: Opus spent its 500 turns in 40.5 game minutes, and Astra then
played alone for 37 more. Its final totals (6,182 iron plates, 13 technologies) include that time; the table
above cuts both off at minute 40.5. The budget did not decide the result: Astra had reached steel, rung 12,
before Opus's last turn.

## How much runs differ

Two runs of the same model alone on the same seed:

| | Run A | Run B |
|---|---|---|
| Opus 5.5: copper plate at minute | 7.8 (0.1) | 22.5 (0.2) |
| Opus 5.5: iron plates at minute 30 | 1,009 | 609 |
| GPT-6.2 Astra: final rung, technologies, science packs | 10, 6, 129 (0.1 solo) | 12, 8, 206 (0.1, idle teammate) |

The Opus pair differs by harness version as well as by chance, so it overstates pure chance; the Astra pair is
on one harness. Either way the spread between two runs of one condition is as large as most of the differences
this page reports between conditions, apart from the gap between the two models.

## Faults the run reviews found in the harness

Each finished run was read turn by turn (reasoning, actions and a sample of screenshots).

| Fault | Evidence | Status |
|---|---|---|
| A click sent 0.05 s after moving the pointer often landed on whatever was under the pointer before. | Reproduced: 4 of 6 such clicks opened the intended chest; 6 of 6 with 0.10 s or more. Opus had worked around it with "move, wait 0.4 s, click" 185 times. | Fixed in 0.2 (0.15 s). |
| Screenshots taken while paused did not show the outline of a building held in the hand, so models placed buildings blind. | Reproduced side by side: outline present running, absent paused. Both models lost runs of turns to misplaced boilers, drills and poles. | Fixed in 0.2 (capture before pausing). |
| The first input after each unpause was lost. | Reproduced: 1 of 6 key presses registered with no delay, 6 of 6 after 0.03 s. | Fixed before the first scored run. |
| One reply without an action ended an agent's run. | Lost a GPT agent on its second turn. GPT-6.2 Astra also sends computer calls with no actions in them, which the API then refuses to accept back (this crashed one run). | Fixed in 0.2 and 0.3: a reminder, and three in a row to stop. |
| Rounds made teammates wait for each other. | 28 to 38% of game time idle per agent. | Fixed in 0.3 (continuous schedule). |
| `\n` at the end of typed text was not sent as Enter, so 3 of 57 chat messages were never sent. | From the logs. | Fixed in 0.3.1, after these runs. |
| Once, a paused right-button hold left an agent's pointer dead for four turns. | One case in seven such coincidences; cause unknown. | Open. |

The fixes in 0.2 did not visibly speed the models up: per turn they made more (Opus 2,237 iron plates against
1,437), but each turn took more game time (5.7 s against 4.3 s), and one run each cannot separate that from
chance.

Roughly 40 to 50% of game time in every run is harness overhead (fixed delays around each input) rather than
durations the model asked for. Game times here are not comparable with a human's.

## A second map

Seed 1002, harness 0.3: Opus 5.5 alone, an Opus 5.5 pair and GPT-6.2 Astra alone (rows in the table of runs).

- GPT-6.2 Astra alone did about what it did on seed 1001: steel (rung 12) in 28:31, 8 technologies. Its lead
  over Opus 5.5 held: lab at minute 8.1 against 21.8, first assembling machine at 11.7 against never.
- The Opus 5.5 pair again reached every milestone before the solo and made about twice the science, but no more
  iron (table above).
- **The Opus solo ended itself by accident on turn 467.** It sent one batch of some twenty actions that pressed
  Escape four times between clicks, and its next screenshot was the game's main menu. Apparently an Escape with
  nothing open brought up the game menu and a later click landed on the button that leaves the game; I did not
  trace which click. The prompt says leaving ends the run, and it did. Opus had opened that menu by mistake
  at least five times in an earlier run without consequence. Whether an accidental exit should cost the rest of
  a run, or the agent should be left to find "Continue" on the main menu, is an open rule.

A GPT-6.2 Astra pair on seed 1002 was still running when this was written.

## Spend

About $347 of API credit so far: $338 on the twelve runs in the table and about $9 on harness tests and aborted
starts (kept under `runs/shakedown/`, not in git). The GPT-6.2 Astra pair still running will add up to $60.
Every run's spend is in [`runs/ledger.jsonl`](../runs/ledger.jsonl).

One uncertainty: OpenAI's usage figures do not show what its server-side compaction pass costs, so GPT-6.2
Astra's totals may be slightly low.

## What this says about the eval

- **It measures something.** The ladder spreads the two models clearly and a team of two is distinguishable
  from one agent. The score comes from the game, and the game refuses the obvious cheats.
- **Budget game time, not turns.** Turns per agent make agents with short turns leave early and let one side of
  a match play on alone.
- **Always report equal game time and equal spend together.** Here they point in opposite directions (ahead,
  and about 0.3x).
- **Several runs per condition are needed before any ratio is believed.** At $17 to $50 a run that is
  affordable for 500 turns; a run to the rocket would be far longer than anything tried here.
- **The interesting team behaviour is in the logs, not the score**: role negotiation, colliding proposals,
  stale beliefs about what a teammate has done. A benchmark of agent societies should publish the chat and the
  reasoning with the numbers.
- **A match needs something worth contesting.** Two sides on an ample map play two solo games. Scarce ore, a
  shared objective only one side can hold, or a score each side can see would give them a reason to compete.
- **Not yet tested:** teams of four or more, a manager role, hostile enemies, and any model from a third lab.
