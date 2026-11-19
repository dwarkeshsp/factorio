"""The game server: holds the map, the clock and the score.

Agents join it as ordinary non-admin players, so the in-game console and the map editor
refuse them. The harness talks to it over RCON, which no agent can reach: an agent has a
screen, a mouse and a keyboard, and the only window on that screen is the game.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from . import paths
from .rcon import Rcon, RconError

TICKS_PER_SECOND = 60
SCENARIO_NAME = "factoriobench"
SCENARIO_SOURCE = Path(__file__).parent / "scenario" / "control.lua"

SERVER_SETTINGS = {
    "name": "factoriobench",
    "description": "",
    "tags": [],
    "max_players": 0,
    "visibility": {"public": False, "lan": False},
    "username": "",
    "password": "",
    "token": "",
    "game_password": "",
    "require_user_verification": False,
    "allow_commands": "admins-only",
    "autosave_interval": 10,
    "autosave_slots": 3,
    "afk_autokick_interval": 0,
    "auto_pause": True,
    "auto_pause_when_players_connect": False,
    "only_admins_can_pause_the_game": True,
    "autosave_only_on_server": True,
    "non_blocking_saving": False,
}

_CONSOLE_LINE = re.compile(r"^\S+ \S+ \[(?P<kind>[A-Z]+)\] (?P<rest>.*)$")
_DENIED = re.compile(r"^(?P<player>.+?) tried to run a command, which isn't allowed for them: (?P<text>.*)$")
_RAN = re.compile(r"^(?P<player>.+?) \(command\): (?P<text>.*)$")
_CHAT = re.compile(r"^(?P<player>[^:]+): (?P<text>.*)$")


def free_port(kind: int) -> int:
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def parse_console_log(text: str) -> dict[str, list[dict[str, str]]]:
    """Sort the server's console log into chat, refused commands and commands that ran.

    The harness's own commands arrive over RCON as silent commands and are not logged, so
    anything under "commands_run" was typed by a player.
    """
    out: dict[str, list[dict[str, str]]] = {"chat": [], "commands_denied": [], "commands_run": [], "sessions": []}
    for line in text.splitlines():
        match = _CONSOLE_LINE.match(line)
        if not match:
            continue
        kind, rest = match["kind"], match["rest"]
        if kind == "COMMAND":
            denied = _DENIED.match(rest)
            ran = _RAN.match(rest)
            if denied:
                out["commands_denied"].append({"player": denied["player"], "text": denied["text"]})
            elif ran:
                out["commands_run"].append({"player": ran["player"], "text": ran["text"]})
        elif kind == "CHAT":
            chat = _CHAT.match(rest)
            if chat:
                out["chat"].append({"player": chat["player"], "text": chat["text"]})
        elif kind in ("JOIN", "LEAVE"):
            out["sessions"].append({"event": kind.lower(), "text": rest})
    return out


class LuaError(RuntimeError):
    pass


class Server:
    def __init__(self, directory: Path, seed: int, peaceful: bool = True, edition: str = "full"):
        self.dir = Path(directory).resolve()
        self.seed = seed
        self.peaceful = peaceful
        self.edition = edition
        self.port = 0
        self.rcon_port = 0
        self.proc: subprocess.Popen | None = None
        self.rcon: Rcon | None = None
        self.save_path = self.dir / "saves" / "map.zip"
        self.console_log = self.dir / "console.log"

    # --- lifecycle ---------------------------------------------------------
    def _run_binary(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(paths.binary(self.edition)), "-c", str(self.dir / "config.ini"), *args],
            capture_output=True, text=True, check=False,
        )

    def prepare(self) -> None:
        """Write this server's config and install the benchmark scenario into its own directory."""
        paths.write_instance_config(self.dir, self.edition)
        (self.dir / "map-gen-settings.json").write_text(json.dumps({"peaceful_mode": self.peaceful}, indent=2))
        scenario = self.dir / "scenarios" / SCENARIO_NAME
        scenario.mkdir(parents=True, exist_ok=True)
        shutil.copy(SCENARIO_SOURCE, scenario / "control.lua")
        (self.dir / "saves").mkdir(exist_ok=True)

    def start(self, timeout: float = 180.0) -> None:
        self.prepare()
        (self.dir / "server-settings.json").write_text(json.dumps(SERVER_SETTINGS, indent=2))
        self.port = free_port(socket.SOCK_DGRAM)
        self.rcon_port = free_port(socket.SOCK_STREAM)
        password = secrets.token_hex(16)
        stdout = (self.dir / "stdout.log").open("ab")
        self.proc = subprocess.Popen(
            [
                str(paths.binary(self.edition)), "-c", str(self.dir / "config.ini"),
                "--start-server-load-scenario", SCENARIO_NAME,
                "--map-gen-seed", str(self.seed),
                "--map-gen-settings", str(self.dir / "map-gen-settings.json"),
                "--port", str(self.port),
                "--rcon-bind", f"127.0.0.1:{self.rcon_port}",
                "--rcon-password", password,
                "--server-settings", str(self.dir / "server-settings.json"),
                "--console-log", str(self.console_log),
            ],
            stdout=stdout, stderr=subprocess.STDOUT, start_new_session=True, preexec_fn=paths.die_with_parent,
        )
        deadline = time.time() + timeout
        while True:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited during startup; see {self.dir / 'stdout.log'}")
            try:
                self.rcon = Rcon("127.0.0.1", self.rcon_port, password)
                break
            except (OSError, RconError):
                if time.time() > deadline:
                    raise RuntimeError("server did not open its RCON port in time") from None
                time.sleep(0.5)
        # The first Lua command of a game only prints a warning that achievements will be
        # disabled; it has to be repeated before any Lua runs.
        self.rcon.command("/silent-command local _ = 0")
        self.rcon.command("/silent-command local _ = 0")

    def stop(self, timeout: float = 60.0) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                if self.rcon:
                    self.rcon.command("/server-save")
                    self.rcon.command("/quit")
            except (OSError, RconError):
                pass
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGINT)
                try:
                    self.proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(self.proc.pid, signal.SIGKILL)
        if self.rcon:
            self.rcon.close()
            self.rcon = None

    # --- Lua ---------------------------------------------------------------
    def eval(self, body: str) -> Any:
        """Run a Lua function body on the server and return what it returns, via JSON."""
        if self.rcon is None:
            raise RuntimeError("server is not running")
        code = " ".join(body.split())
        reply = self.rcon.command(
            "/silent-command local ok, res = pcall(function() " + code + " end) "
            "rcon.print(helpers.table_to_json({ok = ok, value = ok and res or nil, error = (not ok) and tostring(res) or nil}))"
        )
        try:
            parsed = json.loads(reply)
        except json.JSONDecodeError:
            raise LuaError(f"unexpected reply from the server: {reply[:500]!r}") from None
        if not parsed.get("ok"):
            raise LuaError(parsed.get("error", "unknown Lua error"))
        return parsed.get("value")

    # --- teams and prices ----------------------------------------------------
    def configure(self, teams: dict[str, list[str]], spawns: dict[str, tuple[float, float]] | None = None,
                  colors: dict[str, tuple[float, float, float]] | None = None, cease_fire: bool = True) -> None:
        """Create each team's force. Call before any player joins."""
        config = {"teams": teams, "spawns": spawns or {}, "colors": colors or {},
                  "cease_fire": cease_fire, "peaceful": self.peaceful}
        self.eval(f"return remote.call('bench', 'configure', helpers.json_to_table([==[{json.dumps(config)}]==]))")

    def prices(self) -> dict[str, float]:
        """The game's own production price list (core/lualib/production-score.lua)."""
        return self.eval("return remote.call('bench', 'prices')") or {}

    def speed(self, value: float) -> None:
        self.eval(f"game.speed = {float(value)}")

    # --- clock -------------------------------------------------------------
    def pause(self) -> int:
        """Stop the simulation. Nothing in the game responds while paused, menus included."""
        return int(self.eval("game.tick_paused = true return game.tick"))

    def resume(self) -> int:
        return int(self.eval("game.tick_paused = false return game.tick"))

    def tick(self) -> int:
        # game.ticks_played keeps counting while the tick is paused; game.tick does not.
        return int(self.eval("return game.tick"))

    def save(self) -> None:
        if self.rcon:
            self.rcon.command("/server-save")

    # --- players and integrity ----------------------------------------------
    def players(self) -> list[dict[str, Any]]:
        return self.eval(
            """
            local out = {}
            for _, p in pairs(game.players) do
              out[#out + 1] = {name = p.name, connected = p.connected, admin = p.admin, force = p.force.name,
                               cheat_mode = p.cheat_mode, controller = p.controller_type,
                               is_character = p.controller_type == defines.controllers.character}
            end
            return out
            """
        ) or []

    def integrity(self) -> dict[str, Any]:
        """What an auditor needs to trust a run: nobody was an admin, nobody ran a command."""
        log = parse_console_log(self.console_log.read_text(errors="replace")) if self.console_log.exists() else {}
        players = self.players()
        denied = log.get("commands_denied", [])
        ran = log.get("commands_run", [])
        return {
            "clean": not ran and not any(p["admin"] or p["cheat_mode"] for p in players),
            "players": players,
            "commands_run": ran,
            "commands_denied": denied,
        }
