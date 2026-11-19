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


def test_production_score_counts_what_was_made_and_not_used_up():
    from factoriobench.scoring import production_score
    prices = {"iron-ore": 3.0, "iron-plate": 6.0, "coal": 3.0, "wood": 3.2, "raw-fish": 100.0, "automation-science-pack": 27.0}
    force = {
        "items": {"iron-ore": 10, "iron-plate": 8, "coal": 4, "wood": 50, "raw-fish": 3, "automation-science-pack": 2},
        "items_used": {"iron-ore": 8, "coal": 4, "automation-science-pack": 2},
    }
    result = production_score(force, prices)
    # 2 ore left, 8 plates, coal all burnt, wood and fish unpriced, science spent on research still counts
    assert result["score"] == 2 * 3.0 + 8 * 6.0 + 2 * 27.0
    assert result["gross"] == 10 * 3.0 + 8 * 6.0 + 4 * 3.0 + 2 * 27.0


def test_production_score_of_an_empty_force_is_zero():
    from factoriobench.scoring import production_score
    assert production_score({"items": [], "items_used": {}}, {"iron-ore": 3.0}) == {"score": 0.0, "gross": 0.0}
