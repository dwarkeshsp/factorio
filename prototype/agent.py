#!/usr/bin/env python3
"""Native-play Factorio agent: a model plays through screenshots, mouse and keyboard only.

The game process is frozen (SIGSTOP) while the model thinks and resumed (SIGCONT) only
while its actions execute, so game time measures play, not API latency.

Usage:
  agent.py --run-dir DIR --task "..." [--model claude-opus-5-5] [--max-turns 60] [--max-usd 10]
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import anthropic
from PIL import Image

DISPLAY = os.environ.get("DISPLAY", ":77")
ENV = {**os.environ, "DISPLAY": DISPLAY}
NOT_EXECUTED = "Not executed: an earlier computer action in this turn failed."

# USD per million tokens: input, output, cache write (5 min), cache read.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.10),
    "claude-fable-5-2": (8.0, 40.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
}

KEY_ALIASES = {
    "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape",
    "space": "space", "tab": "Tab", "backspace": "BackSpace", "delete": "Delete",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift",
    "super": "super", "cmd": "super", "pageup": "Prior", "pagedown": "Next",
    "home": "Home", "end": "End",
}

SYSTEM = """You are playing the video game Factorio on a Linux desktop, using only the screen, mouse and keyboard, exactly as a human player would.

How this session works:
- The game is frozen while you think. Game time advances only while your actions execute, so there is no rush between actions, but actions themselves take real game time (holding W for 2 seconds walks for 2 seconds).
- You may send several actions in one response; they run in order. A screenshot is taken automatically after your last action, so you rarely need to request one.
- Use hold_key to walk (W/A/S/D). Use zoom when you need to read small text or inspect a detail.
- Screen coordinates are pixels in the screenshot, origin top-left.

