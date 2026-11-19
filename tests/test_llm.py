from types import SimpleNamespace

import pytest

from factoriobench.ledger import Ledger
from factoriobench.llm import Call, ClaudePlayer, Outcome, cost_usd, count_images, strip_images, usage_counts

JPEG = b"\xff\xd8fake"


@pytest.fixture
def player(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    return ClaudePlayer("claude-opus-5-5", "system", keep_turns=2, transcript=tmp_path / "conversation.jsonl")


def test_cost_uses_each_token_class_price():
    counts = {"input": 1_000_000, "output": 1_000_000, "cache_write": 1_000_000, "cache_read": 1_000_000}
    assert cost_usd("claude-opus-5-5", counts) == pytest.approx(4 + 20 + 5 + 0.20)
    with pytest.raises(KeyError):
        cost_usd("claude-unknown", counts)


def test_haiku_long_prompts_cost_more():
    short = {"input": 0, "output": 1000, "cache_write": 0, "cache_read": 90_000}
    long = {"input": 0, "output": 1000, "cache_write": 0, "cache_read": 110_000}
    assert cost_usd("claude-haiku-5-5", short) == pytest.approx((1000 * 0.50 + 90_000 * 0.01) / 1e6)
    assert cost_usd("claude-haiku-5-5", long) == pytest.approx((1000 * 2.50 + 110_000 * 0.05) / 1e6)


def test_usage_counts_reads_objects_and_dicts():
    usage = SimpleNamespace(input_tokens=3, output_tokens=5, cache_creation_input_tokens=None, cache_read_input_tokens=7)
    assert usage_counts(usage) == {"input": 3, "output": 5, "cache_write": 0, "cache_read": 7}
    assert usage_counts({"input_tokens": 1, "output_tokens": 2}) == {"input": 1, "output": 2, "cache_write": 0, "cache_read": 0}


def test_observe_answers_every_call_and_puts_the_screenshot_on_the_last(player):
    player.begin("Objective", JPEG)
    calls = [Call("a", "left_click", {}, "computer"), Call("b", "mouse_hold", {}, None), Call("c", "key", {}, "computer")]
    player.observe(
        [Outcome(calls[0]), Outcome(calls[1], "Error: no button", error=True), Outcome(calls[2], "skipped", error=True)],
        JPEG,
    )
    results = player.history[-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b", "c"]
    assert results[0]["toolset_name"] == "computer" and "toolset_name" not in results[1]
    assert "is_error" not in results[0] and results[1]["is_error"] and results[2]["is_error"]
    assert [b["type"] for b in results[2]["content"]] == ["text", "image"]
    assert count_images(player.history) == 2


def test_transcript_omits_image_bytes(player, tmp_path):
    player.begin("Objective", JPEG)
    text = (tmp_path / "conversation.jsonl").read_text()
    assert "omitted_base64_chars" in text and "/9j" not in text
    assert strip_images({"role": "user", "content": "plain"}) == {"role": "user", "content": "plain"}


def fake_compaction(usd_tokens=1000):
    block = SimpleNamespace(to_dict=lambda: {"type": "compaction", "content": "notes", "signature": "sig"})
    usage = SimpleNamespace(iterations=[{"type": "compaction", "input_tokens": usd_tokens, "output_tokens": 100}])
    return SimpleNamespace(stop_reason="compaction", content=[block], usage=usage)


def test_compaction_keeps_the_last_turns_and_cuts_between_user_and_assistant(player):
    player.begin("Objective", JPEG)
    for i in range(5):
        player.history.append({"role": "assistant", "content": [{"type": "tool_use", "id": str(i), "name": "key", "input": {}}]})
        player.observe([Outcome(Call(str(i), "key", {}, "computer"))], JPEG)
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return fake_compaction()

    player.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    outcome = player.compact()
    assert outcome["ok"] and outcome["replaced_messages"] == 7 and outcome["kept_messages"] == 4
    assert sent["messages"][-1]["role"] == "user" and sent["compaction"]["type"] == "summarize"
    assert player.history[0]["content"][0]["type"] == "compaction"
    assert [m["role"] for m in player.history] == ["assistant", "assistant", "user", "assistant", "user"]
    assert player.spent_usd == pytest.approx((1000 * 4 + 100 * 20) / 1e6)
    assert player.compactions == 1


def test_compaction_is_skipped_when_there_is_too_little_to_summarise(player):
    player.begin("Objective", JPEG)
    player.history.append({"role": "assistant", "content": []})
    player.observe([Outcome(Call("0", "key", {}, "computer"))], JPEG)
    assert player.compact() is None


def test_ledger_totals_across_runs(tmp_path):
    path = tmp_path / "ledger.jsonl"
    first, second = Ledger(path, "a"), Ledger(path, "b")
    first.record(1.5)
    first.record(2.0)
    second.record(0.25)
    assert first.total() == pytest.approx(2.25)
    assert second.total_with(1.25) == pytest.approx(3.25)
    first.record(2.0)
    assert first.total() == pytest.approx(2.25)
