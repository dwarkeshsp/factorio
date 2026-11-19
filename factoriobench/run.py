"""One run: one model plays one freeplay map through the screen until a stop condition."""
from __future__ import annotations

import base64
import json
import subprocess
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from . import __version__, prompts
from .client import CLIENT_CONFIG, SCREEN, Client, Display
from .desktop import MOUSE_HOLD_TOOL, ActionError, Desktop, encode_jpeg
from .llm import HALT_TEXT, Call, ClaudePlayer, tool_result
from .scoring import SNAPSHOT_LUA, TICKS_PER_SECOND, Scorer, game_clock, ladder_check_lua
from .server import Server

# Seconds of running game around the model's actions. They are charged as game time, the
# same for every model.
BETWEEN_ACTIONS = 0.1  # lets one input register before the next
AFTER_ACTIONS = 0.3    # lets the last input take effect before the game is paused
RENDER_WAIT = 0.25     # paused; lets the client draw the frozen state before the capture


@dataclass
class RunConfig:
    out: str
    model: str = "claude-opus-5-5"
    effort: str | None = None
    seed: int = 1001
    peaceful: bool = True
    max_turns: int = 100
    max_usd: float = 5.0
    max_game_hours: float = 40.0
    player: str = "agent-1"
    compact_at_tokens: int = 150_000
    keep_turns: int = 6
    render_threads: int | None = None
    gpu: bool = False
    edition: str = "full"


def image_block(jpeg: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(jpeg).decode()}}


def harness_commit() -> str | None:
    try:
        root = Path(__file__).resolve().parent.parent
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        return out.stdout.strip() or None
    except OSError:
        return None


