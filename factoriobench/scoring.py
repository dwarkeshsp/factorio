"""Scoring from the game's own statistics, read over RCON.

Every first is recorded: the first time each item or fluid is produced, each kind of building
is placed and each technology is researched, with the game tick it was first seen at. A run
counts as complete only when the game's own launch counter rises.
"""
from __future__ import annotations

from typing import Any

TICKS_PER_SECOND = 60

# One Lua call returns everything the score is made of.
SNAPSHOT_TEMPLATE = """
local force = game.forces["%s"]
local surface = game.surfaces[1]
local researched = {}
for name, tech in pairs(force.technologies) do
  if tech.researched then researched[#researched + 1] = name end
end
local connected = {}
for _, p in pairs(game.connected_players) do connected[#connected + 1] = p.name end
return {
  tick = game.tick,
  items = force.get_item_production_statistics(surface).input_counts,
  fluids = force.get_fluid_production_statistics(surface).input_counts,
  built = force.get_entity_build_count_statistics(surface).input_counts,
  researched = researched,
  researching = force.current_research and force.current_research.name or nil,
  rockets_launched = force.rockets_launched,
  finished = game.finished or game.finished_but_continuing,
  connected = connected,
}
"""

def snapshot_lua(force: str = "player") -> str:
    return SNAPSHOT_TEMPLATE % force


SNAPSHOT_LUA = snapshot_lua()

# The headline ladder, in the order a factory normally reaches them. "Furthest milestone" is
# the highest rung reached, so a run that stalls still gets a comparable score.
LADDER = [
    ("item:iron-plate", "Iron plate"),
    ("item:copper-plate", "Copper plate"),
    ("item:iron-gear-wheel", "Iron gear wheel"),
    ("built:burner-mining-drill", "Mining drill placed"),
    ("item:electronic-circuit", "Electronic circuit"),
    ("built:steam-engine", "Steam engine placed"),
    ("built:lab", "Lab placed"),
    ("item:automation-science-pack", "Automation science pack"),
    ("tech:any", "First technology researched"),
    ("built:assembling-machine-1", "Assembling machine placed"),
    ("item:logistic-science-pack", "Logistic science pack"),
    ("item:steel-plate", "Steel plate"),
    ("fluid:petroleum-gas", "Petroleum gas"),
    ("item:plastic-bar", "Plastic bar"),
    ("item:advanced-circuit", "Advanced circuit"),
    ("item:chemical-science-pack", "Chemical science pack"),
    ("item:processing-unit", "Processing unit"),
    ("item:production-science-pack", "Production science pack"),
    ("item:utility-science-pack", "Utility science pack"),
    ("item:low-density-structure", "Low density structure"),
    ("item:rocket-fuel", "Rocket fuel"),
    ("built:rocket-silo", "Rocket silo placed"),
    ("item:rocket-part", "Rocket part"),
    ("rocket", "Rocket launched"),
]

# Checked against the running game at the start of a run, so a renamed prototype in a new
# game version fails loudly instead of leaving a rung unreachable.
LADDER_CHECK_LUA = """
local missing = {}
local function check(kind, name, exists) if not exists then missing[#missing + 1] = kind .. ":" .. name end end
%s
return missing
"""


def ladder_check_lua() -> str:
    lines = []
    for key, _ in LADDER:
        kind, _, name = key.partition(":")
        if kind == "item":
            lines.append(f'check("item", "{name}", prototypes.item["{name}"] ~= nil)')
        elif kind == "fluid":
            lines.append(f'check("fluid", "{name}", prototypes.fluid["{name}"] ~= nil)')
        elif kind == "built":
            lines.append(f'check("built", "{name}", prototypes.entity["{name}"] ~= nil)')
    return LADDER_CHECK_LUA % "\n".join(lines)


def _counts(value: Any) -> dict[str, float]:
    # An empty Lua table serialises as {} or [], depending on the game version.
    return value if isinstance(value, dict) else {}


def game_clock(ticks: int) -> str:
    total = max(0, int(ticks)) // TICKS_PER_SECOND
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


class Scorer:
    def __init__(self, start_tick: int = 0, firsts: dict[str, int] | None = None):
        self.start_tick = start_tick
        self.firsts: dict[str, int] = dict(firsts or {})
        self.last: dict[str, Any] = {}

    def update(self, snapshot: dict[str, Any]) -> list[str]:
        """Take a snapshot; return the keys reached for the first time, in a stable order."""
        self.last = snapshot
        tick = int(snapshot["tick"]) - self.start_tick
        seen: list[str] = []
        for name, count in sorted(_counts(snapshot.get("items")).items()):
            if count > 0:
                seen.append(f"item:{name}")
        for name, count in sorted(_counts(snapshot.get("fluids")).items()):
            if count > 0:
                seen.append(f"fluid:{name}")
        for name, count in sorted(_counts(snapshot.get("built")).items()):
            if count > 0:
                seen.append(f"built:{name}")
        researched = sorted(snapshot.get("researched") or [])
        if researched:
            seen.append("tech:any")
        seen.extend(f"tech:{name}" for name in researched)
        if (snapshot.get("rockets_launched") or 0) > 0:
            seen.append("rocket")
        new = [key for key in seen if key not in self.firsts]
        for key in new:
            self.firsts[key] = tick
        return new

    @property
    def launched(self) -> bool:
        return "rocket" in self.firsts

    def furthest(self) -> tuple[int, str]:
        """(rung number counted from 1, label) of the highest ladder rung reached; (0, "") if none."""
        best = (0, "")
        for index, (key, label) in enumerate(LADDER, start=1):
            if key in self.firsts:
                best = (index, label)
        return best

    def ladder(self) -> list[dict[str, Any]]:
        return [
            {"rung": index, "key": key, "label": label, "tick": self.firsts.get(key),
             "game_time": game_clock(self.firsts[key]) if key in self.firsts else None}
            for index, (key, label) in enumerate(LADDER, start=1)
        ]

    def report(self) -> dict[str, Any]:
        rung, label = self.furthest()
        return {
            "rocket_launched": self.launched,
            "furthest_rung": rung,
            "furthest_label": label,
            "rungs_total": len(LADDER),
            "ladder": self.ladder(),
            "technologies_researched": sum(1 for key in self.firsts if key.startswith("tech:") and key != "tech:any"),
            "firsts": dict(sorted(self.firsts.items(), key=lambda item: (item[1], item[0]))),
        }
