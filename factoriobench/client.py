"""The graphical game client an agent plays through, on its own virtual display."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

from . import paths

SCREEN = (1280, 720)

# Settings that differ from a fresh install, the same for every model. The graphics ones
# turn off decoration that costs render time on a CPU-only machine and carries no game
# information; everything a player needs to read the factory stays on.
CLIENT_CONFIG = {
    "other": {
        "check-updates": "false",
        "enable-crash-log-uploading": "false",
    },
    "graphics": {
        "full-screen": "false",
        "v-sync": "false",
        "show-clouds": "false",
        "show-fog": "false",
        "show-animated-water": "false",
        "show-tree-distortion": "false",
        "additional-terrain-effects": "false",
        "light-occlusion": "false",
        "high-quality-animations": "false",
        "show-game-simulations-in-background": "false",
    },
}


class Display:
    """An Xvfb screen with nothing on it but what we start."""

    def __init__(self, size: tuple[int, int] = SCREEN):
        self.size = size
        self.name = ""
        self.proc: subprocess.Popen | None = None

    def start(self, timeout: float = 20.0) -> str:
        read_fd, write_fd = os.pipe()
        self.proc = subprocess.Popen(
            [
                "Xvfb", "-displayfd", str(write_fd),
                "-screen", "0", f"{self.size[0]}x{self.size[1]}x24",
                "+extension", "GLX", "-nolisten", "tcp",
            ],
            pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        os.close(write_fd)
        deadline = time.time() + timeout
        data = b""
        os.set_blocking(read_fd, False)
        try:
            while not data.endswith(b"\n"):
                if self.proc.poll() is not None:
                    raise RuntimeError("Xvfb exited during startup; is it installed?")
                if time.time() > deadline:
                    raise RuntimeError("Xvfb did not report a display in time")
                try:
                    data += os.read(read_fd, 32)
                except BlockingIOError:
                    time.sleep(0.05)
        finally:
            os.close(read_fd)
        self.name = f":{int(data.strip())}"
        return self.name

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Client:
    def __init__(self, directory: Path, display: Display, player: str, edition: str = "full",
                 render_threads: int | None = None, gpu: bool = False):
        self.dir = Path(directory).resolve()
        self.display = display
        self.player = player
        self.edition = edition
        self.render_threads = render_threads
        self.gpu = gpu
        self.proc: subprocess.Popen | None = None

    def connect(self, port: int) -> None:
        paths.write_instance_config(self.dir, self.edition, CLIENT_CONFIG)
        # A server that does not verify accounts takes whatever name the client presents.
        (self.dir / "player-data.json").write_text(json.dumps({"service-username": self.player, "service-token": ""}))
        env = {**os.environ, "DISPLAY": self.display.name}
        if not self.gpu:
            env["LIBGL_ALWAYS_SOFTWARE"] = "1"
            if self.render_threads:
                env["LP_NUM_THREADS"] = str(self.render_threads)
        width, height = self.display.size
        stdout = (self.dir / "stdout.log").open("ab")
        self.proc = subprocess.Popen(
            [
                str(paths.binary(self.edition)), "-c", str(self.dir / "config.ini"),
                "--mp-connect", f"127.0.0.1:{port}",
                "--window-size", f"{width}x{height}",
                "--disable-audio",
            ],
            env=env, stdout=stdout, stderr=subprocess.STDOUT, start_new_session=True,
        )

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.alive():
            os.killpg(self.proc.pid, signal.SIGINT)
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