class Run:
    def __init__(self, cfg: RunConfig):
        self.cfg = cfg
        self.dir = Path(cfg.out).resolve()
        if (self.dir / "summary.json").exists():
            raise SystemExit(f"{self.dir} already holds a finished run; choose another --out")
        self.shots = self.dir / "shots"
        self.shots.mkdir(parents=True, exist_ok=True)
        self._log = (self.dir / "log.jsonl").open("a")
        self.server = Server(self.dir / "server", seed=cfg.seed, peaceful=cfg.peaceful, edition=cfg.edition)
        self.display = Display(SCREEN)
        self.client = Client(self.dir / "client", self.display, cfg.player, edition=cfg.edition,
                             render_threads=cfg.render_threads, gpu=cfg.gpu)
        self.desktop: Desktop | None = None
        self.scorer = Scorer()
        self.player: ClaudePlayer | None = None
        self.turn = 0
        self.shot_n = 0
        self.game_ticks = 0
        self.started = time.time()

    # --- logging -----------------------------------------------------------
    def emit(self, **record: Any) -> None:
        record["t"] = round(time.time(), 2)
        self._log.write(json.dumps(record) + "\n")
        self._log.flush()

    def save_shot(self, image: Image.Image, suffix: str = "") -> tuple[str, dict]:
        jpeg = encode_jpeg(image)
        if suffix:
            name = f"{self.turn:05d}_{suffix}.jpg"
        else:
            name = f"{self.turn:05d}.jpg"
        (self.shots / name).write_bytes(jpeg)
        self.shot_n += 1
        return name, image_block(jpeg)

    # --- setup -------------------------------------------------------------
    def launch(self) -> None:
        cfg = self.cfg
        self.server.start()
        missing = self.server.eval(ladder_check_lua())
        if missing:
            raise RuntimeError(f"milestone ladder names unknown to this game version: {missing}")
        game_version = self.server.eval("return script.active_mods.base")
        self.display.start()
        self.client.connect(self.server.port)
        deadline = time.time() + 300
        while True:
            if not self.client.alive():
                raise RuntimeError(f"the game client exited during startup; see {self.client.dir / 'stdout.log'}")
            me = [p for p in self.server.players() if p["name"] == cfg.player]
            if me and me[0]["connected"] and me[0]["is_character"]:
                break
            if time.time() > deadline:
                raise RuntimeError("the game client did not join the server in time")
            time.sleep(1.0)
        time.sleep(2.0)  # the first frames after joining are still loading sprites
        start_tick = self.server.pause()
        self.scorer = Scorer(start_tick=start_tick)
        self.desktop = Desktop(self.display.name, SCREEN)
        config = {
            **asdict(cfg),
            "harness_version": __version__,
            "harness_commit": harness_commit(),
            "prompt_version": prompts.PROMPT_VERSION,
            "factorio_version": game_version,
            "scenario": "freeplay",
            "screen": list(SCREEN),
            "client_config": CLIENT_CONFIG,
            "timing": {"between_actions": BETWEEN_ACTIONS, "after_actions": AFTER_ACTIONS, "render_wait": RENDER_WAIT},
            "start_tick": start_tick,
        }
        (self.dir / "config.json").write_text(json.dumps(config, indent=2))
        self.emit(event="start", **config)

    # --- one turn ------------------------------------------------------------
    def execute(self, calls: list[Call]) -> tuple[list[dict], list[dict]]:
        """Run a batch of actions with the game unpaused; return tool results and a log of them."""
        assert self.desktop is not None
        results: list[dict] = []
        record: list[dict] = []
        failed = False
        trailing_screenshot = bool(calls) and calls[-1].name == "screenshot"
        self.server.resume()
        try:
            for index, call in enumerate(calls):
                entry: dict[str, Any] = {"name": call.name, "input": call.input}
                if failed:
                    results.append(tool_result(call, HALT_TEXT, is_error=True))
                    entry["skipped"] = True
                elif trailing_screenshot and index == len(calls) - 1:
                    results.append(tool_result(call, []))  # filled with the end-of-turn capture
                else:
                    try:
                        out = self.desktop.act(call.name, call.input)
                        if isinstance(out, Image.Image):
                            name, block = self.save_shot(out, f"a{index + 1}_{call.name}")
                            results.append(tool_result(call, [block]))
                            entry["shot"] = name
                        else:
                            results.append(tool_result(call, [{"type": "text", "text": out}]))
                        time.sleep(BETWEEN_ACTIONS)
                    except ActionError as err:
                        results.append(tool_result(call, [{"type": "text", "text": f"Error: {err}"}], is_error=True))
                        entry["error"] = str(err)
                        failed = True
                record.append(entry)
            time.sleep(AFTER_ACTIONS)
        finally:
            self.game_ticks = self.server.pause() - self.scorer.start_tick
        return results, record

    def observe(self) -> tuple[str, dict, list[str], dict]:
        """With the game paused: capture the screen and read the score."""
        assert self.desktop is not None
        time.sleep(RENDER_WAIT)
        name, block = self.save_shot(self.desktop.grab())
        snapshot = self.server.eval(SNAPSHOT_LUA)
        new = self.scorer.update(snapshot)
        return name, block, new, snapshot

    def stop_reason(self, snapshot: dict) -> str | None:
        cfg = self.cfg
        assert self.player is not None
        if self.scorer.launched:
            return "rocket_launched"
        if cfg.player not in (snapshot.get("connected") or []) or not self.client.alive():
            return "left_game"
        if (self.dir / "STOP").exists():
            return "stopped_by_operator"
        if self.player.spent_usd >= cfg.max_usd:
            return "budget"
        if self.game_ticks >= cfg.max_game_hours * 3600 * TICKS_PER_SECOND:
            return "game_time_limit"
        if self.turn >= cfg.max_turns:
            return "max_turns"
        return None

    # --- the loop ------------------------------------------------------------
    def play(self) -> str:
        cfg = self.cfg
        objective = prompts.FREEPLAY_OBJECTIVE if cfg.peaceful else prompts.FREEPLAY_OBJECTIVE_HOSTILE
        self.player = ClaudePlayer(
            cfg.model, prompts.system_prompt(*SCREEN), [MOUSE_HOLD_TOOL], effort=cfg.effort,
            compact_at_tokens=cfg.compact_at_tokens, keep_turns=cfg.keep_turns,
            summary_instructions=prompts.SUMMARY_INSTRUCTIONS, transcript=self.dir / "conversation.jsonl",
        )
        name, block, _, _ = self.observe()
        self.player.say([{"type": "text", "text": f"Objective: {objective}\n\nThe game has just started. Current screen:"}, block])
        self.emit(event="observe", turn=0, shot=name)

        while True:
            self.turn += 1
            t0 = time.time()
            reply = self.player.step()
            think_s = time.time() - t0
            if reply.stop_reason == "refusal":
                self.emit(event="turn", turn=self.turn, stop_reason="refusal", text=reply.text, usd=round(self.player.spent_usd, 4))
                return "refusal"
            if not reply.calls:
                self.emit(event="turn", turn=self.turn, stop_reason=reply.stop_reason, text=reply.text,
                          thinking=reply.thinking, usd=round(self.player.spent_usd, 4))
                if reply.stop_reason == "end_turn":
                    return "model_stopped"
                # Cut off mid-thought (for example by the output limit): let it carry on.
                self.player.say([{"type": "text", "text": "Your last response was cut off before any action. Continue."}])
                if self.turn >= cfg.max_turns:
                    return "max_turns"
                continue

            t1 = time.time()
            results, actions = self.execute(reply.calls)
            act_s = time.time() - t1
            name, block, new, snapshot = self.observe()
            last = results[-1]
            if isinstance(last["content"], str):
                last["content"] = [{"type": "text", "text": last["content"]}]
            last["content"].extend([{"type": "text", "text": f"[game time {game_clock(self.game_ticks)}]"}, block])
            self.player.say(results)

            self.emit(
                event="turn", turn=self.turn, think_s=round(think_s, 1), act_s=round(act_s, 2),
                game_ticks=self.game_ticks, stop_reason=reply.stop_reason, text=reply.text, thinking=reply.thinking,
                actions=actions, shot=name, new=new, usd=round(self.player.spent_usd, 4), turn_usd=round(reply.usd, 4),
                tokens=reply.counts, context_tokens=self.player.context_tokens, notes=reply.notes,
            )
            summary = ", ".join(f"{a['name']}{json.dumps(a['input'])}" for a in actions)
            print(f"[{self.turn}] {game_clock(self.game_ticks)} ${self.player.spent_usd:.2f} "
                  f"ctx={self.player.context_tokens // 1000}k | {reply.text[:140]} | {summary[:240]}", flush=True)
            for key in new:
                print(f"      first: {key}", flush=True)
            if self.turn % 25 == 0:
                self.emit(event="snapshot", turn=self.turn, snapshot=snapshot)

            stop = self.stop_reason(snapshot)
            if stop:
                return stop
            if self.player.should_compact():
                outcome = self.player.compact()
                if outcome is not None:
                    self.emit(event="compaction", turn=self.turn, **outcome)
                    print(f"      compaction: {'ok' if outcome.get('ok') else 'failed'} ${outcome.get('usd', 0):.3f}", flush=True)

    def finish(self, stop: str, error: str | None = None) -> dict:
        integrity: dict[str, Any] = {}
        final_snapshot: dict[str, Any] = {}
        try:
            final_snapshot = self.server.eval(SNAPSHOT_LUA)
            self.scorer.update(final_snapshot)
            integrity = self.server.integrity()
        except Exception as err:  # the server may already be gone; the summary is still worth writing
            integrity = {"clean": None, "error": str(err)}
        score = self.scorer.report()
        player = self.player
        summary = {
            "stop": stop,
            "error": error,
            "model": self.cfg.model,
            "effort": self.cfg.effort,
            "seed": self.cfg.seed,
            "peaceful": self.cfg.peaceful,
            "turns": self.turn,
            "game_ticks": self.game_ticks,
            "game_time": game_clock(self.game_ticks),
            "usd": round(player.spent_usd, 4) if player else 0.0,
            "tokens": player.totals if player else {},
            "compactions": player.compactions if player else 0,
            "rocket_launched": score["rocket_launched"],
            "furthest_rung": score["furthest_rung"],
            "furthest_label": score["furthest_label"],
            "rungs_total": score["rungs_total"],
            "technologies_researched": score["technologies_researched"],
            "integrity_clean": integrity.get("clean"),
            "commands_denied": len(integrity.get("commands_denied", [])),
            "commands_run": len(integrity.get("commands_run", [])),
            "screenshots": self.shot_n,
            "wall_seconds": round(time.time() - self.started),
        }
        (self.dir / "milestones.json").write_text(json.dumps(score, indent=2))
        (self.dir / "summary.json").write_text(json.dumps(summary, indent=2))
        self.emit(event="end", **summary, integrity=integrity, final_snapshot=final_snapshot)
        return summary

    def close(self) -> None:
        if self.desktop:
            self.desktop.close()
        self.client.stop()
        self.server.stop()
        self.display.stop()
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
