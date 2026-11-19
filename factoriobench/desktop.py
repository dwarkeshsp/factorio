"""Screen capture and mouse/keyboard input on one X display.

`Desktop.act` implements every member of Anthropic's computer toolset (computer_toolset_20260801)
plus `mouse_hold`, which presses and holds any mouse button. The toolset can hold a key but
only the left mouse button, and Factorio mines with a held right button; without this a model
has to rebind the game's controls before it can mine, which tests the tool, not the play.
"""
from __future__ import annotations

import io
import os
import subprocess
from typing import Any

import mss
from PIL import Image

from .clock import WallClock

MAX_HOLD_SECONDS = 300.0  # the toolset's documented limit for hold_key and wait
MAX_ZOOM = 4.0
JPEG_QUALITY = 90

KEY_ALIASES = {
    "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape",
    "space": "space", "tab": "Tab", "backspace": "BackSpace", "delete": "Delete", "del": "Delete",
    "insert": "Insert", "home": "Home", "end": "End",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "pageup": "Prior", "page_up": "Prior", "pagedown": "Next", "page_down": "Next",
    "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "option": "alt", "shift": "shift",
    "super": "super", "cmd": "super", "win": "super", "meta": "super",
    "capslock": "Caps_Lock", "plus": "plus", "minus": "minus",
    "arrowup": "Up", "arrowdown": "Down", "arrowleft": "Left", "arrowright": "Right",
    "command": "super", "grave": "grave", "backquote": "grave", "backtick": "grave", "tilde": "grave",
}
SYMBOLS = {
    "`": "grave", "~": "asciitilde", "-": "minus", "=": "equal", "[": "bracketleft", "]": "bracketright",
    ";": "semicolon", "'": "apostrophe", ",": "comma", ".": "period", "/": "slash", "\\": "backslash",
    "+": "plus", " ": "space",
}
BUTTONS = {"left": 1, "middle": 2, "right": 3}
SCROLL_BUTTONS = {"up": 4, "down": 5, "left": 6, "right": 7}

MOUSE_HOLD_TOOL = {
    "name": "mouse_hold",
    "description": (
        "Press a mouse button, hold it for a duration, then release it. Use this for anything that needs a "
        "held mouse button other than a left-button drag, for example holding the right button over a "
        "resource or building to mine it. The pointer moves to `coordinate` first when it is given."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "duration": {"type": "number", "description": "Seconds to hold, up to 300."},
            "coordinate": {
                "type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2,
                "description": "[x, y] in screenshot pixels. Omit to hold at the current pointer position.",
            },
            "text": {"type": "string", "description": "Modifier keys to hold meanwhile, such as shift or ctrl+shift."},
        },
        "required": ["button", "duration"],
    },
}


class ActionError(ValueError):
    """An action the model asked for that cannot be carried out; reported back to it."""


def parse_keys(combo: str) -> list[str]:
    """Turn 'ctrl+s', 'W', 'Return' or '`' into xdotool key names."""
    if not combo or not combo.strip():
        raise ActionError("no key given")
    text = combo.strip()
    if text == "+":
        return ["plus"]
    if text.endswith("++"):
        text = text[:-1] + "plus"
    keys = []
    for part in text.split("+"):
        part = part.strip()
        if not part:
            raise ActionError(f"cannot read key combination {combo!r}")
        if part in SYMBOLS:
            keys.append(SYMBOLS[part])
        elif part.lower() in KEY_ALIASES:
            keys.append(KEY_ALIASES[part.lower()])
        elif len(part) == 1:
            keys.append(part.lower())
        else:
            keys.append(part)
    return keys


def seconds(value: Any, what: str) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        raise ActionError(f"{what} needs a duration in seconds") from None
    if not 0 <= duration <= MAX_HOLD_SECONDS:
        raise ActionError(f"{what} duration must be between 0 and {MAX_HOLD_SECONDS:.0f} seconds")
    return duration


def encode_jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


