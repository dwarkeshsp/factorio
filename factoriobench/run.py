"""One run: one or more models play one freeplay map through their screens until a stop condition.

A solo run is a team of one. With several agents the game advances in rounds: it stays paused
until every agent has replied, then all of their action batches run at the same time, and the
round lasts as long as the longest batch.
"""
from __future__ import annotations

import json
import subprocess
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from . import __version__, prompts
from .client import CLIENT_CONFIG, SCREEN, Client, Display
from .desktop import ActionError, Desktop, encode_jpeg
from .ledger import Ledger
from .llm import HALT_TEXT, Call, Outcome, Reply, make_player
from .scoring import LADDER, TICKS_PER_SECOND, Scorer, game_clock, ladder_check_lua, snapshot_lua
from .server import Server

# Seconds of running game around the models' actions. They are charged as game time, the
# same for every model.
BEFORE_ACTIONS = 0.15  # the client needs a few ticks to see the unpause; input sent sooner is lost
BETWEEN_ACTIONS = 0.1  # lets one input register before the next
AFTER_ACTIONS = 0.3    # lets the last input take effect before the game is paused
RENDER_WAIT = 0.8      # paused, so free; lets slow software-rendered clients draw the frozen state
SNAPSHOT_EVERY = 25    # rounds between full production snapshots in the log


@dataclass
class RunConfig:
    out: str
    models: list[str] = field(default_factory=lambda: ["claude-opus-5-5"])
    rivals: list[str] = field(default_factory=list)  # a second team on the same map, with its own force
    effort: str | None = None
    seed: int = 1001
    peaceful: bool = True
    max_turns: int = 100
    max_usd: float = 5.0
    max_game_hours: float = 40.0
    compact_at_tokens: int = 150_000
    keep_turns: int = 6
    render_threads: int | None = None
    gpu: bool = False
    edition: str = "full"
    ledger: str = "runs/ledger.jsonl"
    budget_usd: float = 500.0


def harness_commit() -> str | None:
    try:
        root = Path(__file__).resolve().parent.parent
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        return out.stdout.strip() or None
    except OSError:
        return None


