import json

from factoriobench.analyze import compare, produced_at, production_curve, team_ratio


def write_run(path, snapshots, end_ticks, end_items, agents=("claude-opus-5-5",)):
    path.mkdir(parents=True)
    records = [{"event": "start", "start_tick": 600, "agents": [{"name": f"agent-{i + 1}", "model": m, "force": "player"}
                                                               for i, m in enumerate(agents)]}]
    for turn, ticks, items, new in snapshots:
        records.append({"event": "round", "turn": turn, "game_ticks": ticks, "usd": turn * 0.03, "new": new, "act_s": 2, "ups": 60})
        records.append({"event": "snapshot", "turn": turn, "snapshot": {"tick": 600 + ticks, "items": items}})
    last_turn = snapshots[-1][0] + 5
    records.append({"event": "round", "turn": last_turn, "game_ticks": end_ticks, "usd": 1.0, "new": [], "act_s": 2, "ups": 60})
    records.append({"event": "end", "stop": "max_turns", "production": {"items": end_items}})
    (path / "log.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def test_production_is_interpolated_between_snapshots(tmp_path):
    run = write_run(tmp_path / "solo" / "a", [(25, 18000, {"iron-plate": 100}, ["item:iron-plate"])], 36000, {"iron-plate": 300})
    curve = production_curve(run)
    assert [round(minute, 1) for minute, _, _ in curve] == [0.0, 5.0, 10.0]
    assert produced_at(curve, 2.5, "iron-plate") == 50
    assert produced_at(curve, 7.5, "iron-plate") == 200
    assert produced_at(curve, 12, "iron-plate") is None
    assert produced_at(curve, 5, "copper-plate") == 0


def test_team_ratio_compares_at_equal_game_time(tmp_path):
    solo = write_run(tmp_path / "solo" / "a", [(25, 18000, {"iron-plate": 100}, [])], 36000, {"iron-plate": 300})
    team = write_run(tmp_path / "duo" / "b", [(25, 18000, {"iron-plate": 250}, [])], 36000, {"iron-plate": 450},
                     agents=("claude-opus-5-5", "claude-opus-5-5"))
    table = team_ratio(solo, team, items=("iron-plate",))
    assert "| 5 | 100 | 250 | 2.50 |" in table
    assert "| 10 | 300 | 450 | 1.50 |" in table


def test_compare_lists_rungs_and_runs(tmp_path):
    solo = write_run(tmp_path / "solo" / "a", [(25, 18000, {"iron-plate": 100}, ["item:iron-plate"])], 36000, {"iron-plate": 300})
    text = compare([solo])
    assert "| solo/a | claude-opus-5-5 | 30 | 0:10:00 | $1.00 | 1 of 24: Iron plate | max_turns |" in text
    assert "| Iron plate | 0:05:00 / 25 / $0.75 |" in text