class Desktop:
    def __init__(self, display: str, size: tuple[int, int], move_settle: float = 0.15, clock=None):
        self.display = display
        self.size = size
        self.clock = clock or WallClock()
        # Seconds between moving the pointer and clicking. The game learns the pointer's position a few
        # ticks late, so a click sent too soon lands on whatever was under the pointer before.
        self.move_settle = move_settle
        self._env = {**os.environ, "DISPLAY": display}
        self._grabber = mss.MSS(display=display)

    def close(self) -> None:
        self._grabber.close()

    # --- screen ------------------------------------------------------------
    def grab(self) -> Image.Image:
        shot = self._grabber.grab({"left": 0, "top": 0, "width": self.size[0], "height": self.size[1]})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    def zoom(self, region: Any) -> Image.Image:
        try:
            x0, y0, x1, y1 = (int(v) for v in region)
        except (TypeError, ValueError):
            raise ActionError("zoom needs region [x0, y0, x1, y1]") from None
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(self.size[0], x1), min(self.size[1], y1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            raise ActionError(f"zoom region is empty or outside the {self.size[0]}x{self.size[1]} screen")
        crop = self.grab().crop((x0, y0, x1, y1))
        scale = min(self.size[0] / crop.width, self.size[1] / crop.height, MAX_ZOOM)
        return crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.LANCZOS)

    # --- input -------------------------------------------------------------
    def _x(self, *args: str) -> str:
        self.clock.checkpoint()  # never send input to a paused game
        result = subprocess.run(["xdotool", *args], env=self._env, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise ActionError(f"input failed: {result.stderr.strip() or 'xdotool error'}")
        return result.stdout.strip()

    def _point(self, coordinate: Any) -> tuple[int, int]:
        try:
            x, y = int(coordinate[0]), int(coordinate[1])
        except (TypeError, ValueError, IndexError):
            raise ActionError("coordinate must be [x, y]") from None
        if not (0 <= x < self.size[0] and 0 <= y < self.size[1]):
            raise ActionError(f"coordinate [{x}, {y}] is outside the {self.size[0]}x{self.size[1]} screen")
        return x, y

    def _move(self, coordinate: Any) -> None:
        if coordinate is not None:
            x, y = self._point(coordinate)
            self._x("mousemove", str(x), str(y))
            self.clock.sleep(self.move_settle)

    def _held(self, modifiers: str | None, action) -> None:
        keys = parse_keys(modifiers) if modifiers else []
        for key in keys:
            self._x("keydown", key)
        try:
            action()
        finally:
            for key in reversed(keys):
                self._x("keyup", key)

    def _click(self, inp: dict, button: int, count: int = 1) -> None:
        self._move(inp.get("coordinate"))
        self._held(inp.get("text"), lambda: self._x("click", "--repeat", str(count), "--delay", "90", str(button)))

    def _scroll(self, direction: int, amount: int) -> None:
        # In short bursts, so a pause never has to wait long for one input call to finish.
        while amount > 0:
            burst = min(amount, 5)
            self._x("click", "--repeat", str(burst), "--delay", "50", str(direction))
            amount -= burst

    def act(self, name: str, inp: dict) -> str | Image.Image:
        """Carry out one action. Returns text, or an image for screenshot and zoom."""
        if name == "screenshot":
            return self.grab()
        if name == "zoom":
            return self.zoom(inp.get("region"))
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
            if inp.get("coordinate") is None:
                raise ActionError("mouse_move needs a coordinate")
            self._move(inp["coordinate"])
        elif name == "left_click_drag":
            # A drag is a start and an end, or a whole path of points to pass through.
            path = [self._point(p) for p in inp["path"]] if inp.get("path") else [
                self._point(inp.get("start_coordinate")), self._point(inp.get("coordinate"))]
            if len(path) < 2:
                raise ActionError("a drag needs at least two points")

            def drag() -> None:
                self._x("mousemove", str(path[0][0]), str(path[0][1]))
                self.clock.sleep(0.1)
                self._x("mousedown", "1")
                try:
                    for (x0, y0), (x1, y1) in zip(path, path[1:]):
                        steps = max(1, min(12, max(abs(x1 - x0), abs(y1 - y0)) // 8))
                        for i in range(1, steps + 1):
                            self._x("mousemove", str(x0 + (x1 - x0) * i // steps), str(y0 + (y1 - y0) * i // steps))
                            self.clock.sleep(0.03)
                finally:
                    self._x("mouseup", "1")

            self._held(inp.get("text"), drag)
        elif name == "left_mouse_down":
            self._x("mousedown", "1")
        elif name == "left_mouse_up":
            self._x("mouseup", "1")
        elif name == "mouse_hold":
            button = BUTTONS.get(str(inp.get("button", "")).lower())
            if button is None:
                raise ActionError("mouse_hold button must be left, right or middle")
            duration = seconds(inp.get("duration"), "mouse_hold")
            self._move(inp.get("coordinate"))

            def hold() -> None:
                self._x("mousedown", str(button))
                try:
                    self.clock.sleep(duration)
                finally:
                    self._x("mouseup", str(button))

            self._held(inp.get("text"), hold)
        elif name == "cursor_position":
            fields = dict(part.split(":") for part in self._x("getmouselocation").split()[:2])
            return f"X={fields['x']}, Y={fields['y']}"
        elif name == "scroll":
            direction = SCROLL_BUTTONS.get(str(inp.get("scroll_direction", "")).lower())
            if direction is None:
                raise ActionError("scroll_direction must be up, down, left or right")
            try:
                amount = max(1, min(50, int(inp.get("scroll_amount", 1))))
            except (TypeError, ValueError):
                raise ActionError("scroll_amount must be a number") from None
            self._move(inp.get("coordinate"))
            self._held(inp.get("text"), lambda: self._scroll(direction, amount))
        elif name == "type":
            if not isinstance(inp.get("text"), str):
                raise ActionError("type needs text")
            text = inp["text"]
            for start in range(0, len(text), 8):
                self._x("type", "--delay", "25", "--", text[start:start + 8])
        elif name == "key":
            combo = "+".join(parse_keys(inp.get("text", "")))
            try:
                repeat = max(1, min(100, int(inp.get("repeat", 1))))
            except (TypeError, ValueError):
                raise ActionError("repeat must be a number") from None
            for _ in range(repeat):
                self._x("key", combo)
                self.clock.sleep(0.05)
        elif name == "hold_key":
            keys = parse_keys(inp.get("text", ""))
            duration = seconds(inp.get("duration"), "hold_key")
            for key in keys:
                self._x("keydown", key)
            try:
                self.clock.sleep(duration)
            finally:
                for key in reversed(keys):
                    self._x("keyup", key)
        elif name == "wait":
            self.clock.sleep(seconds(inp.get("duration"), "wait"))
        elif name == "unsupported":
            raise ActionError(f"{inp.get('what', 'that action')} is not supported here")
        else:
            raise ActionError(f"unknown action {name!r}")
        return "OK"