Play to complete the objective given by the user. The game shows its own objectives and hints on screen; follow them. Say briefly what you are doing as you go. When the objective is complete, or you are certain you cannot make progress, stop calling tools and say so."""


def sh(*args: str, check: bool = True) -> str:
    return subprocess.run(args, env=ENV, check=check, capture_output=True, text=True).stdout.strip()


class Game:
    """Screen capture, input injection and freeze/resume for one Factorio process."""

    def __init__(self, shots_dir: Path, freeze: bool = True):
        self.pid = int(sh("pgrep", "-f", "bin/x64/factorio").split()[0])
        self.freeze = freeze
        self.shots_dir = shots_dir
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        self.shot_n = 0
        self.frozen = False
        self.play_seconds = 0.0
        self._resumed_at: float | None = None
        self.size = self._detect_size()

    def _detect_size(self) -> tuple[int, int]:
        """The game may draw smaller than the X screen; crop captures to the drawn area."""
        img = self._grab()
        box = img.convert("L").point(lambda p: 255 if p > 8 else 0).getbbox()
        if not box:
            return img.size
        return (box[2], box[3])

    def _grab(self) -> Image.Image:
        raw = subprocess.run(["import", "-window", "root", "png:-"], env=ENV, check=True, capture_output=True).stdout
        return Image.open(io.BytesIO(raw)).convert("RGB")

    def resume(self) -> None:
        if self.freeze and self.frozen:
            os.kill(self.pid, signal.SIGCONT)
            self.frozen = False
            time.sleep(0.15)
        self._resumed_at = time.time()

    def pause(self) -> None:
        if self._resumed_at is not None:
            self.play_seconds += time.time() - self._resumed_at
            self._resumed_at = None
        if self.freeze and not self.frozen:
            os.kill(self.pid, signal.SIGSTOP)
            self.frozen = True

    def capture(self, region: list[int] | None = None) -> dict:
        time.sleep(0.6)  # let the software renderer draw a fresh frame
        img = self._grab().crop((0, 0, *self.size))
        if region:
            x0, y0, x1, y1 = (int(v) for v in region)
            crop = img.crop((max(0, x0), max(0, y0), min(self.size[0], x1), min(self.size[1], y1)))
            scale = min(self.size[0] / crop.width, self.size[1] / crop.height)
            img = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))), Image.LANCZOS)
        self.shot_n += 1
        path = self.shots_dir / f"{self.shot_n:05d}{'_zoom' if region else ''}.png"
        img.save(path)
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}

    # --- input -------------------------------------------------------------
    @staticmethod
    def _keys(combo: str) -> list[str]:
        out = []
        for part in combo.replace(" ", "").split("+"):
            if not part:
                continue
            out.append(KEY_ALIASES.get(part.lower(), part if len(part) > 1 else part.lower()))
        return out

    def _point(self, coord) -> tuple[int, int]:
        x, y = int(coord[0]), int(coord[1])
        if not (0 <= x < self.size[0] and 0 <= y < self.size[1]):
            raise ValueError(f"coordinate {[x, y]} is outside the {self.size[0]}x{self.size[1]} screen")
        return x, y

    def _with_mods(self, mods: str | None, fn) -> None:
        keys = self._keys(mods) if mods else []
        for k in keys:
            sh("xdotool", "keydown", k)
        try:
            fn()
        finally:
            for k in reversed(keys):
                sh("xdotool", "keyup", k)

    def _click(self, inp: dict, button: int, repeat: int = 1) -> None:
        if inp.get("coordinate") is not None:
            x, y = self._point(inp["coordinate"])
            sh("xdotool", "mousemove", str(x), str(y))
            time.sleep(0.08)
        self._with_mods(inp.get("text"), lambda: sh(
            "xdotool", "click", "--repeat", str(repeat), "--delay", "90", str(button)))

    def act(self, name: str, inp: dict):
        """Execute one computer-toolset member. Returns text or a list of content blocks."""
        if name == "screenshot":
            return [self.capture()]
        if name == "zoom":
            return [self.capture(inp["region"])]
        if name == "left_click":
            self._click(inp, 1)
        elif name == "right_click":
            self._click(inp, 3)
        elif name == "middle_click":
            self._click(inp, 2)
        elif name == "double_click":
            self._click(inp, 1, 2)
        elif name == "triple_click":
            self._click(inp, 1, 3)
        elif name == "mouse_move":
            x, y = self._point(inp["coordinate"])
            sh("xdotool", "mousemove", str(x), str(y))
        elif name == "left_click_drag":
            x0, y0 = self._point(inp["start_coordinate"])
            x1, y1 = self._point(inp["coordinate"])

            def drag():
                sh("xdotool", "mousemove", str(x0), str(y0))
                time.sleep(0.1)
                sh("xdotool", "mousedown", "1")
                steps = 12
                for i in range(1, steps + 1):
                    sh("xdotool", "mousemove", str(x0 + (x1 - x0) * i // steps), str(y0 + (y1 - y0) * i // steps))
                    time.sleep(0.04)
                sh("xdotool", "mouseup", "1")
            self._with_mods(inp.get("text"), drag)
        elif name == "left_mouse_down":
            sh("xdotool", "mousedown", "1")
        elif name == "left_mouse_up":
            sh("xdotool", "mouseup", "1")
        elif name == "cursor_position":
            loc = dict(p.split(":") for p in sh("xdotool", "getmouselocation").split()[:2])
            return f"[{loc['x']}, {loc['y']}]"
        elif name == "scroll":
            if inp.get("coordinate") is not None:
                x, y = self._point(inp["coordinate"])
                sh("xdotool", "mousemove", str(x), str(y))
            button = {"up": 4, "down": 5, "left": 6, "right": 7}[inp["scroll_direction"]]
            n = max(1, min(50, int(inp.get("scroll_amount", 1))))
            self._with_mods(inp.get("text"), lambda: sh(
                "xdotool", "click", "--repeat", str(n), "--delay", "60", str(button)))
        elif name == "type":
            sh("xdotool", "type", "--delay", "30", "--", inp["text"])
        elif name == "key":
            combo = "+".join(self._keys(inp["text"]))
            for _ in range(max(1, min(100, int(inp.get("repeat", 1))))):
                sh("xdotool", "key", combo)
                time.sleep(0.06)
        elif name == "hold_key":
            keys = self._keys(inp["text"])
            dur = max(0.0, min(60.0, float(inp["duration"])))
            for k in keys:
                sh("xdotool", "keydown", k)
            try:
                time.sleep(dur)
            finally:
                for k in reversed(keys):
                    sh("xdotool", "keyup", k)
        elif name == "wait":
            time.sleep(max(0.0, min(60.0, float(inp["duration"]))))
        else:
            raise ValueError(f"unknown action {name}")
        return "OK"


def cost_usd(model: str, usage) -> float:
    pin, pout, pwrite, pread = PRICES[model]
    return (
        (usage.input_tokens or 0) * pin
        + (usage.output_tokens or 0) * pout
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * pwrite
        + (getattr(usage, "cache_read_input_tokens", 0) or 0) * pread
    ) / 1e6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument("--max-usd", type=float, default=10.0)
    ap.add_argument("--no-freeze", action="store_true")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    log = (run_dir / "log.jsonl").open("a")

    def emit(**rec) -> None:
        rec["t"] = round(time.time(), 2)
        log.write(json.dumps(rec) + "\n")
        log.flush()

    # Same client setup as clocktower/llm.py: the key lives under MY_ANTHROPIC_API_KEY and
    # is not scoped to a workspace, so the workspace id goes in a header.
    headers = {}
    if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
        headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY") or os.environ["MY_ANTHROPIC_API_KEY"],
        default_headers=headers, max_retries=4, timeout=900,
    )
    game = Game(run_dir / "shots", freeze=not args.no_freeze)
    game.resume()
    first = game.capture()
    game.pause()

    messages = [{"role": "user", "content": [
        {"type": "text", "text": f"Objective: {args.task}\n\nThe screen is {game.size[0]}x{game.size[1]} pixels. Current screen:"},
        first,
    ]}]
    spent, turn, stop = 0.0, 0, "max_turns"
    totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    emit(event="start", model=args.model, effort=args.effort, task=args.task, screen=game.size)

    while turn < args.max_turns:
        turn += 1
        t0 = time.time()
        # No refusal fallback on purpose: a benchmark run must be served by one model.
        with client.messages.stream(
            model=args.model,
            max_tokens=16000,
            system=SYSTEM,
            tools=[{"type": "computer_toolset_20260801"}],
            output_config={"effort": args.effort},
            cache_control={"type": "ephemeral"},
            messages=messages,
        ) as stream:
            resp = stream.get_final_message()
        u = resp.usage
        spent += cost_usd(args.model, u)
        totals["input"] += u.input_tokens or 0
        totals["output"] += u.output_tokens or 0
        totals["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        totals["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        messages.append({"role": "assistant", "content": resp.content})

        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        calls = [b for b in resp.content if b.type == "tool_use"]
        emit(event="turn", turn=turn, think_s=round(time.time() - t0, 1), stop_reason=resp.stop_reason,
             text=text, actions=[{"name": c.name, "input": c.input} for c in calls],
             usd=round(spent, 4), play_s=round(game.play_seconds, 1))
        print(f"[{turn}] ${spent:.2f} play={game.play_seconds:.0f}s | {text[:160]} | "
              + ", ".join(f"{c.name}{json.dumps(c.input)}" for c in calls)[:300], flush=True)

        if resp.stop_reason == "refusal":
            stop = "refusal"
            break
        if not calls:
            stop = "model_stopped"
            break

        results, failed, saw_image = [], False, False
        game.resume()
        try:
            for c in calls:
                res = {"type": "tool_result", "tool_use_id": c.id, "toolset_name": "computer"}
                if failed:
                    res["content"], res["is_error"] = NOT_EXECUTED, True
                else:
                    try:
                        out = game.act(c.name, c.input)
                        res["content"] = out
                        saw_image = isinstance(out, list)
                        time.sleep(0.12)
                    except Exception as err:  # report the failure to the model, skip the rest
                        res["content"], res["is_error"], failed = f"Error: {err}", True, True
                results.append(res)
            if not saw_image:
                last = results[-1]
                shot = game.capture()
                if isinstance(last["content"], str):
                    last["content"] = [{"type": "text", "text": last["content"]}, shot]
                else:
                    last["content"].append(shot)
        finally:
            game.pause()
        messages.append({"role": "user", "content": results})

        if spent >= args.max_usd:
            stop = "budget"
            break

    game.resume()  # leave the game running for inspection
    summary = {"event": "end", "stop": stop, "turns": turn, "usd": round(spent, 4),
               "play_seconds": round(game.play_seconds, 1), "tokens": totals, "screenshots": game.shot_n}
    emit(**summary)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
