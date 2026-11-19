from factoriobench.server import parse_console_log

LOG = """=== Log opened 2026-11-19 01:50:45 ===
2026-11-19 01:50:53 [WARNING] Using Lua console commands will disable achievements. Please repeat the command to proceed.
2026-11-19 01:51:41 [JOIN] agent-1 joined the game
2026-11-19 01:52:51 [COMMAND] agent-1 tried to run a command, which isn't allowed for them: game.player.insert{name="iron-plate",count=100}
2026-11-19 01:52:54 [CHAT] agent-1: hello: I am at the iron patch
2026-11-19 01:53:10 [COMMAND] agent-2 (command): game.player.cheat_mode = true
2026-11-19 01:53:23 [LEAVE] agent-1 left the game
"""


def test_console_log_is_sorted_into_chat_refused_and_run_commands():
    parsed = parse_console_log(LOG)
    assert parsed["commands_denied"] == [
        {"player": "agent-1", "text": 'game.player.insert{name="iron-plate",count=100}'}
    ]
    assert parsed["commands_run"] == [{"player": "agent-2", "text": "game.player.cheat_mode = true"}]
    assert parsed["chat"] == [{"player": "agent-1", "text": "hello: I am at the iron patch"}]
    assert [s["event"] for s in parsed["sessions"]] == ["join", "leave"]


def test_an_empty_log_parses_to_nothing():
    assert parse_console_log("") == {"chat": [], "commands_denied": [], "commands_run": [], "sessions": []}
