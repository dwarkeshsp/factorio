"""An OpenAI model's conversation for one run, through the Responses API and its computer tool.

The computer tool clicks, drags, scrolls, types and presses key chords, but it cannot hold a key
or a mouse button down for a duration, wait for a chosen time, or enlarge part of the screen.
Those arrive as function tools with the same names and meanings as on the Claude side, so every
model has the same hands. Context is bounded by the API's own server-side compaction.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .llm import Call, Outcome, Reply

API_URL = "https://api.openai.com/v1/responses"
BUILTIN_WAIT_SECONDS = 2.0  # the computer tool's wait action has no duration; OpenAI's handlers sleep 2 s
SCROLL_UNITS_PER_NOTCH = 100

# USD per million tokens. Source: developers.openai.com/api/docs/models/gpt-6.2-astra, read 18 Nov 2026.
# Above `long_over` input tokens, input and cache rates double and output costs 1.5 times as much.
PRICES: dict[str, dict[str, float]] = {
    "gpt-6.2-astra": {"input": 8.0, "cached": 0.40, "write_30m": 10.0, "write_12h": 20.0, "output": 40.0,
                      "long_over": 272_000},
}

TOOL_NOTES = """

Tool notes: the computer tool's own wait action lasts 2 seconds; call the wait function for any other duration. The computer tool cannot hold a key or a mouse button down, or enlarge part of the screen: use the hold_key, mouse_hold and zoom functions for those. One response can hold either computer-tool actions or function calls, not both. So that a walk or another hold can share a response with clicks and key presses, click and press_keys are also offered as functions; several function calls in one response run in the order you wrote them. In a scroll action, a scroll_y or scroll_x of 100 is one notch of the mouse wheel."""


def _function(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "name": name, "description": description, "strict": True,
            "parameters": {"type": "object", "properties": properties, "required": required,
                           "additionalProperties": False}}


TOOLS = [
    {"type": "computer"},
    _function("hold_key", "Hold one or more keyboard keys down together for a duration, then release them. "
              "W, A, S and D walk.",
              {"keys": {"type": "array", "items": {"type": "string"}, "description": 'For example ["w"] or ["w", "d"].'},
               "seconds": {"type": "number", "description": "Seconds to hold, up to 300."}},
              ["keys", "seconds"]),
    _function("mouse_hold", "Move the pointer to (x, y), press a mouse button, hold it for a duration, then release "
              "it. For example, holding the right button over a resource or a building mines it.",
              {"x": {"type": "integer"}, "y": {"type": "integer"},
               "button": {"type": "string", "enum": ["left", "right", "middle"]},
               "seconds": {"type": "number", "description": "Seconds to hold, up to 300."}},
              ["x", "y", "button", "seconds"]),
    _function("zoom", "Return an enlarged image of the part of the screen between (x0, y0) and (x1, y1), for "
              "reading small text. Coordinates in later actions still refer to the full screenshot.",
              {"x0": {"type": "integer"}, "y0": {"type": "integer"}, "x1": {"type": "integer"}, "y1": {"type": "integer"}},
              ["x0", "y0", "x1", "y1"]),
    _function("wait", "Let the game run for a duration without doing anything.",
              {"seconds": {"type": "number", "description": "Seconds to wait, up to 300."}},
              ["seconds"]),
    _function("click", "Click a mouse button at (x, y). The same as the computer tool's click, offered as a "
              "function so it can share a response with hold_key, mouse_hold and wait.",
              {"x": {"type": "integer"}, "y": {"type": "integer"},
               "button": {"type": "string", "enum": ["left", "right", "middle"]},
               "modifiers": {"type": "array", "items": {"type": "string"},
                             "description": 'Keys held during the click, for example ["ctrl"]. Empty for none.'}},
              ["x", "y", "button", "modifiers"]),
    _function("press_keys", "Press and release a key or a chord of keys once. The same as the computer tool's "
              "keypress, offered as a function so it can share a response with hold_key, mouse_hold and wait.",
              {"keys": {"type": "array", "items": {"type": "string"}, "description": 'For example ["e"] or ["ctrl", "c"].'}},
              ["keys"]),
]

MOUSE_BUTTONS = {"left": "left_click", "right": "right_click", "wheel": "middle_click", "middle": "middle_click"}


