from factoriobench import prompts
from factoriobench.run import Run, RunConfig
from factoriobench.scoring import Scorer


def make(tmp_path, **kwargs):
    return Run(RunConfig(out=str(tmp_path / "run"), ledger=str(tmp_path / "ledger.jsonl"), **kwargs))


def test_a_team_shares_the_default_force(tmp_path):
    run = make(tmp_path, models=["claude-opus-5-5", "gpt-6.2-astra"])
    assert [(s.name, s.model, s.force) for s in run.seats] == [
        ("agent-1", "claude-opus-5-5", "player"), ("agent-2", "gpt-6.2-astra", "player")]
    assert run.forces == ["player"]
    run.close()


def test_rivals_get_their_own_force_and_names_continue(tmp_path):
    run = make(tmp_path, models=["claude-opus-5-5", "claude-opus-5-5"], rivals=["gpt-6.2-astra"])
    assert [(s.name, s.force) for s in run.seats] == [("agent-1", "team-1"), ("agent-2", "team-1"), ("agent-3", "team-2")]
    lua = run.forces_lua()
    assert 'game.create_force("team-2")' in lua
    assert 'game.players["agent-3"].force = f' in lua
    assert 'f.set_cease_fire("team-1", true)' in lua and "f.set_friend(home, true)" in lua
    run.close()


def test_winner_is_the_launch_then_the_higher_rung_then_a_tie(tmp_path):
    run = make(tmp_path, models=["claude-opus-5-5"], rivals=["gpt-6.2-astra"])
    snapshot = lambda items, rockets=0: {"tick": 60, "items": items, "fluids": {}, "built": {}, "researched": [],
                                         "rockets_launched": rockets}
    run.scorers = {"team-1": Scorer(), "team-2": Scorer()}
    reports = lambda: {force: run.scorers[force].report() for force in run.forces}
    assert run.winner(reports()) == "tie"
    run.scorers["team-1"].update(snapshot({"iron-plate": 1}))
    run.scorers["team-2"].update(snapshot({"iron-plate": 1, "copper-plate": 1}))
    assert run.winner(reports()) == "team-2"
    run.scorers["team-1"].update(snapshot({"iron-plate": 1}, rockets=1))
    assert run.winner(reports()) == "team-1"
    run.close()


def test_prompts_name_teammates_and_rivals():
    solo = prompts.system_prompt(1280, 720, "agent-1", ["agent-1"])
    assert "same team" not in solo and "Another" not in solo
    team = prompts.system_prompt(1280, 720, "agent-2", ["agent-1", "agent-2"])
    assert "You are agent-2, one of 2 players on the same team" in team and "Another team" not in team
    versus = prompts.system_prompt(1280, 720, "agent-1", ["agent-1", "agent-2"], ["agent-3", "agent-4"])
    assert "Another team" in versus and "agent-3, agent-4" in versus
    duel = prompts.system_prompt(1280, 720, "agent-1", ["agent-1"], ["agent-2"])
    assert "You are agent-1. Another player" in duel
    assert "before the other side does" in prompts.opening(True, ["agent-1"], ["agent-2"])
    assert "in as little game time as you can" in prompts.opening(True, ["agent-1"])
