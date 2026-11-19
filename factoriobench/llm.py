"""One model's conversation for one run, with prices and context management.

The history is append-only and cached. Editing it client-side invalidates the thinking
blocks that current Claude models bind to their prefix, so when the conversation grows past
a threshold the older part is replaced by the API's own on-demand compaction: a summary
written by the same model, with the most recent turns kept verbatim.
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import anthropic

from .desktop import MOUSE_HOLD_TOOL
from .tools import openai_functions

# USD per million tokens: input, output, 5-minute cache write, cache read.
# Source: platform.claude.com/docs/en/about-claude/pricing, read 18 Nov 2026.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.10),
    "claude-fable-5-2": (8.0, 40.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    # OpenAI: input, output, 30-minute cache write, cached input. Same figures as the Clocktower
    # benchmark's table (checked 17 Nov 2026); the Sol row is the 6.1 Sol price.
    "gpt-6.2-astra": (8.0, 40.0, 10.0, 0.40),
    "gpt-6.2-sol": (2.0, 10.0, 2.5, 0.10),
}
# Haiku 5.5 charges more for a request whose prompt (cached or not) is over 100,000 tokens.
PRICES_LONG_PROMPT = {"claude-haiku-5-5": (100_000, (0.50, 2.50, 0.625, 0.05))}

BETAS = ["compact-2026-09-04", "thinking-binding-controls-2026-08-01"]
MISMATCH_TEXT = "The block is bound to a different conversation"
HALT_TEXT = "Not executed: an earlier computer action in this turn failed."


def _get(usage: Any, name: str) -> int:
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, 0)
    return int(value or 0)


def usage_counts(usage: Any) -> dict[str, int]:
    return {
        "input": _get(usage, "input_tokens"),
        "output": _get(usage, "output_tokens"),
        "cache_write": _get(usage, "cache_creation_input_tokens"),
        "cache_read": _get(usage, "cache_read_input_tokens"),
    }


def cost_usd(model: str, counts: dict[str, int]) -> float:
    if model not in PRICES:
        raise KeyError(f"no price for {model}; add it to PRICES in factoriobench/llm.py")
    prices = PRICES[model]
    if model in PRICES_LONG_PROMPT:
        threshold, long_prices = PRICES_LONG_PROMPT[model]
        if counts["input"] + counts["cache_write"] + counts["cache_read"] > threshold:
            prices = long_prices
    p_in, p_out, p_write, p_read = prices
    return (
        counts["input"] * p_in + counts["output"] * p_out
        + counts["cache_write"] * p_write + counts["cache_read"] * p_read
    ) / 1e6


@dataclass
class Call:
    """One action the model asked for, in the harness's vocabulary (the computer toolset's member names)."""
    id: str
    name: str
    input: dict
    toolset: str | None = None


@dataclass
class Outcome:
    """What happened to one Call. `image` is JPEG bytes for screenshot and zoom."""
    call: Call
    text: str = "OK"
    image: bytes | None = None
    error: bool = False


@dataclass
class Reply:
    text: str
    thinking: str
    calls: list[Call]
    stop: str  # "actions", "stopped", "refusal" or "cut_off"
    usd: float
    counts: dict[str, int]
    notes: list[str] = field(default_factory=list)


def image_block(jpeg: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(jpeg).decode()}}


def count_images(history: list[dict]) -> int:
    total = 0
    for message in history:
        content = message["content"]
        if isinstance(content, str):
            continue
        for block in content:
            if block.get("type") == "image":
                total += 1
            elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                total += sum(1 for inner in block["content"] if inner.get("type") == "image")
    return total


def strip_images(message: dict) -> dict:
    """A copy of a message for the on-disk transcript, without the image bytes."""
    def strip(block: dict) -> dict:
        if block.get("type") == "image":
            data = block.get("source", {}).get("data", "")
            return {"type": "image", "omitted_base64_chars": len(data)}
        if block.get("type") == "tool_result" and isinstance(block.get("content"), list):
            return {**block, "content": [strip(inner) for inner in block["content"]]}
        return block

    content = message["content"]
    return message if isinstance(content, str) else {**message, "content": [strip(block) for block in content]}


class ClaudePlayer:
    def __init__(self, model: str, system: str, effort: str | None = None,
                 compact_at_tokens: int = 150_000, compact_at_images: int = 300, keep_turns: int = 6,
                 summary_instructions: str | None = None, transcript: Path | None = None,
                 log: Callable[..., None] | None = None):
        if model not in PRICES:
            raise KeyError(f"no price for {model}; add it to PRICES in factoriobench/llm.py")
        self.model = model
        self.effort = effort
        # Built once: any change to system or tools invalidates the cache and every thinking block.
        self.system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        self.tools = [{"type": "computer_toolset_20260801"}, MOUSE_HOLD_TOOL]
        self.compact_at_tokens = compact_at_tokens
        self.compact_at_images = compact_at_images
        self.keep_turns = keep_turns
        self.summary_instructions = summary_instructions
        self.transcript = transcript
        self.log = log or (lambda **record: None)
        self.history: list[dict] = []
        self.mismatch = "error"
        self.context_tokens = 0
        self.spent_usd = 0.0
        self.totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
        self.compactions = 0
        headers = {}
        if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
            headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
        key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MY_ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("set ANTHROPIC_API_KEY to run a Claude model")
        self.client = anthropic.Anthropic(api_key=key, default_headers=headers, max_retries=5, timeout=900)

    # --- bookkeeping -------------------------------------------------------
    def _append(self, message: dict) -> None:
        self.history.append(message)
        if self.transcript:
            with self.transcript.open("a") as handle:
                handle.write(json.dumps(strip_images(message)) + "\n")

    def _charge(self, usage: Any) -> tuple[float, dict[str, int]]:
        counts = usage_counts(usage)
        usd = cost_usd(self.model, counts)
        self.spent_usd += usd
        for key, value in counts.items():
            self.totals[key] += value
        return usd, counts

    def _shared(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = dict(
            model=self.model, system=self.system, tools=self.tools, betas=BETAS, max_tokens=16000,
            thinking={"type": "adaptive", "display": "summarized",
                      "block_binding": {"prefix_mismatch_behavior": self.mismatch}},
        )
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        return kwargs

    # --- conversation ------------------------------------------------------
    def begin(self, text: str, jpeg: bytes) -> None:
        self._append({"role": "user", "content": [{"type": "text", "text": text}, image_block(jpeg)]})

    def nudge(self, text: str) -> None:
        self._append({"role": "user", "content": [{"type": "text", "text": text}]})

    def observe(self, outcomes: list[Outcome], note: str, jpeg: bytes) -> None:
        """Answer every call of the last reply; the end-of-turn screenshot rides on the last result."""
        results = []
        for outcome in outcomes:
            content: list[dict] = []
            if outcome.image is not None:
                content.append(image_block(outcome.image))
            elif outcome.text:
                content.append({"type": "text", "text": outcome.text})
            result: dict[str, Any] = {"type": "tool_result", "tool_use_id": outcome.call.id, "content": content}
            if outcome.call.toolset:
                result["toolset_name"] = outcome.call.toolset  # required on results for toolset members
            if outcome.error:
                result["is_error"] = True
            results.append(result)
        # A result marked as an error may hold only text, so after a failed last action the
        # end-of-turn screenshot follows the results as its own blocks.
        if results[-1].get("is_error"):
            results[-1]["content"] = [block for block in results[-1]["content"] if block.get("type") == "text"]
            results.extend([{"type": "text", "text": note}, image_block(jpeg)])
        else:
            results[-1]["content"].extend([{"type": "text", "text": note}, image_block(jpeg)])
        self._append({"role": "user", "content": results})

    def step(self) -> Reply:
        notes: list[str] = []
        while True:
            try:
                # No fallback model on purpose: a benchmark run must be served by one model.
                with self.client.beta.messages.stream(
                    messages=self.history, cache_control={"type": "ephemeral"}, **self._shared()
                ) as stream:
                    response = stream.get_final_message()
                break
            except anthropic.BadRequestError as err:
                if MISMATCH_TEXT in str(err) and self.mismatch == "error":
                    self.mismatch = "drop_block"
                    notes.append("thinking prefix check failed; dropping invalid thinking blocks from now on")
                    continue
                raise
        for change in getattr(response, "input_transformations", None) or []:
            notes.append(f"input transformation: {getattr(change, 'type', change)}")
        usd, counts = self._charge(response.usage)
        self.context_tokens = counts["input"] + counts["cache_read"] + counts["cache_write"] + counts["output"]
        blocks = [block.to_dict() for block in response.content]
        self._append({"role": "assistant", "content": blocks})
        calls = [Call(b["id"], b["name"], b.get("input") or {}, b.get("toolset_name"))
                 for b in blocks if b.get("type") == "tool_use"]
        if response.stop_reason == "refusal":
            stop = "refusal"
        elif calls:
            stop = "actions"
        elif response.stop_reason == "end_turn":
            stop = "stopped"
        else:
            stop = "cut_off"
        return Reply(
            text=" ".join(b["text"] for b in blocks if b.get("type") == "text").strip(),
            thinking=" ".join(b.get("thinking", "") for b in blocks if b.get("type") == "thinking").strip(),
            calls=calls, stop=stop, usd=usd, counts=counts, notes=notes,
        )

    # --- context management --------------------------------------------------
    def should_compact(self) -> bool:
        return (self.context_tokens > self.compact_at_tokens
                or count_images(self.history) > self.compact_at_images)

    def compact(self) -> dict[str, Any] | None:
        """Replace all but the last few turns with the model's own summary.

        Call only when the history ends with a user message (no tool call left open). The cut
        falls where a request was already sent, which keeps the kept turns' thinking valid.
        """
        split = len(self.history) - 2 * self.keep_turns
        if split < 2 or self.history[-1]["role"] != "user":
            return None
        older, recent = self.history[:split], self.history[split:]
        if older[-1]["role"] != "user" or recent[0]["role"] != "assistant":
            return None
        compaction: dict[str, Any] = {"type": "summarize"}
        if self.summary_instructions:
            compaction["instructions"] = self.summary_instructions
        try:
            # The summarised messages end where an earlier request ended, so its cache entry can be read.
            response = self.client.beta.messages.create(
                messages=older, compaction=compaction, cache_control={"type": "ephemeral"}, **self._shared())
        except anthropic.BadRequestError:
            response = self.client.beta.messages.create(messages=older, compaction=compaction, **self._shared())
        usd = 0.0
        counts = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
        # A compaction call reports zero usage at the top level and its real cost per iteration.
        for entry in getattr(response.usage, "iterations", None) or [response.usage]:
            entry_usd, entry_counts = self._charge(entry)
            usd += entry_usd
            for key, value in entry_counts.items():
                counts[key] += value
        if response.stop_reason != "compaction" or not response.content:
            return {"ok": False, "stop_reason": response.stop_reason, "usd": usd, "counts": counts}
        blocks = [block.to_dict() for block in response.content]
        self.history = [{"role": "assistant", "content": blocks}, *recent]
        self.compactions += 1
        summary = " ".join(str(b.get("content") or "") for b in blocks if b.get("type") == "compaction")
        if self.transcript:
            with self.transcript.open("a") as handle:
                handle.write(json.dumps({"role": "compaction", "replaced_messages": len(older),
                                         "kept_messages": len(recent), "content": blocks}) + "\n")
        return {"ok": True, "usd": usd, "counts": counts, "replaced_messages": len(older),
                "kept_messages": len(recent), "summary": summary}


class OpenAIPlayer:
    """An OpenAI model through the Responses API, stateless: every output item, reasoning
    included, is appended to the input of the next request. It acts through function tools
    that mirror the computer toolset one for one (see tools.py)."""

    URL = "https://api.openai.com/v1/responses"

    def __init__(self, model: str, system: str, effort: str | None = None,
                 compact_at_tokens: int = 150_000, compact_at_images: int = 300, keep_turns: int = 6,
                 summary_instructions: str | None = None, transcript: Path | None = None,
                 log: Callable[..., None] | None = None):
        if model not in PRICES:
            raise KeyError(f"no price for {model}; add it to PRICES in factoriobench/llm.py")
        self.key = os.environ.get("OPENAI_API_KEY")
        if not self.key:
            raise RuntimeError("set OPENAI_API_KEY to run an OpenAI model")
        self.model = model
        self.effort = effort
        self.system = {"role": "developer", "content": [{"type": "input_text", "text": system}]}
        self.tools = openai_functions()
        self.compact_at_tokens = compact_at_tokens
        self.compact_at_images = compact_at_images
        self.summary_instructions = summary_instructions
        self.transcript = transcript
        self.history: list[dict] = [self.system]
        self.pending: list[dict] = []  # function calls of the last reply, awaiting their outputs
        self.last_jpeg: bytes | None = None
        self.images = 0
        self.context_tokens = 0
        self.spent_usd = 0.0
        self.totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
        self.compactions = 0
        self.cache_key = f"factoriobench:{id(self) % 10 ** 9}:{int(time.time())}"

    # --- bookkeeping -------------------------------------------------------
    @staticmethod
    def _image(jpeg: bytes) -> dict:
        return {"type": "input_image", "detail": "original",
                "image_url": "data:image/jpeg;base64," + base64.standard_b64encode(jpeg).decode()}

    def _append(self, item: dict) -> None:
        self.history.append(item)
        if self.transcript:
            def strip(value: Any) -> Any:
                if isinstance(value, dict):
                    if value.get("type") == "input_image":
                        return {"type": "input_image", "omitted_base64_chars": len(value.get("image_url", ""))}
                    return {k: ("<omitted>" if k == "encrypted_content" else strip(v)) for k, v in value.items()}
                if isinstance(value, list):
                    return [strip(v) for v in value]
                return value
            with self.transcript.open("a") as handle:
                handle.write(json.dumps(strip(item)) + "\n")

    def _charge(self, usage: dict) -> tuple[float, dict[str, int]]:
        detail = usage.get("input_tokens_details") or {}
        read, write = int(detail.get("cached_tokens") or 0), int(detail.get("cache_write_tokens") or 0)
        counts = {"input": int(usage.get("input_tokens") or 0) - read - write, "output": int(usage.get("output_tokens") or 0),
                  "cache_write": write, "cache_read": read}
        usd = cost_usd(self.model, counts)
        if int(usage.get("input_tokens") or 0) > 272_000:  # long-context pricing: input x2, output x1.5
            p_in, p_out, p_write, p_read = PRICES[self.model]
            usd = (2 * (counts["input"] * p_in + counts["cache_write"] * p_write + counts["cache_read"] * p_read)
                   + 1.5 * counts["output"] * p_out) / 1e6
        self.spent_usd += usd
        for key, value in counts.items():
            self.totals[key] += value
        return usd, counts

    def _post(self, body: dict) -> dict:
        """One streamed request, returning the final response object; transient failures are retried."""
        data = json.dumps({**body, "stream": True}).encode()
        for attempt in range(8):
            try:
                request = urllib.request.Request(self.URL, data=data, method="POST", headers={
                    "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=900) as response:
                    for raw in response:
                        line = raw.decode(errors="replace").strip()
                        if not line.startswith("data: "):
                            continue
                        event = json.loads(line[6:])
                        if event.get("type") in ("response.completed", "response.incomplete", "response.failed"):
                            return event["response"]
                        if event.get("type") == "error":
                            raise ConnectionError(f"stream error: {json.dumps(event)[:500]}")
                raise ConnectionError("stream ended without a final response")
            except urllib.error.HTTPError as err:
                detail = err.read().decode(errors="replace")[:1500]
                if not (err.code in (408, 409, 429) or err.code >= 500) or attempt == 7:
                    raise RuntimeError(f"OpenAI HTTP {err.code}: {detail}") from None
            except (TimeoutError, urllib.error.URLError, ConnectionError, http.client.HTTPException) as err:
                if attempt == 7:
                    raise RuntimeError(f"OpenAI transport error: {err}") from None
            time.sleep(min(2 ** attempt, 60) + random.random())
        raise RuntimeError("unreachable")

    def _body(self, **extra: Any) -> dict:
        reasoning: dict[str, Any] = {"summary": "concise", "context": "all_turns"}
        if self.effort:
            reasoning["effort"] = self.effort
        return {"model": self.model, "store": False, "input": self.history, "tools": self.tools,
                "max_output_tokens": 16000, "reasoning": reasoning, "include": ["reasoning.encrypted_content"],
                "prompt_cache_key": self.cache_key, **extra}

    # --- conversation ------------------------------------------------------
    def begin(self, text: str, jpeg: bytes) -> None:
        self.last_jpeg = jpeg
        self.images += 1
        self._append({"role": "user", "content": [{"type": "input_text", "text": text}, self._image(jpeg)]})

    def nudge(self, text: str) -> None:
        self._append({"role": "user", "content": [{"type": "input_text", "text": text}]})

    def observe(self, outcomes: list[Outcome], note: str, jpeg: bytes) -> None:
        self.last_jpeg = jpeg
        for index, outcome in enumerate(outcomes):
            content: list[dict] = []
            if outcome.image is not None:
                content.append(self._image(outcome.image))
                self.images += 1
            elif outcome.text:
                content.append({"type": "input_text", "text": outcome.text})
            if index == len(outcomes) - 1:
                content.extend([{"type": "input_text", "text": note}, self._image(jpeg)])
                self.images += 1
            self._append({"type": "function_call_output", "call_id": outcome.call.id,
                          "output": content or [{"type": "input_text", "text": "OK"}]})
        self.pending = []

    def step(self) -> Reply:
        response = self._post(self._body())
        usd, counts = self._charge(response.get("usage") or {})
        self.context_tokens = counts["input"] + counts["cache_read"] + counts["cache_write"] + counts["output"]
        output = response.get("output") or []
        for item in output:
            self._append(item)
        calls = []
        for item in output:
            if item.get("type") == "function_call":
                try:
                    arguments = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                # Optional fields arrive as empty strings or nulls; they mean "not given".
                arguments = {k: v for k, v in arguments.items() if v not in ("", None, [])}
                calls.append(Call(item["call_id"], item["name"], arguments))
        self.pending = calls
        parts = [c for item in output if item.get("type") == "message" for c in item.get("content") or []]
        text = " ".join(c.get("text", "") for c in parts if c.get("type") == "output_text").strip()
        thinking = " ".join(part.get("text", "") for item in output if item.get("type") == "reasoning"
                            for part in item.get("summary") or []).strip()
        if any(c.get("type") == "refusal" for c in parts):
            stop = "refusal"
        elif calls:
            stop = "actions"
        elif response.get("status") == "completed":
            stop = "stopped"
        else:
            stop = "cut_off"
        return Reply(text=text, thinking=thinking, calls=calls, stop=stop, usd=usd, counts=counts)

    # --- context management --------------------------------------------------
    def should_compact(self) -> bool:
        return self.context_tokens > self.compact_at_tokens or self.images > self.compact_at_images

    def compact(self) -> dict[str, Any] | None:
        """Ask the model for its own notes, then start the history again from them and the current screen."""
        if self.pending or self.last_jpeg is None:
            return None
        ask = {"role": "user", "content": [{"type": "input_text", "text": self.summary_instructions or "Summarise this session so far."}]}
        response = self._post({**self._body(), "input": [*self.history, ask], "tool_choice": "none"})
        usd, counts = self._charge(response.get("usage") or {})
        parts = [c for item in response.get("output") or [] if item.get("type") == "message" for c in item.get("content") or []]
        summary = " ".join(c.get("text", "") for c in parts if c.get("type") == "output_text").strip()
        if not summary:
            return {"ok": False, "stop_reason": response.get("status"), "usd": usd, "counts": counts}
        replaced = len(self.history) - 1
        self.history = [self.system]
        self.images = 1
        self.compactions += 1
        self._append({"role": "user", "content": [
            {"type": "input_text", "text": "Your notes from the session so far, which replace the earlier messages:\n\n"
                                           + summary + "\n\nThe game continues. Current screen:"},
            self._image(self.last_jpeg)]})
        return {"ok": True, "usd": usd, "counts": counts, "replaced_messages": replaced, "kept_messages": 1, "summary": summary}


def make_player(model: str, system: str, **kwargs: Any):
    if model.startswith("claude-"):
        return ClaudePlayer(model, system, **kwargs)
    if model.startswith("gpt-"):
        return OpenAIPlayer(model, system, **kwargs)
    raise KeyError(f"no player for model {model!r}")
