import pytest

from factoriobench.llm import Outcome
from factoriobench.llm_openai import OpenAIPlayer, computer_action_calls, cost_usd, function_call, strip_images

JPEG = b"\xff\xd8fake"


def names(calls):
    return [(c.name, c.input) for c in calls]


def test_computer_actions_translate_to_the_harness_vocabulary():
    assert names(computer_action_calls("c", 0, {"type": "click", "button": "right", "x": 5, "y": 6, "keys": None})) == [
        ("right_click", {"coordinate": [5, 6]})]
    assert names(computer_action_calls("c", 0, {"type": "click", "button": "left", "x": 5, "y": 6, "keys": ["SHIFT"]})) == [
        ("left_click", {"coordinate": [5, 6], "text": "SHIFT"})]
    assert names(computer_action_calls("c", 0, {"type": "keypress", "keys": ["CTRL", "a"]})) == [("key", {"text": "CTRL+a"})]
    assert names(computer_action_calls("c", 0, {"type": "wait"})) == [("wait", {"duration": 2.0})]
    assert names(computer_action_calls("c", 0, {"type": "move", "x": 1, "y": 2})) == [("mouse_move", {"coordinate": [1, 2]})]
    drag = computer_action_calls("c", 0, {"type": "drag", "path": [{"x": 1, "y": 2}, {"x": 5, "y": 2}, {"x": 5, "y": 9}]})
    assert drag[0].name == "left_click_drag" and drag[0].input["path"] == [[1, 2], [5, 2], [5, 9]]


def test_scroll_becomes_wheel_notches_per_axis():
    calls = computer_action_calls("c", 0, {"type": "scroll", "x": 9, "y": 9, "scroll_x": -100, "scroll_y": 350})
    assert names(calls) == [
        ("scroll", {"coordinate": [9, 9], "scroll_direction": "down", "scroll_amount": 4}),
        ("scroll", {"coordinate": [9, 9], "scroll_direction": "left", "scroll_amount": 1}),
    ]
    assert len({c.id for c in calls}) == 2


def test_unknown_actions_are_reported_not_dropped():
    assert computer_action_calls("c", 0, {"type": "click", "button": "back", "x": 1, "y": 1})[0].name == "unsupported"
    assert computer_action_calls("c", 0, {"type": "teleport"})[0].name == "unsupported"
    assert function_call("f", "fly", {}).name == "unsupported"


def test_functions_fill_the_gaps_in_the_computer_tool():
    assert function_call("f", "hold_key", {"keys": ["w", "d"], "seconds": 2}).input == {"text": "w+d", "duration": 2}
    hold = function_call("f", "mouse_hold", {"x": 3, "y": 4, "button": "right", "seconds": 5})
    assert (hold.name, hold.input) == ("mouse_hold", {"button": "right", "duration": 5, "coordinate": [3, 4]})
    assert function_call("f", "zoom", {"x0": 1, "y0": 2, "x1": 3, "y1": 4}).input == {"region": [1, 2, 3, 4]}
    assert function_call("f", "wait", {"seconds": 7}).input == {"duration": 7}
    click = function_call("f", "click", {"x": 3, "y": 4, "button": "right", "modifiers": ["ctrl"]})
    assert (click.name, click.input) == ("right_click", {"coordinate": [3, 4], "text": "ctrl"})
    assert function_call("f", "click", {"x": 3, "y": 4, "button": "left", "modifiers": []}).input == {"coordinate": [3, 4]}
    press = function_call("f", "press_keys", {"keys": ["ctrl", "c"]})
    assert (press.name, press.input) == ("key", {"text": "ctrl+c"})


def test_cost_separates_cached_written_and_plain_input():
    usage = {"input_tokens": 10_000, "output_tokens": 500,
             "input_tokens_details": {"cached_tokens": 8_000, "cache_write_tokens": 1_500}}
    usd, counts = cost_usd("gpt-6.2-astra", usage)
    assert counts == {"input": 500, "output": 500, "cache_write": 1_500, "cache_read": 8_000}
    assert usd == pytest.approx((500 * 8 + 8_000 * 0.40 + 1_500 * 10 + 500 * 40) / 1e6)


def test_long_context_doubles_input_and_raises_output():
    usage = {"input_tokens": 300_000, "output_tokens": 1_000, "input_tokens_details": {"cached_tokens": 300_000}}
    usd, _ = cost_usd("gpt-6.2-astra", usage)
    assert usd == pytest.approx((2 * 300_000 * 0.40 + 1.5 * 1_000 * 40) / 1e6)


