from factoriobench.scoring import LADDER, Scorer, game_clock, ladder_check_lua


def snapshot(tick, items=None, fluids=None, built=None, researched=None, rockets=0):
    return {"tick": tick, "items": items or {}, "fluids": fluids or {}, "built": built or {},
            "researched": researched or [], "rockets_launched": rockets}


def test_firsts_are_recorded_once_at_game_time_since_the_start():
    scorer = Scorer(start_tick=1000)
    assert scorer.update(snapshot(1600, items={"iron-ore": 3})) == ["item:iron-ore"]
    assert scorer.update(snapshot(2200, items={"iron-ore": 9, "iron-plate": 1})) == ["item:iron-plate"]
    assert scorer.update(snapshot(2800, items={"iron-ore": 9, "iron-plate": 4})) == []
    assert scorer.firsts == {"item:iron-ore": 600, "item:iron-plate": 1200}


def test_empty_lua_tables_arrive_as_lists_or_dicts():
    scorer = Scorer()
    assert scorer.update({"tick": 5, "items": [], "fluids": {}, "built": [], "researched": {}, "rockets_launched": 0}) == []


def test_furthest_rung_is_the_highest_reached_not_the_count():
    scorer = Scorer()
    scorer.update(snapshot(60, items={"iron-plate": 1, "steel-plate": 1}))
    rung, label = scorer.furthest()
    assert label == "Steel plate"
    assert rung == [key for key, _ in LADDER].index("item:steel-plate") + 1
    assert not scorer.launched


def test_research_and_launch():
    scorer = Scorer()
    new = scorer.update(snapshot(120, researched=["automation"], rockets=1))
    assert new == ["tech:any", "tech:automation", "rocket"]
    assert scorer.launched
    report = scorer.report()
    assert report["rocket_launched"] and report["furthest_label"] == "Rocket launched"
    assert report["technologies_researched"] == 1
    assert report["furthest_rung"] == report["rungs_total"] == len(LADDER)


def test_game_clock():
    assert game_clock(0) == "0:00:00"
    assert game_clock(60 * 75) == "0:01:15"
    assert game_clock(60 * 3600 * 13 + 60 * 1800) == "13:30:00"


def test_ladder_check_names_every_prototype_rung():
    lua = ladder_check_lua()
    assert 'prototypes.item["rocket-part"]' in lua
    assert 'prototypes.fluid["petroleum-gas"]' in lua
    assert 'prototypes.entity["rocket-silo"]' in lua