def data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.standard_b64encode(jpeg).decode()


def cost_usd(model: str, usage: dict) -> tuple[float, dict[str, int]]:
    """Dollars for one response, and its tokens in the harness's four classes."""
    prices = PRICES[model]
    details = usage.get("input_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0)
    written = int(details.get("cache_write_tokens") or 0)
    written_12h = int((details.get("cache_write_tokens_details") or {}).get("ttl_12h_tokens") or 0)
    total_in = int(usage.get("input_tokens") or 0)
    output = int(usage.get("output_tokens") or 0)  # reasoning tokens are included
    plain = max(0, total_in - cached - written)
    long = total_in > prices["long_over"]
    in_factor, out_factor = (2.0, 1.5) if long else (1.0, 1.0)
    usd = (
        in_factor * (plain * prices["input"] + cached * prices["cached"]
                     + (written - written_12h) * prices["write_30m"] + written_12h * prices["write_12h"])
        + out_factor * output * prices["output"]
    ) / 1e6
    return usd, {"input": plain, "output": output, "cache_write": written, "cache_read": cached}


def modifiers(action: dict) -> dict:
    keys = action.get("keys") or []
    return {"text": "+".join(keys)} if keys else {}


def computer_action_calls(call_id: str, index: int, action: dict) -> list[Call]:
    """Translate one computer-tool action into the harness's vocabulary (usually one Call)."""
    kind = action.get("type")
    here = [action.get("x"), action.get("y")]
    ident = f"{call_id}/{index}"

    def one(name: str, inp: dict) -> list[Call]:
        return [Call(ident, name, inp, "computer")]

    if kind == "click":
        name = MOUSE_BUTTONS.get(action.get("button", "left"))
        if name is None:
            return one("unsupported", {"what": f"mouse button {action.get('button')!r}"})
        return one(name, {"coordinate": here, **modifiers(action)})
    if kind == "double_click":
        return one("double_click", {"coordinate": here, **modifiers(action)})
    if kind == "move":
        return one("mouse_move", {"coordinate": here})
    if kind == "drag":
        path = [[p["x"], p["y"]] if isinstance(p, dict) else list(p) for p in action.get("path") or []]
        if len(path) < 2:
            return one("unsupported", {"what": "a drag with fewer than two points"})
        return one("left_click_drag", {"start_coordinate": path[0], "coordinate": path[-1], "path": path,
                                       **modifiers(action)})
    if kind == "scroll":
        calls = []
        for delta, negative, positive in ((action.get("scroll_y") or 0, "up", "down"),
                                          (action.get("scroll_x") or 0, "left", "right")):
            if delta:
                calls.append(Call(f"{ident}.{positive}", "scroll", {
                    "coordinate": here, "scroll_direction": positive if delta > 0 else negative,
                    "scroll_amount": max(1, round(abs(delta) / SCROLL_UNITS_PER_NOTCH)), **modifiers(action)}, "computer"))
        return calls or one("mouse_move", {"coordinate": here})
    if kind == "keypress":
        return one("key", {"text": "+".join(action.get("keys") or [])})
    if kind == "type":
        return one("type", {"text": action.get("text", "")})
    if kind == "wait":
        return one("wait", {"duration": BUILTIN_WAIT_SECONDS})
    if kind == "screenshot":
        return one("screenshot", {})
    return one("unsupported", {"what": f"computer action {kind!r}"})


def function_call(call_id: str, name: str, args: dict) -> Call:
    ident = f"{call_id}/0"
    if name == "hold_key":
        return Call(ident, "hold_key", {"text": "+".join(args.get("keys") or []), "duration": args.get("seconds")}, "function")
    if name == "mouse_hold":
        return Call(ident, "mouse_hold", {"button": args.get("button"), "duration": args.get("seconds"),
                                          "coordinate": [args.get("x"), args.get("y")]}, "function")
    if name == "zoom":
        return Call(ident, "zoom", {"region": [args.get("x0"), args.get("y0"), args.get("x1"), args.get("y1")]}, "function")
    if name == "wait":
        return Call(ident, "wait", {"duration": args.get("seconds")}, "function")
    if name == "click":
        action = MOUSE_BUTTONS.get(args.get("button", "left"))
        if action is None:
            return Call(ident, "unsupported", {"what": f"mouse button {args.get('button')!r}"}, "function")
        held = {"text": "+".join(args["modifiers"])} if args.get("modifiers") else {}
        return Call(ident, action, {"coordinate": [args.get("x"), args.get("y")], **held}, "function")
    if name == "press_keys":
        return Call(ident, "key", {"text": "+".join(args.get("keys") or [])}, "function")
    return Call(ident, "unsupported", {"what": f"function {name!r}"}, "function")


def strip_images(item: Any) -> Any:
    """A copy of a conversation item for the on-disk transcript, without image bytes."""
    if isinstance(item, dict):
        return {key: (f"<image, {len(value)} chars>" if key == "image_url" and isinstance(value, str) else strip_images(value))
                for key, value in item.items()}
    if isinstance(item, list):
        return [strip_images(value) for value in item]
    return item


class OpenAIPlayer:
    def __init__(self, model: str, system: str, effort: str | None = None, compact_at_tokens: int = 150_000,
                 keep_turns: int = 6, transcript: Path | None = None, log: Callable[..., None] | None = None):
        if model not in PRICES:
            raise KeyError(f"no price for {model}; add it to PRICES in factoriobench/llm_openai.py")
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("set OPENAI_API_KEY to run an OpenAI model")
        self.model = model
        self.effort = effort
        self.compact_at_tokens = compact_at_tokens
        self.transcript = transcript
        # The prompt goes in a developer message, not `instructions`: on this model family the
        # instructions parameter is placed after the input and is never cached.
        self.history: list[dict] = [{"role": "developer", "content": [{"type": "input_text", "text": system + TOOL_NOTES}]}]
        self._record(self.history[0])
        self._pending: list[dict] = []  # the last response's call items, in order
        self.context_tokens = 0
        self.spent_usd = 0.0
        self.totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
        self.compactions = 0

    # --- bookkeeping -------------------------------------------------------
    def _record(self, item: dict) -> None:
        if self.transcript:
            with self.transcript.open("a") as handle:
                handle.write(json.dumps(strip_images(item)) + "\n")

    def _append(self, item: dict) -> None:
        self.history.append(item)
        self._record(item)

    def _post(self, body: dict) -> dict:
        data = json.dumps(body).encode()
        delay = 2.0
        for attempt in range(7):
            request = urllib.request.Request(API_URL, data=data, headers={
                "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"], "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=900) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as err:
                detail = err.read().decode("utf-8", "replace")[:800]
                if err.code in (408, 409, 429, 500, 502, 503, 504) and attempt < 6:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise RuntimeError(f"OpenAI API error {err.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
                if attempt < 6:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise RuntimeError(f"OpenAI API unreachable: {err}") from None
        raise RuntimeError("OpenAI API: retries exhausted")

    # --- conversation ------------------------------------------------------
    def begin(self, text: str) -> None:
        self._append({"role": "user", "content": [{"type": "input_text", "text": text}]})

    def nudge(self, text: str) -> None:
        self._append({"role": "user", "content": [{"type": "input_text", "text": text}]})

    def step(self) -> Reply:
        body: dict[str, Any] = {
            "model": self.model, "store": False, "input": self.history, "tools": TOOLS,
            "reasoning": {"summary": "auto"}, "max_output_tokens": 32000,
            "context_management": [{"type": "compaction", "compact_threshold": self.compact_at_tokens}],
        }
        if self.effort:
            body["reasoning"]["effort"] = self.effort
        # No fallback model on purpose: a benchmark run must be served by one model.
        response = self._post(body)
        usage = response.get("usage") or {}
        usd, counts = cost_usd(self.model, usage)
        self.spent_usd += usd
        for key, value in counts.items():
            self.totals[key] += value
        self.context_tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)

        notes: list[str] = []
        output = response.get("output") or []
        if response.get("status") != "completed":
            # Partial output may hold an unfinished call; do not replay or execute any of it.
            notes.append(f"response {response.get('status')}: {response.get('incomplete_details') or response.get('error')}")
            return Reply("", "", [], "cut_off", usd, counts, notes)

        texts, summaries, refusals, calls = [], [], [], []
        empty: list[dict] = []
        self._pending = []
        for item in output:
            kind = item.get("type")
            if kind == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text":
                        texts.append(part.get("text", ""))
                    elif part.get("type") == "refusal":
                        refusals.append(part.get("refusal", ""))
            elif kind == "reasoning":
                summaries.extend(part.get("text", "") for part in item.get("summary") or [])
            elif kind == "computer_call":
                actions = item.get("actions") or ([item["action"]] if item.get("action") else [])
                if not actions:
                    # Seen from GPT-6.2 Astra alongside a remark: a computer call with no actions. The API
                    # refuses to take such an item back, so it is left out of the history.
                    empty.append(item)
                    notes.append("empty computer call dropped")
                    continue
                self._pending.append(item)
                for index, action in enumerate(actions):
                    calls.extend(computer_action_calls(item["call_id"], index, action))
            elif kind == "function_call":
                self._pending.append(item)
                try:
                    args = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                calls.append(function_call(item["call_id"], item.get("name", ""), args))
            elif kind == "compaction":
                self.compactions += 1
                notes.append("server-side compaction")
        # A computer call that is not the last call of the response still has to be answered with a
        # screenshot, so capture one right after its actions.
        if len(self._pending) > 1:
            staged: list[Call] = []
            for item in self._pending[:-1]:
                staged.extend(c for c in calls if c.id.split("/")[0] == item["call_id"])
                if item["type"] == "computer_call":
                    staged.append(Call(f"{item['call_id']}/shot", "screenshot", {}, "computer"))
            staged.extend(c for c in calls if c.id.split("/")[0] == self._pending[-1]["call_id"])
            calls = staged

        for item in output:
            if not any(item is dropped for dropped in empty):
                self._append(item)
        self._prune()
        if refusals:
            stop = "refusal"
        elif calls:
            stop = "actions"
        else:
            stop = "stopped"
        return Reply(" ".join(texts).strip() or " ".join(refusals).strip(), " ".join(summaries).strip(),
                     calls, stop, usd, counts, notes)

    def observe(self, outcomes: list[Outcome], jpeg: bytes) -> None:
        """Answer every call item of the last response, in order."""
        by_call: dict[str, list[Outcome]] = {}
        for outcome in outcomes:
            by_call.setdefault(outcome.call.id.split("/")[0], []).append(outcome)
        failures: list[str] = []
        last = self._pending[-1]["call_id"] if self._pending else None
        for item in self._pending:
            call_id = item["call_id"]
            mine = by_call.get(call_id, [])
            if item["type"] == "computer_call":
                shot = next((o.image for o in mine if o.call.id.endswith("/shot") and o.image), None)
                failures.extend(o.text for o in mine if o.error)
                # A computer call can only be answered with a screenshot.
                self._append({"type": "computer_call_output", "call_id": call_id,
                              "output": {"type": "computer_screenshot", "image_url": data_url(shot or jpeg),
                                         "detail": "original"}})
            else:
                outcome = mine[0] if mine else None
                content: list[dict] = []
                if outcome and outcome.image:
                    content.append({"type": "input_image", "image_url": data_url(outcome.image), "detail": "original"})
                else:
                    content.append({"type": "input_text", "text": outcome.text if outcome else "Not executed."})
                if call_id == last:
                    content.append({"type": "input_image", "image_url": data_url(jpeg), "detail": "original"})
                only_text = len(content) == 1 and content[0]["type"] == "input_text"
                self._append({"type": "function_call_output", "call_id": call_id,
                              "output": content[0]["text"] if only_text else content})
        if failures:
            self._append({"role": "user", "content": [{"type": "input_text", "text": "Harness: " + " ".join(failures)}]})
        self._pending = []

    # --- context management --------------------------------------------------
    def _prune(self) -> None:
        """Drop everything the newest compaction item replaced.

        The item carries the developer prompt and the user messages forward itself (checked live),
        so they are dropped too rather than sent twice.
        """
        newest = max((i for i, item in enumerate(self.history) if item.get("type") == "compaction"), default=None)
        if newest:
            self.history = self.history[newest:]

    def should_compact(self) -> bool:
        return False  # the API compacts on its own at the threshold

    def compact(self) -> None:
        return None