@pytest.fixture
def player(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return OpenAIPlayer("gpt-6.2-astra", "system", transcript=tmp_path / "conversation.jsonl")


def response(*items, usage=None):
    return {"status": "completed", "output": list(items),
            "usage": usage or {"input_tokens": 100, "output_tokens": 10, "input_tokens_details": {}}}


def test_step_flattens_calls_in_order_and_observe_answers_each(player, monkeypatch):
    player.begin("Objective")
    monkeypatch.setattr(player, "_post", lambda body: response(
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "plan"}], "encrypted_content": "x"},
        {"type": "message", "content": [{"type": "output_text", "text": "Walking."}]},
        {"type": "computer_call", "call_id": "c1", "actions": [{"type": "click", "button": "left", "x": 1, "y": 2},
                                                              {"type": "type", "text": "hi"}]},
        {"type": "function_call", "call_id": "f1", "name": "hold_key", "arguments": '{"keys": ["w"], "seconds": 2}'},
    ))
    reply = player.step()
    assert reply.stop == "actions" and reply.text == "Walking." and reply.thinking == "plan"
    # A computer call that is not last gets its own capture, because it can only be answered with a screenshot.
    assert [c.name for c in reply.calls] == ["left_click", "type", "screenshot", "hold_key"]
    outcomes = [Outcome(reply.calls[0]), Outcome(reply.calls[1]), Outcome(reply.calls[2], "", image=b"mid"),
                Outcome(reply.calls[3])]
    player.observe(outcomes, JPEG)
    computer_out, function_out = player.history[-2], player.history[-1]
    assert computer_out["type"] == "computer_call_output" and computer_out["call_id"] == "c1"
    assert computer_out["output"]["type"] == "computer_screenshot" and computer_out["output"]["image_url"].endswith("bWlk")
    assert function_out["call_id"] == "f1"
    assert [part["type"] for part in function_out["output"]] == ["input_text", "input_image"]


def test_a_failed_computer_action_is_reported_in_a_message(player, monkeypatch):
    player.begin("Objective")
    monkeypatch.setattr(player, "_post", lambda body: response(
        {"type": "computer_call", "call_id": "c1", "actions": [{"type": "click", "button": "left", "x": 9999, "y": 2}]}))
    reply = player.step()
    player.observe([Outcome(reply.calls[0], "Error: coordinate outside the screen", error=True)], JPEG)
    assert player.history[-2]["type"] == "computer_call_output"
    assert "outside the screen" in player.history[-1]["content"][0]["text"]


def test_compaction_drops_everything_before_it(player, monkeypatch):
    player.begin("Objective")
    monkeypatch.setattr(player, "_post", lambda body: response(
        {"type": "compaction", "id": "cmp", "encrypted_content": "zzz"},
        {"type": "computer_call", "call_id": "c2", "actions": [{"type": "screenshot"}]}))
    reply = player.step()
    assert player.compactions == 1 and "server-side compaction" in reply.notes
    assert [item.get("type") for item in player.history] == ["compaction", "computer_call"]


def test_incomplete_and_refused_responses(player, monkeypatch):
    player.begin("Objective")
    before = len(player.history)
    monkeypatch.setattr(player, "_post", lambda body: {"status": "incomplete", "output": [{"type": "reasoning"}],
                                                       "incomplete_details": {"reason": "max_output_tokens"}, "usage": {}})
    assert player.step().stop == "cut_off" and len(player.history) == before
    monkeypatch.setattr(player, "_post", lambda body: response(
        {"type": "message", "content": [{"type": "refusal", "refusal": "No."}]}))
    assert player.step().stop == "refusal"
    monkeypatch.setattr(player, "_post", lambda body: response(
        {"type": "message", "content": [{"type": "output_text", "text": "Done."}]}))
    assert player.step().stop == "stopped"


def test_transcript_omits_image_bytes():
    item = {"type": "computer_call_output", "output": {"image_url": "data:image/jpeg;base64,AAAA", "detail": "original"}}
    assert strip_images(item)["output"]["image_url"] == "<image, 27 chars>"
    assert item["output"]["image_url"].endswith("AAAA")


def test_an_empty_computer_call_is_not_replayed(player, monkeypatch):
    player.begin("Objective")
    monkeypatch.setattr(player, "_post", lambda body: response(
        {"type": "message", "content": [{"type": "output_text", "text": "I'll take copper."}]},
        {"type": "computer_call", "call_id": "c9", "actions": []}))
    reply = player.step()
    assert reply.stop == "stopped" and reply.text == "I'll take copper."
    assert "empty computer call dropped" in reply.notes
    assert all(item.get("type") != "computer_call" for item in player.history)
