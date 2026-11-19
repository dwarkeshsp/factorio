"""One run: one or more teams of models play one freeplay map through their screens until a deadline.

Every agent acts at its own pace, as players do in a real multiplayer game. The game is paused
whenever any agent is thinking; when it runs, every agent's current batch of actions runs at once,
and it is paused again as soon as some agent's batch is finished. An agent still in the middle of a
batch is simply suspended through the pause: its held keys stay down and its timers stop.

A solo run is one team of one. A co-op run is one team of several. A versus run is two teams, each
on its own force with its own buildings, research and score.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from . import __version__, prompts
from .client import CLIENT_CONFIG, SCREEN, Client, Display
from .clock import Clock
from .desktop import ActionError, Desktop, encode_jpeg
from .ledger import Ledger
from .llm import HALT_TEXT, Call, Outcome, Reply, make_player
from .scoring import TICKS_PER_SECOND, Scorer, game_clock, ladder_check_lua, production_score, snapshot_lua
from .server import Server

# Seconds of running game around the models' actions. They are charged as game time, the
# same for every model.
BEFORE_ACTIONS = 0.15  # the client needs a few ticks to see the unpause; input sent sooner is lost
BETWEEN_ACTIONS = 0.1  # lets one input register before the next
AFTER_ACTIONS = 0.3    # lets an agent's last input take effect before the game is paused for it
MIN_RUN = 1.0          # the game runs at least this long between pauses, so each response costs about a second
RENDER_WAIT = 0.7      # paused; lets the clients draw the frozen state before the capture
SNAPSHOT_EVERY = 40    # pauses between full production snapshots in the log
OVERVIEW_EVERY = 20.0  # game seconds between overview frames of the whole base
MAX_REJOINS = 5        # times one player is put back into the game after leaving it

SOLO_FORCE = "player"
TEAM_COLORS = {"red": (0.9, 0.15, 0.1), "blue": (0.15, 0.45, 0.95), "green": (0.1, 0.8, 0.2), "yellow": (0.9, 0.8, 0.1)}
TEAM_SPAWNS = [(-16.0, 0.0), (16.0, 0.0), (0.0, -16.0), (0.0, 16.0)]


@dataclass
class RunConfig:
    out: str
    teams: dict[str, list[str]] = field(default_factory=lambda: {SOLO_FORCE: ["claude-opus-5-5"]})  # team -> models
    effort: str | None = None
    seed: int = 1001
    peaceful: bool = True
    cease_fire: bool = True
    always_day: bool = True      # a screen at night is close to black; the game's own PvP mode offers the same switch
    minutes: float = 20.0        # the deadline, in game minutes
    max_turns: int = 2000        # per agent
    max_usd: float = 25.0        # for the whole run
    compact_at_tokens: int = 100_000
    keep_turns: int = 6
    render_threads: int | None = None
    gpu: bool = False
    edition: str = "full"
    ledger: str = "runs/ledger.jsonl"
    budget_usd: float = 500.0
    overview: bool = True
    org: str = "flat"            # how a team is organised: flat, manager (the first agent leads) or roles (assigned)
    handbook: str | None = None  # a file of notes from an earlier team, given to every agent of the first team
    write_handbook: bool = True  # at the end, ask each agent for the notes it would leave the next team
    throttle: bool = True        # rest the game clients while the models think


def harness_commit() -> str | None:
    try:
        root = Path(__file__).resolve().parent.parent
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        return out.stdout.strip() or None
    except OSError:
        return None


class Throttle:
    """Rests the game clients while the models think.

    A paused game still redraws its frozen screen as fast as it can, which on a CPU-only
    machine keeps every core busy for nothing. While the models think, each client is
    stopped and continued in short bursts: long enough to save most of the CPU, short
    enough that the server never sees it as a lost connection.
    """
    STOPPED, RUNNING = 0.25, 0.06

    def __init__(self, pids: list[int]):
        self.pids = pids
        self._on = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        threading.Thread(target=self._loop, daemon=True, name="throttle").start()

    def _signal(self, sig: int) -> None:
        for pid in self.pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass

    def _loop(self) -> None:
        while True:
            self._on.wait()
            self._idle.clear()
            while self._on.is_set():
                self._signal(signal.SIGSTOP)
                self._on.wait()  # no-op while on; keeps the timing below simple
                time.sleep(self.STOPPED)
                self._signal(signal.SIGCONT)
                time.sleep(self.RUNNING)
            self._idle.set()

    def on(self) -> None:
        self._on.set()

    def off(self) -> None:
        """Returns once every client is running again."""
        self._on.clear()
        self._idle.wait()
        self._signal(signal.SIGCONT)


class Seat:
    """One agent: its display, its game client, its hands and eyes, and its model."""

    def __init__(self, run_dir: Path, name: str, team: str, model: str, cfg: RunConfig, clock: Clock):
        self.name = name
        self.team = team
        self.model = model
        self.clock = clock
        self.dir = run_dir / "agents" / name
        self.shots = self.dir / "shots"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.display = Display(SCREEN)
        self.client = Client(self.dir / "client", self.display, name, edition=cfg.edition,
                             render_threads=cfg.render_threads, gpu=cfg.gpu)
        self.desktop: Desktop | None = None
        self.player: Any = None
        self.active = True
        self.stop: str | None = None
        self.shot_n = 0
        self.turn = 0
        # the batch in flight
        self.reply: Reply | None = None
        self.think_s = 0.0
        self.done = threading.Event()
        self.done_at = 0.0
        self.started_at = 0.0
        self.result: tuple[list[Outcome], list[dict]] | None = None
        self.busy = False
        self.rejoins = 0
        self.rejoined = False  # set when it was put back in; cleared once it has been told

    def save_shot(self, image: Image.Image, suffix: str = "") -> tuple[str, bytes]:
        jpeg = encode_jpeg(image)
        name = f"{self.turn:05d}_{suffix}.jpg" if suffix else f"{self.turn:05d}.jpg"
        (self.shots / name).write_bytes(jpeg)
        self.shot_n += 1
        return name, jpeg

    def start_batch(self, reply: Reply, think_s: float) -> None:
        """Begin carrying out a reply's actions on a thread; they proceed only while the clock runs."""
        self.reply, self.think_s, self.result, self.busy = reply, think_s, None, True
        self.done.clear()
        self.started_at = self.clock.now()
        threading.Thread(target=self._execute, args=(reply.calls,), daemon=True, name=f"batch-{self.name}").start()

    def _execute(self, calls: list[Call]) -> None:
        """Carry out a batch in order, stopping at the first failure."""
        assert self.desktop is not None
        outcomes: list[Outcome] = []
        record: list[dict] = []
        failed = False
        for index, call in enumerate(calls):
            entry: dict[str, Any] = {"name": call.name, "input": call.input}
            if failed:
                outcomes.append(Outcome(call, HALT_TEXT, error=True))
                entry["skipped"] = True
            elif call.name == "screenshot" and index == len(calls) - 1:
                outcomes.append(Outcome(call, ""))  # answered by the end-of-turn capture
            else:
                try:
                    out = self.desktop.act(call.name, call.input)
                    if isinstance(out, Image.Image):
                        name, jpeg = self.save_shot(out, f"a{index + 1}_{call.name}")
                        outcomes.append(Outcome(call, "", image=jpeg))
                        entry["shot"] = name
                    else:
                        outcomes.append(Outcome(call, out))
                    self.clock.sleep(BETWEEN_ACTIONS)
                except ActionError as err:
                    outcomes.append(Outcome(call, f"Error: {err}", error=True))
                    entry["error"] = str(err)
                    failed = True
                except Exception as err:  # never leave the scheduler waiting on a dead thread
                    outcomes.append(Outcome(call, f"Error: {type(err).__name__}: {err}", error=True))
                    entry["error"] = f"{type(err).__name__}: {err}"
                    failed = True
            record.append(entry)
        self.result = (outcomes, record)
        self.done_at = self.clock.now()
        self.done.set()

    def close(self) -> None:
        if self.desktop:
            self.desktop.close()
        self.client.stop()
        self.display.stop()


