-- The benchmark scenario: the game's own freeplay, plus teams.
--
-- Everything a player experiences is freeplay as shipped. This file adds only what the
-- harness needs and a console command cannot do: putting each joining player on its team's
-- force at its team's spawn, and reading the game's own production price list.
local handler = require("event_handler")
handler.add_lib(require("__base__/script/freeplay/freeplay"))
handler.add_lib(require("silo-script"))
local production_score = require("production-score")

local function state()
  storage.bench = storage.bench or {member = {}, spawns = {}, colors = {}}
  return storage.bench
end

local function place(player)
  local s = state()
  local team = s.member[player.name]
  if not team then return end
  local force = game.forces[team]
  if not force then return end
  player.force = force
  if s.colors[team] then
    player.color = s.colors[team]
    player.chat_color = s.colors[team]
  end
  local surface = game.surfaces[1]
  local spawn = s.spawns[team]
  if spawn then
    local position = surface.find_non_colliding_position("character", spawn, 24, 0.5) or spawn
    player.teleport(position, surface)
  end
end

local bench = {}

bench.on_init = function() state() end

bench.events =
{
  [defines.events.on_player_created] = function(event)
    place(game.get_player(event.player_index))
  end
}

bench.add_remote_interface = function()
  remote.add_interface("bench",
  {
    -- config = {teams = {name = {player names}}, spawns = {name = {x, y}}, colors = {name = {r, g, b}},
    --           cease_fire = bool, peaceful = bool, always_day = bool, chart = tiles}
    configure = function(config)
      local s = state()
      local surface = game.surfaces[1]
      remote.call("freeplay", "set_skip_intro", true)
      remote.call("freeplay", "set_disable_crashsite", true)
      if config.peaceful ~= nil then surface.peaceful_mode = config.peaceful end
      if config.always_day ~= nil then surface.always_day = config.always_day end
      local names = {}
      for name, members in pairs(config.teams) do
        names[#names + 1] = name
        local force = game.forces[name] or game.create_force(name)
        for _, player_name in pairs(members) do s.member[player_name] = name end
        local spawn = config.spawns and config.spawns[name]
        if spawn then
          s.spawns[name] = {spawn[1], spawn[2]}
          force.set_spawn_position(s.spawns[name], surface)
        end
        if config.colors and config.colors[name] then
          local c = config.colors[name]
          s.colors[name] = {r = c[1], g = c[2], b = c[3]}
        end
        local r = config.chart or 200
        force.chart(surface, {{-r, -r}, {r, r}})
      end
      for _, a in pairs(names) do
        for _, b in pairs(names) do
          if a ~= b then
            game.forces[a].set_cease_fire(b, config.cease_fire and true or false)
            game.forces[a].set_friend(b, false)
          end
        end
      end
      return names
    end,

    -- The price list the game's PvP mode scores production with.
    prices = function()
      return production_score.generate_price_list()
    end
  })
end

handler.add_lib(bench)