class Seat:
    """One agent: its display, its game client, its hands and eyes, and its model."""

    def __init__(self, run_dir: Path, name: str, model: str, cfg: RunConfig, force: str = "player"):
        self.name = name
        self.model = model
        self.force = force
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

    def save_shot(self, image: Image.Image, turn: int, suffix: str = "") -> tuple[str, bytes]:
        jpeg = encode_jpeg(image)
        name = f"{turn:05d}_{suffix}.jpg" if suffix else f"{turn:05d}.jpg"
        (self.shots / name).write_bytes(jpeg)
        self.shot_n += 1
        return name, jpeg

    def execute(self, calls: list[Call], turn: int) -> tuple[list[Outcome], list[dict]]:
        """Carry out a batch in order, stopping at the first failure. The game must be running."""
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
                        name, jpeg = self.save_shot(out, turn, f"a{index + 1}_{call.name}")
                        outcomes.append(Outcome(call, "", image=jpeg))
                        entry["shot"] = name
                    else:
                        outcomes.append(Outcome(call, out))
                    time.sleep(BETWEEN_ACTIONS)
                except ActionError as err:
                    outcomes.append(Outcome(call, f"Error: {err}", error=True))
                    entry["error"] = str(err)
                    failed = True
            record.append(entry)
        return outcomes, record

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
        self.server = Server(self.dir / "server", seed=cfg.seed, peaceful=cfg.peaceful, edition=cfg.edition)
        # Without rivals everyone plays in the game's default force. With rivals each side gets its own.
        sides = [("team-1", cfg.models), ("team-2", cfg.rivals)] if cfg.rivals else [("player", cfg.models)]
        self.seats = []
        for force, models in sides:
            for model in models:
                self.seats.append(Seat(self.dir, f"agent-{len(self.seats) + 1}", model, cfg, force=force))
        self.forces = [force for force, _ in sides]
        self.scorers = {force: Scorer() for force in self.forces}
        self.start_tick = 0
        self.ledger = Ledger(Path(cfg.ledger), self.dir.name)
        self.turn = 0
        self.game_ticks = 0
        self.started = time.time()
        self.pool = ThreadPoolExecutor(max_workers=max(2, len(self.seats)))

    # --- logging -----------------------------------------------------------
    def emit(self, **record: Any) -> None:
        record["t"] = round(time.time(), 2)
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
        if cfg.rivals:
            self.server.eval(self.forces_lua())
        self.start_tick = start_tick
        self.scorers = {force: Scorer(start_tick=start_tick) for force in self.forces}
        for seat in self.seats:
            seat.desktop = Desktop(seat.display.name, SCREEN)
        config = {
            **asdict(cfg),
            "agents": [{"name": seat.name, "model": seat.model, "force": seat.force} for seat in self.seats],
            "harness_version": __version__,
            "harness_commit": harness_commit(),
            "prompt_version": prompts.PROMPT_VERSION,
            "factorio_version": game_version,
            "scenario": "freeplay",
            "screen": list(SCREEN),
            "client_config": CLIENT_CONFIG,
            "timing": {"before_actions": BEFORE_ACTIONS, "between_actions": BETWEEN_ACTIONS, "after_actions": AFTER_ACTIONS, "render_wait": RENDER_WAIT},
            "start_tick": start_tick,
        }
        (self.dir / "config.json").write_text(json.dumps(config, indent=2))
        self.emit(event="start", **config)

    def forces_lua(self) -> str:
        """Give each side its own force: its own research, production statistics and buildings.

        Both sides keep the same spawn point and the same charted starting area, are friends with the
        default force (so either can open the crashed ship's containers), and have a cease-fire with
        each other (so turrets and stray shots do not start a war by accident).
        """
        lines = ["local surface = game.surfaces[1]", "local home = game.forces.player",
                 "local spawn = home.get_spawn_position(surface)"]
        for force in self.forces:
            lines += [
                f'local f = game.forces["{force}"] or game.create_force("{force}")',
                "f.set_spawn_position(spawn, surface)",
                "f.set_friend(home, true) home.set_friend(f, true)",
                "f.chart(surface, {{spawn.x - 200, spawn.y - 200}, {spawn.x + 200, spawn.y + 200}})",
            ]
            for other in self.forces:
                if other != force:
                    lines.append(f'if game.forces["{other}"] then f.set_cease_fire("{other}", true) '
                                 f'game.forces["{other}"].set_cease_fire(f, true) end')
            for seat in self.seats:
                if seat.force == force:
                    lines.append(f'game.players["{seat.name}"].force = f')
        lines.append("return true")
        return "\n".join(lines)

    # --- one round -----------------------------------------------------------
    def capture(self, seat: Seat) -> tuple[str, bytes]:
        assert seat.desktop is not None
        return seat.save_shot(seat.desktop.grab(), self.turn)

    def observe(self) -> tuple[dict[str, tuple[str, bytes]], dict[str, list[str]], dict[str, dict]]:
        """With the game paused: capture every screen and read each side's score."""
        time.sleep(RENDER_WAIT)
        shots = {seat.name: self.capture(seat) for seat in self.seats}
        snapshots = {force: self.server.eval(snapshot_lua(force)) for force in self.forces}
        new = {force: self.scorers[force].update(snapshots[force]) for force in self.forces}
        return shots, new, snapshots

    def stop_reason(self, snapshots: dict[str, dict]) -> str | None:
        cfg = self.cfg
        if any(scorer.launched for scorer in self.scorers.values()):
            return "rocket_launched"
        connected = snapshots[self.forces[0]].get("connected") or []
        for seat in self.seats:
            if seat.name not in connected or not seat.client.alive():
                return "left_game"
        if not any(seat.active for seat in self.seats):
            return self.seats[0].stop if len(self.seats) == 1 else "all_agents_stopped"
        if (self.dir / "STOP").exists():
            return "stopped_by_operator"
        if self.spent >= cfg.max_usd:
            return "budget"
        if self.ledger.total_with(self.spent) >= cfg.budget_usd:
            return "overall_budget"
        if self.game_ticks >= cfg.max_game_hours * 3600 * TICKS_PER_SECOND:
            return "game_time_limit"
        if self.turn >= cfg.max_turns:
            return "max_turns"
        return None

    def think(self, seat: Seat) -> tuple[Reply, float]:
        """One model reply, retrying a reply that was cut off before any action."""
        t0 = time.time()
        reply = seat.player.step()
        retries = 0
        while reply.stop == "cut_off" and retries < 2:
            self.emit(event="cut_off", turn=self.turn, agent=seat.name, text=reply.text)
            seat.player.nudge("Your last response was cut off before any action. Continue.")
            reply = seat.player.step()
            retries += 1
        return reply, time.time() - t0

    def play(self) -> str:
        cfg = self.cfg
        shots, _, _ = self.observe()
        for seat in self.seats:
            team = [other.name for other in self.seats if other.force == seat.force]
            rivals = [other.name for other in self.seats if other.force != seat.force]
            seat.player = make_player(
                seat.model, prompts.system_prompt(*SCREEN, name=seat.name, team=team, rivals=rivals), effort=cfg.effort,
                compact_at_tokens=cfg.compact_at_tokens, keep_turns=cfg.keep_turns,
                transcript=self.dir / "agents" / seat.name / "conversation.jsonl",
            )
            # No opening screenshot: the model asks for one, as it would at any other time. A provider
            # that keeps user messages verbatim through compaction would otherwise carry it forever.
            seat.player.begin(prompts.opening(peaceful=cfg.peaceful, team=team, rivals=rivals))
            self.emit(event="observe", turn=0, agent=seat.name, shot=shots[seat.name][0])

        while True:
            self.turn += 1
            playing = [seat for seat in self.seats if seat.active]
            thoughts = dict(zip([s.name for s in playing], self.pool.map(self.think, playing)))
            acting: list[Seat] = []
            for seat in playing:
                reply, think_s = thoughts[seat.name]
                if reply.stop != "actions":
                    seat.active = False
                    seat.stop = {"stopped": "model_stopped", "refusal": "refusal"}.get(reply.stop, reply.stop)
                    self.emit(event="turn", turn=self.turn, agent=seat.name, stop=seat.stop, text=reply.text,
                              thinking=reply.thinking, think_s=round(think_s, 1), usd=round(seat.player.spent_usd, 4),
                              turn_usd=round(reply.usd, 4), tokens=reply.counts)
                    print(f"[{self.turn}] {seat.name} stopped ({seat.stop}): {reply.text[:300]}", flush=True)
                else:
                    acting.append(seat)

            results: dict[str, tuple[list[Outcome], list[dict]]] = {}
            t1 = time.time()
            tick_before = self.game_ticks
            if acting:
                self.server.resume()
                try:
                    time.sleep(BEFORE_ACTIONS)
                    done = self.pool.map(lambda seat: seat.execute(thoughts[seat.name][0].calls, self.turn), acting)
                    results = dict(zip([s.name for s in acting], done))
                    time.sleep(AFTER_ACTIONS)
                finally:
                    self.game_ticks = self.server.pause() - self.start_tick
            act_s = time.time() - t1
            shots, new_by_force, snapshots = self.observe()
            new = new_by_force[self.forces[0]]
            ups = round((self.game_ticks - tick_before) / act_s, 1) if act_s > 0 else None

            for seat in acting:
                reply, think_s = thoughts[seat.name]
                outcomes, actions = results[seat.name]
                name, jpeg = shots[seat.name]
                seat.player.observe(outcomes, jpeg)
                self.emit(
                    event="turn", turn=self.turn, agent=seat.name, think_s=round(think_s, 1), text=reply.text,
                    thinking=reply.thinking, actions=actions, shot=name, usd=round(seat.player.spent_usd, 4),
                    turn_usd=round(reply.usd, 4), tokens=reply.counts, context_tokens=seat.player.context_tokens,
                    notes=reply.notes,
                )
                summary = ", ".join(f"{a['name']}{json.dumps(a['input'])}" for a in actions)
                print(f"[{self.turn}] {seat.name} {game_clock(self.game_ticks)} ${seat.player.spent_usd:.2f} "
                      f"ctx={seat.player.context_tokens // 1000}k | {reply.text[:140]} | {summary[:240]}", flush=True)
            self.emit(event="round", turn=self.turn, game_ticks=self.game_ticks, act_s=round(act_s, 2), ups=ups,
                      new=new, usd=round(self.spent, 4), **({"new_by_force": new_by_force} if cfg.rivals else {}))
            for force, keys in new_by_force.items():
                for key in keys:
                    side = f" [{force}]" if cfg.rivals else ""
                    print(f"      first{side}: {key} at {game_clock(self.game_ticks)}", flush=True)
            if self.turn % SNAPSHOT_EVERY == 0:
                self.emit(event="snapshot", turn=self.turn, snapshot=snapshots[self.forces[0]],
                          **({"snapshots": snapshots} if cfg.rivals else {}))
                self.ledger.record(self.spent)

            stop = self.stop_reason(snapshots)
            if stop:
                return stop
            for seat in self.seats:
                if seat.active and seat.player.should_compact():
                    outcome = seat.player.compact()
                    if outcome is not None:
                        self.emit(event="compaction", turn=self.turn, agent=seat.name, **outcome)
                        print(f"      {seat.name} compaction: {'ok' if outcome.get('ok') else 'failed'} "
                              f"${outcome.get('usd', 0):.3f}", flush=True)

    # --- wrap-up -------------------------------------------------------------
    def finish(self, stop: str, error: str | None = None) -> dict:
        integrity: dict[str, Any] = {}
        finals: dict[str, dict] = {}
        try:
            for force in self.forces:
                finals[force] = self.server.eval(snapshot_lua(force))
                self.scorers[force].update(finals[force])
            integrity = self.server.integrity()
        except Exception as err:  # the server may already be gone; the summary is still worth writing
            integrity = {"clean": None, "error": str(err)}
        reports = {force: self.scorers[force].report() for force in self.forces}
        totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
        agents = []
        for seat in self.seats:
            player = seat.player
            if player:
                for key, value in player.totals.items():
                    totals[key] += value
            agents.append({
                "name": seat.name, "model": seat.model, "force": seat.force, "stop": seat.stop,
                "usd": round(player.spent_usd, 4) if player else 0.0,
                "tokens": player.totals if player else {},
                "compactions": player.compactions if player else 0,
                "screenshots": seat.shot_n,
            })

        def side(force: str) -> dict[str, Any]:
            report, final = reports[force], finals.get(force, {})
            return {
                "rocket_launched": report["rocket_launched"],
                "furthest_rung": report["furthest_rung"],
                "furthest_label": report["furthest_label"],
                "technologies_researched": report["technologies_researched"],
                "production": {"items": final.get("items") or {}, "fluids": final.get("fluids") or {},
                               "built": final.get("built") or {}},
            }

        first = side(self.forces[0])
        summary = {
            "stop": stop,
            "error": error,
            "agents": agents,
            "models": self.cfg.models,
            "rivals": self.cfg.rivals,
            "effort": self.cfg.effort,
            "seed": self.cfg.seed,
            "peaceful": self.cfg.peaceful,
            "turns": self.turn,
            "game_ticks": self.game_ticks,
            "game_time": game_clock(self.game_ticks),
            "usd": round(self.spent, 4),
            "tokens": totals,
            **first,
            "rungs_total": len(LADDER),
            "integrity_clean": integrity.get("clean"),
            "commands_denied": len(integrity.get("commands_denied", [])),
            "commands_run": len(integrity.get("commands_run", [])),
            "wall_seconds": round(time.time() - self.started),
        }
        milestones: dict[str, Any] = reports[self.forces[0]]
        if self.cfg.rivals:
            summary["sides"] = {force: {"models": [s.model for s in self.seats if s.force == force], **side(force)}
                                for force in self.forces}
            summary["winner"] = self.winner(reports)
            milestones = {"sides": reports}
        self.ledger.record(self.spent)
        (self.dir / "milestones.json").write_text(json.dumps(milestones, indent=2))
        (self.dir / "summary.json").write_text(json.dumps(summary, indent=2))
        self.emit(event="end", **summary, integrity=integrity)
        return summary

    def winner(self, reports: dict[str, dict]) -> str:
        """The side that launched; failing that, the higher rung; failing that, a tie."""
        launched = [force for force in self.forces if reports[force]["rocket_launched"]]
        if len(launched) == 1:
            return launched[0]
        if len(launched) > 1:
            return min(launched, key=lambda force: self.scorers[force].firsts["rocket"])
        best = max(reports[force]["furthest_rung"] for force in self.forces)
        leaders = [force for force in self.forces if reports[force]["furthest_rung"] == best]
        return leaders[0] if len(leaders) == 1 else "tie"

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