class Run:
    def __init__(self, cfg: RunConfig):
        self.cfg = cfg
        self.dir = Path(cfg.out).resolve()
        if (self.dir / "summary.json").exists():
            raise SystemExit(f"{self.dir} already holds a finished run; choose another --out")
        self.dir.mkdir(parents=True, exist_ok=True)
        self._log = (self.dir / "log.jsonl").open("a")
        self._log_lock = threading.Lock()
        self.clock = Clock()
        self.server = Server(self.dir / "server", seed=cfg.seed, peaceful=cfg.peaceful, edition=cfg.edition,
                             always_day=cfg.always_day)
        self.versus = len(cfg.teams) > 1
        self.seats: list[Seat] = []
        self.roster: dict[str, list[str]] = {}  # team -> player names
        for team, models in cfg.teams.items():
            prefix = "agent" if team == SOLO_FORCE else team
            names = [f"{prefix}-{i}" for i in range(1, len(models) + 1)]
            self.roster[team] = names
            self.seats += [Seat(self.dir, name, team, model, cfg, self.clock) for name, model in zip(names, models)]
        self.scorers = {team: Scorer() for team in cfg.teams}
        self.scores: dict[str, dict[str, float]] = {team: {"score": 0.0, "gross": 0.0} for team in cfg.teams}
        self.prices: dict[str, float] = {}
        self.ledger = Ledger(Path(cfg.ledger), self.dir.name)
        self.pauses = 0
        self.game_ticks = 0
        self.deadline_ticks = int(cfg.minutes * 60 * TICKS_PER_SECOND)
        self.next_overview = 0.0
        self.view: list[float] | None = None
        self.throttle: Throttle | None = None
        self.started = time.time()
        self.pool = ThreadPoolExecutor(max_workers=max(2, len(self.seats)))

    # --- logging -----------------------------------------------------------
    def emit(self, **record: Any) -> None:
        record["t"] = round(time.time(), 2)
        with self._log_lock:
            self._log.write(json.dumps(record) + "\n")
            self._log.flush()

    @property
    def spent(self) -> float:
        return sum(seat.player.spent_usd for seat in self.seats if seat.player)

    # --- setup -------------------------------------------------------------
    def launch(self) -> None:
        cfg = self.cfg
        self.server.start()
        missing = self.server.eval(ladder_check_lua())
        if missing:
            raise RuntimeError(f"milestone ladder names unknown to this game version: {missing}")
        game_version = self.server.eval("return script.active_mods.base")
        teams = list(cfg.teams)
        spawns = {team: TEAM_SPAWNS[i] for i, team in enumerate(teams)} if self.versus else {}
        colors = {team: TEAM_COLORS[team] for team in teams if team in TEAM_COLORS}
        self.server.configure(self.roster, spawns=spawns, colors=colors, cease_fire=cfg.cease_fire)
        self.prices = self.server.prices()
        (self.dir / "prices.json").write_text(json.dumps(self.prices, indent=1, sort_keys=True))
        for seat in self.seats:
            seat.display.start()
            seat.client.connect(self.server.port)
        names = {seat.name for seat in self.seats}
        deadline = time.time() + 300 + 120 * len(self.seats)
        while True:
            for seat in self.seats:
                if not seat.client.alive():
                    raise RuntimeError(f"{seat.name}'s game client exited during startup; see {seat.client.dir / 'stdout.log'}")
            ready = {p["name"] for p in self.server.players() if p["connected"] and p["is_character"]}
            if names <= ready:
                break
            if time.time() > deadline:
                raise RuntimeError(f"game clients did not all join in time; joined: {sorted(ready)}")
            time.sleep(1.0)
        time.sleep(2.0)  # the first frames after joining are still loading sprites
        start_tick = self.server.pause()
        wrong = [p for p in self.server.players() if p["name"] in names and p["force"] != self.team_of(p["name"])]
        if wrong:
            raise RuntimeError(f"players on the wrong force: {wrong}")
        for scorer in self.scorers.values():
            scorer.start_tick = start_tick
        self.start_tick = start_tick
        for seat in self.seats:
            seat.desktop = Desktop(seat.display.name, SCREEN, clock=self.clock)
        if self.cfg.throttle:
            self.throttle = Throttle([seat.client.proc.pid for seat in self.seats if seat.client.proc])
        config = {
            **asdict(cfg),
            "mode": "versus" if self.versus else ("team" if len(self.seats) > 1 else "solo"),
            "agents": [{"name": seat.name, "team": seat.team, "model": seat.model} for seat in self.seats],
            "spawns": spawns,
            "harness_version": __version__,
            "harness_commit": harness_commit(),
            "prompt_version": prompts.PROMPT_VERSION,
            "factorio_version": game_version,
            "scenario": "freeplay with teams (factoriobench/scenario/control.lua)",
            "screen": list(SCREEN),
            "client_config": CLIENT_CONFIG,
            "timing": {"before_actions": BEFORE_ACTIONS, "between_actions": BETWEEN_ACTIONS,
                       "after_actions": AFTER_ACTIONS, "min_run": MIN_RUN, "render_wait": RENDER_WAIT},
            "start_tick": start_tick,
        }
        (self.dir / "config.json").write_text(json.dumps(config, indent=2))
        self.emit(event="start", **config)

    def team_of(self, name: str) -> str:
        return next(team for team, names in self.roster.items() if name in names)

    # --- observing -----------------------------------------------------------
    def snapshot(self) -> dict:
        snap = self.server.eval(snapshot_lua(list(self.cfg.teams)))
        new: dict[str, list[str]] = {}
        for team, scorer in self.scorers.items():
            force = (snap.get("forces") or {}).get(team) or {}
            new[team] = scorer.update({**force, "tick": snap["tick"]})
            self.scores[team] = production_score(force, self.prices)
        snap["new"] = new
        return snap

    def note(self, seat: Seat) -> str:
        parts = [f"game time {game_clock(self.game_ticks)} of {game_clock(self.deadline_ticks)}"]
        own = f"{self.scores[seat.team]['score']:,.0f}"
        if self.versus:
            others = ", ".join(f"{team} {self.scores[team]['score']:,.0f}" for team in self.cfg.teams if team != seat.team)
            parts.append(f"production score: your team ({seat.team}) {own}, {others}")
        else:
            parts.append(f"production score {own}")
        return "[" + " | ".join(parts) + "]"

    def overview(self) -> None:
        """Ask the first client to write a view of everything built so far to its script-output folder (for the
        timelapse). The frame only ever widens, so the camera does not jump about."""
        if not self.cfg.overview or self.game_ticks / TICKS_PER_SECOND < self.next_overview:
            return
        self.next_overview = self.game_ticks / TICKS_PER_SECOND + OVERVIEW_EVERY
        name = self.seats[0].name
        forces = ", ".join(f'"{team}"' for team in self.cfg.teams)
        try:
            box = self.server.eval(
                f"local x0, y0, x1, y1 = 1e9, 1e9, -1e9, -1e9 "
                f"for _, e in pairs(game.surfaces[1].find_entities_filtered{{force = {{{forces}}}}}) do "
                f"local p = e.position "
                f"if p.x < x0 then x0 = p.x end if p.x > x1 then x1 = p.x end "
                f"if p.y < y0 then y0 = p.y end if p.y > y1 then y1 = p.y end end "
                f"return {{x0, y0, x1, y1}}")
            if box and box[0] <= box[2]:
                view = self.view or box
                self.view = [min(view[0], box[0]), min(view[1], box[1]), max(view[2], box[2]), max(view[3], box[3])]
            if not self.view:
                return
            x0, y0, x1, y1 = self.view
            margin = 12.0
            zoom = min(1280 / ((x1 - x0 + 2 * margin) * 32), 720 / ((y1 - y0 + 2 * margin) * 32))
            zoom = max(0.1, min(0.75, zoom))
            self.server.eval(
                f'local p = game.get_player("{name}") if p then game.take_screenshot{{player = p, by_player = p, '
                f'surface = p.surface, position = {{{(x0 + x1) / 2:.1f}, {(y0 + y1) / 2:.1f}}}, resolution = {{1280, 720}}, '
                f'zoom = {zoom:.4f}, path = "overview/{self.game_ticks:08d}.jpg", quality = 80, show_gui = false, '
                f'show_entity_info = true, daytime = 0}} end')
        except Exception as err:  # the overview is decoration; never let it end a run
            self.emit(event="overview_failed", error=str(err))
            self.cfg.overview = False

    # --- thinking ------------------------------------------------------------
    def think(self, seat: Seat) -> tuple[Reply, float]:
        """One model reply, retrying a reply that was cut off or that stopped before the deadline."""
        t0 = time.time()
        reply = seat.player.step()
        retries = 0
        while reply.stop in ("cut_off", "stopped") and retries < 2:
            self.emit(event=reply.stop, agent=seat.name, turn=seat.turn, text=reply.text)
            seat.player.nudge("Your last response was cut off before any action. Continue."
                              if reply.stop == "cut_off" else prompts.KEEP_PLAYING)
            reply = seat.player.step()
            retries += 1
        return reply, time.time() - t0

    def think_safely(self, seat: Seat) -> tuple[Reply, float]:
        """A model or network failure retires that one agent instead of ending everyone's game."""
        try:
            return self.think(seat)
        except Exception as err:
            self.emit(event="agent_error", agent=seat.name, turn=seat.turn, error=traceback.format_exc())
            print(f"      {seat.name} failed: {type(err).__name__}: {str(err)[:300]}", flush=True)
            return Reply(text=f"{type(err).__name__}: {err}", thinking="", calls=[], stop="error", usd=0.0,
                         counts={"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}), 0.0

    def think_all(self, seats: list[Seat]) -> None:
        """Get a reply from each seat (in parallel) and start its batch, or retire the seat."""
        if not seats:
            return
        if self.throttle:
            self.throttle.on()
        try:
            replies = list(self.pool.map(self.think_safely, seats))
        finally:
            if self.throttle:
                self.throttle.off()
        for seat, (reply, think_s) in zip(seats, replies):
            seat.turn += 1
            if reply.stop != "actions":
                seat.active = False
                seat.busy = False
                seat.stop = {"stopped": "model_stopped"}.get(reply.stop, reply.stop)
                self.emit(event="turn", agent=seat.name, team=seat.team, turn=seat.turn, stop=seat.stop, text=reply.text,
                          thinking=reply.thinking, think_s=round(think_s, 1), usd=round(seat.player.spent_usd, 4),
                          turn_usd=round(reply.usd, 4), tokens=reply.counts)
                print(f"[{game_clock(self.game_ticks)}] {seat.name} stopped ({seat.stop}): {reply.text[:300]}", flush=True)
            else:
                seat.start_batch(reply, think_s)

    # --- the loop ------------------------------------------------------------
    def stop_reason(self, snap: dict) -> str | None:
        cfg = self.cfg
        if self.game_ticks >= self.deadline_ticks:
            return "deadline"
        if any(scorer.launched for scorer in self.scorers.values()):
            return "rocket_launched"
        connected = snap.get("connected") or []
        if any(seat.name not in connected for seat in self.seats):
            return "left_game"  # only reached when putting a player back in has failed
        if not any(seat.active for seat in self.seats):
            return self.seats[0].stop or "model_stopped" if len(self.seats) == 1 else "all_agents_stopped"
        if (self.dir / "STOP").exists():
            return "stopped_by_operator"
        if self.spent >= cfg.max_usd:
            return "budget"
        if self.ledger.total_with(self.spent) >= cfg.budget_usd:
            return "overall_budget"
        if any(seat.turn >= cfg.max_turns for seat in self.seats):
            return "max_turns"
        return None

    def run_until_someone_is_done(self) -> float:
        """Run the game until an agent has finished its batch (or the deadline). Returns seconds run."""
        busy = [seat for seat in self.seats if seat.busy]
        remaining = (self.deadline_ticks - self.game_ticks) / TICKS_PER_SECOND
        self.server.resume()
        time.sleep(BEFORE_ACTIONS)
        self.clock.start()
        t0 = self.clock.now()
        try:
            while True:
                time.sleep(0.02)
                now = self.clock.now()
                ran = now - t0
                if ran >= remaining:
                    break
                finished = [seat for seat in busy if seat.done.is_set()]
                if finished and ran >= MIN_RUN and all(now - seat.done_at >= AFTER_ACTIONS for seat in finished):
                    break
                if any(not seat.client.alive() for seat in self.seats):
                    break
        finally:
            self.clock.stop()
            self.game_ticks = self.server.pause() - self.start_tick
        return self.clock.now() - t0

    def is_connected(self, name: str) -> bool:
        return any(p["name"] == name and p["connected"] and p["is_character"] for p in self.server.players())

    def wait_for(self, name: str, connected: bool, seconds: float, client: Client | None = None) -> bool:
        """Wait until the server reports the player as connected (or not). False if it did not happen in time."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.is_connected(name) == connected:
                return True
            if client is not None and not client.alive():
                return False
            time.sleep(1.0)
        return False

    def rejoin_leavers(self) -> None:
        """Put back any player who is no longer in the game. Call with the game paused.

        The game's own menu has a quit button, and a stray click on it would otherwise end the
        game for everyone. The player keeps its character and inventory; the game stays paused
        while its client reloads, so the others lose nothing, and it is told what happened.
        """
        try:
            connected = {p["name"] for p in self.server.players() if p["connected"]}
        except Exception:
            return
        gone = [seat for seat in self.seats if seat.name not in connected or not seat.client.alive()]
        for seat in gone:
            if seat.rejoins >= MAX_REJOINS:
                continue
            seat.rejoins += 1
            self.emit(event="rejoin", agent=seat.name, n=seat.rejoins, game_ticks=self.game_ticks)
            print(f"      {seat.name} left the game; reconnecting it ({seat.rejoins})", flush=True)
            seat.client.stop()
            # A client that died without saying goodbye is still a connected player to the server
            # until its connection times out; a second client cannot join under that name until then.
            self.wait_for(seat.name, connected=False, seconds=5)
            if self.is_connected(seat.name):
                try:
                    self.server.rcon.command(f"/kick {seat.name} reconnecting")
                except Exception:
                    pass
                self.wait_for(seat.name, connected=False, seconds=90)
            seat.client.connect(self.server.port)
            if self.wait_for(seat.name, connected=True, seconds=420, client=seat.client):
                seat.rejoined = True
            time.sleep(2.0)
        if gone and self.throttle:
            self.throttle.pids = [seat.client.proc.pid for seat in self.seats if seat.client.proc]

    def play(self) -> str:
        cfg = self.cfg
        deadline = game_clock(self.deadline_ticks)
        handbook = Path(cfg.handbook).read_text() if cfg.handbook else None
        time.sleep(RENDER_WAIT)
        for seat in self.seats:
            assert seat.desktop is not None
            seat.player = make_player(
                seat.model,
                prompts.system_prompt(*SCREEN, name=seat.name, deadline=deadline, team=seat.team, teams=self.roster,
                                      peaceful=cfg.peaceful, cease_fire=cfg.cease_fire, org=cfg.org, handbook=handbook),
                effort=cfg.effort, compact_at_tokens=cfg.compact_at_tokens, keep_turns=cfg.keep_turns,
                summary_instructions=prompts.SUMMARY_INSTRUCTIONS,
                transcript=self.dir / "agents" / seat.name / "conversation.jsonl",
            )
            name, jpeg = seat.save_shot(seat.desktop.grab())
            seat.player.begin(prompts.OPENING, jpeg)
            self.emit(event="observe", turn=0, agent=seat.name, shot=name)
        self.think_all(self.seats)

        while True:
            if not any(seat.busy for seat in self.seats):
                return "all_agents_stopped" if len(self.seats) > 1 else (self.seats[0].stop or "model_stopped")
            tick_before = self.game_ticks
            ran = self.run_until_someone_is_done()
            self.pauses += 1
            self.rejoin_leavers()
            time.sleep(RENDER_WAIT)
            finished = [seat for seat in self.seats if seat.busy and seat.done.is_set()]
            shots = {}
            for seat in finished:
                assert seat.desktop is not None
                shots[seat.name] = seat.save_shot(seat.desktop.grab())
            snap = self.snapshot()
            self.overview()
            ups = round((self.game_ticks - tick_before) / ran, 1) if ran > 0 else None

            for seat in finished:
                assert seat.reply is not None and seat.result is not None
                outcomes, actions = seat.result
                name, jpeg = shots[seat.name]
                seat.busy = False
                note = self.note(seat)
                if seat.rejoined:
                    note += " " + prompts.REJOINED
                    seat.rejoined = False
                seat.player.observe(outcomes, note, jpeg)
                reply = seat.reply
                self.emit(
                    event="turn", agent=seat.name, team=seat.team, turn=seat.turn, game_ticks=self.game_ticks,
                    think_s=round(seat.think_s, 1), batch_s=round(seat.done_at - seat.started_at, 2), text=reply.text,
                    thinking=reply.thinking, actions=actions, shot=name, usd=round(seat.player.spent_usd, 4),
                    turn_usd=round(reply.usd, 4), tokens=reply.counts, context_tokens=seat.player.context_tokens,
                    notes=reply.notes,
                )
                summary = ", ".join(f"{a['name']}{json.dumps(a['input'])}" for a in actions)
                print(f"[{game_clock(self.game_ticks)}] {seat.name} t{seat.turn} ${seat.player.spent_usd:.2f} "
                      f"ctx={seat.player.context_tokens // 1000}k | {reply.text[:140]} | {summary[:220]}", flush=True)
            self.emit(event="pause", n=self.pauses, game_ticks=self.game_ticks, ran_s=round(ran, 2), ups=ups,
                      scores={team: s["score"] for team, s in self.scores.items()}, new=snap["new"],
                      players=snap.get("players"), usd=round(self.spent, 4))
            for team, keys in snap["new"].items():
                for key in keys:
                    print(f"      first ({team}): {key} at {game_clock(self.game_ticks)}", flush=True)
            if self.pauses % SNAPSHOT_EVERY == 0:
                self.emit(event="snapshot", n=self.pauses, game_ticks=self.game_ticks, forces=snap.get("forces"))
                self.ledger.record(self.spent)
                print(f"      scores at {game_clock(self.game_ticks)}: "
                      + ", ".join(f"{team} {s['score']:,.0f}" for team, s in self.scores.items())
                      + f" | ${self.spent:.2f} | {ups} ups", flush=True)

            stop = self.stop_reason(snap)
            if stop:
                return stop
            again = [seat for seat in finished if seat.active]
            for seat in again:
                if seat.player.should_compact():
                    outcome = seat.player.compact()
                    if outcome is not None:
                        self.emit(event="compaction", agent=seat.name, turn=seat.turn, **outcome)
                        print(f"      {seat.name} compaction: {'ok' if outcome.get('ok') else 'failed'} "
                              f"${outcome.get('usd', 0):.3f}", flush=True)
            self.think_all(again)

    # --- notes for the next team ---------------------------------------------
    def ask_handbook(self, seat: Seat) -> str:
        """One more reply from an agent after the game: the notes it would leave the next team."""
        assert seat.desktop is not None and seat.player is not None
        if seat.busy and seat.reply is not None:
            # Its last batch was still running at the deadline: close those calls before saying anything else.
            outcomes = [Outcome(call, "Not executed: the game ended.", error=True) for call in seat.reply.calls]
            _, jpeg = seat.save_shot(seat.desktop.grab(), "final")
            seat.player.observe(outcomes, self.note(seat), jpeg)
            seat.busy = False
        mates = self.roster[seat.team]
        score = f"{self.scores[seat.team]['score']:,.0f}"
        if self.versus:
            others = ", ".join(f"{team} {self.scores[team]['score']:,.0f}" for team in self.cfg.teams if team != seat.team)
            result = f"Final production scores: your team ({seat.team}) {score}, {others}."
        else:
            result = f"Your {'team' if len(mates) > 1 else ''} final production score was {score}.".replace("  ", " ")
        seat.player.nudge(prompts.HANDBOOK_REQUEST.format(
            result=result, unit="team" if len(mates) > 1 else "player",
            team_part=", and how a team should split the work and talk to each other" if len(mates) > 1 else ""))
        reply = seat.player.step()
        return reply.text.strip()

    def write_handbooks(self) -> None:
        texts = {}
        for seat, outcome in zip(self.seats, self.pool.map(self._handbook_safely, self.seats)):
            if outcome:
                texts[seat.name] = outcome
                (self.dir / "agents" / seat.name / "handbook.md").write_text(outcome + "\n")
        for team, names in self.roster.items():
            parts = [f"Notes from {name}:\n\n{texts[name]}" for name in names if name in texts]
            if parts:
                name = "handbook.md" if len(self.roster) == 1 else f"handbook-{team}.md"
                (self.dir / name).write_text("\n\n".join(parts) + "\n")
        self.emit(event="handbooks", agents=sorted(texts), usd=round(self.spent, 4))

    def _handbook_safely(self, seat: Seat) -> str | None:
        try:
            return self.ask_handbook(seat) if seat.player is not None and seat.stop != "error" else None
        except Exception:
            self.emit(event="handbook_failed", agent=seat.name, error=traceback.format_exc())
            return None

    # --- wrap-up -------------------------------------------------------------
    def finish(self, stop: str, error: str | None = None) -> dict:
        integrity: dict[str, Any] = {}
        snap: dict[str, Any] = {}
        try:
            snap = self.snapshot()
            integrity = self.server.integrity()
        except Exception as err:  # the server may already be gone; the summary is still worth writing
            integrity = {"clean": None, "error": str(err)}
        forces = snap.get("forces") or {}
        totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
        agents = []
        for seat in self.seats:
            player = seat.player
            if player:
                for key, value in player.totals.items():
                    totals[key] += value
            agents.append({
                "name": seat.name, "team": seat.team, "model": seat.model, "stop": seat.stop, "turns": seat.turn,
                "usd": round(player.spent_usd, 4) if player else 0.0,
                "tokens": player.totals if player else {},
                "compactions": player.compactions if player else 0,
                "screenshots": seat.shot_n,
            })
        teams = {}
        milestones = {}
        for team, scorer in self.scorers.items():
            report = scorer.report()
            milestones[team] = report
            force = forces.get(team) or {}
            teams[team] = {
                "models": self.cfg.teams[team],
                "players": self.roster[team],
                "score": self.scores[team]["score"],
                "gross_production": self.scores[team]["gross"],
                "usd": round(sum(a["usd"] for a in agents if a["team"] == team), 4),
                "turns": sum(a["turns"] for a in agents if a["team"] == team),
                "furthest_rung": report["furthest_rung"],
                "furthest_label": report["furthest_label"],
                "technologies_researched": report["technologies_researched"],
                "rocket_launched": report["rocket_launched"],
                "production": {"items": force.get("items") or {}, "items_used": force.get("items_used") or {},
                               "fluids": force.get("fluids") or {}, "built": force.get("built") or {}},
                "kills": force.get("kills") or {}, "losses": force.get("losses") or {},
            }
        ranked = sorted(teams, key=lambda team: teams[team]["score"], reverse=True)
        winner = None
        if self.versus and stop == "deadline" and teams[ranked[0]]["score"] > teams[ranked[1]]["score"]:
            winner = ranked[0]
        summary = {
            "stop": stop,
            "error": error,
            "mode": "versus" if self.versus else ("team" if len(self.seats) > 1 else "solo"),
            "teams": teams,
            "winner": winner,
            "agents": agents,
            "effort": self.cfg.effort,
            "seed": self.cfg.seed,
            "peaceful": self.cfg.peaceful,
            "cease_fire": self.cfg.cease_fire,
            "org": self.cfg.org,
            "handbook": self.cfg.handbook,
            "deadline_minutes": self.cfg.minutes,
            "pauses": self.pauses,
            "game_ticks": self.game_ticks,
            "game_time": game_clock(self.game_ticks),
            "usd": round(self.spent, 4),
            "tokens": totals,
            "integrity_clean": integrity.get("clean"),
            "commands_denied": len(integrity.get("commands_denied", [])),
            "commands_run": len(integrity.get("commands_run", [])),
            "wall_seconds": round(time.time() - self.started),
        }
        self.ledger.record(self.spent)
        (self.dir / "milestones.json").write_text(json.dumps(milestones, indent=2))
        (self.dir / "summary.json").write_text(json.dumps(summary, indent=2))
        self.emit(event="end", **summary, integrity=integrity)
        return summary

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
        for seat in self.seats:
            seat.close()
        self.server.stop()
        self._log.close()

    def run(self) -> dict:
        stop, error = "error", None
        try:
            self.launch()
            stop = self.play()
            if stop == "deadline" and self.cfg.write_handbook:
                self.write_handbooks()
        except KeyboardInterrupt:
            stop = "interrupted"
        except Exception:
            error = traceback.format_exc()
            print(error, flush=True)
        try:
            return self.finish(stop, error)
        finally:
            self.close()


def run(cfg: RunConfig) -> dict:
    return Run(cfg).run()
