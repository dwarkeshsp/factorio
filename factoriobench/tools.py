"""The same hands for every model.

Claude models get Anthropic's computer toolset natively. Models from other labs get the same
actions, with the same names and inputs, declared as ordinary function tools, so every model
can do exactly what the others can: nothing more, nothing less.
"""
from __future__ import annotations

from .desktop import MOUSE_HOLD_TOOL

_XY = {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2,
       "description": "[x, y] in screenshot pixels, origin top-left."}
_MODS = {"type": "string", "description": "Modifier keys to hold meanwhile: shift, ctrl, alt, or a +-joined combination."}


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties or {}, "required": required or []}}


def _click(name: str, what: str) -> dict:
    return _tool(name, f"{what} at `coordinate`, or at the current pointer position if it is omitted.",
                 {"coordinate": _XY, "text": _MODS})


TOOLSET = [
    _tool("screenshot", "Capture the screen now and return it as an image."),
    _tool("zoom", "Return one region of the screen enlarged, for reading small text.",
          {"region": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4,
                      "description": "[x0, y0, x1, y1]: top-left and bottom-right corners in screenshot pixels."}},
          ["region"]),
    _click("left_click", "Click the left mouse button"),
    _click("right_click", "Click the right mouse button"),
    _click("middle_click", "Click the middle mouse button"),
    _click("double_click", "Double-click the left mouse button"),
    _click("triple_click", "Triple-click the left mouse button"),
    _tool("left_click_drag", "Press the left button at `start_coordinate`, drag to `coordinate`, and release.",
          {"start_coordinate": _XY, "coordinate": _XY, "text": _MODS}, ["start_coordinate", "coordinate"]),
    _tool("mouse_move", "Move the pointer without clicking.", {"coordinate": _XY}, ["coordinate"]),
    _tool("left_mouse_down", "Press the left mouse button at the current pointer position and keep it down."),
    _tool("left_mouse_up", "Release the left mouse button."),
    _tool("cursor_position", "Report the pointer's position as text."),
    _tool("scroll", "Scroll the mouse wheel at `coordinate`, or at the pointer.",
          {"scroll_direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
           "scroll_amount": {"type": "integer", "description": "Wheel clicks."},
           "coordinate": _XY, "text": _MODS}, ["scroll_direction", "scroll_amount"]),
    _tool("type", "Type literal text at the current keyboard focus.", {"text": {"type": "string"}}, ["text"]),
    _tool("key", "Press a key or a +-joined combination, such as Return, e, ctrl+c or shift+space.",
          {"text": {"type": "string"}, "repeat": {"type": "integer", "description": "Times to press, 1 to 100. Default 1."}},
          ["text"]),
    _tool("hold_key", "Hold a key or +-joined combination down for a duration, for example w to walk north or w+d to walk north-east.",
          {"text": {"type": "string"}, "duration": {"type": "number", "description": "Seconds, up to 300."}},
          ["text", "duration"]),
    _tool("wait", "Let game time pass without doing anything.",
          {"duration": {"type": "number", "description": "Seconds, up to 300."}}, ["duration"]),
    MOUSE_HOLD_TOOL,
]

TOOL_NAMES = [tool["name"] for tool in TOOLSET]


def openai_functions() -> list[dict]:
    return [{"type": "function", "name": tool["name"], "description": tool["description"],
             "parameters": tool["input_schema"]} for tool in TOOLSET]
