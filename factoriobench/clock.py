"""The shared game clock for one run.

The game runs only while this clock runs. Every input an agent sends and every second it
holds a key or waits goes through here, so pausing the game also suspends each agent
mid-action: held keys stay down, timers stop, and nothing is sent to a frozen game.
"""
from __future__ import annotations

import threading
import time


class Clock:
    def __init__(self) -> None:
        self._running = threading.Event()
        self.lock = threading.Lock()  # held while an input is being sent
        self.elapsed = 0.0            # seconds the game has run under this clock
        self._since: float | None = None

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def start(self) -> None:
        with self.lock:
            self._since = time.monotonic()
            self._running.set()

    def stop(self) -> None:
        """Returns once no input is in flight and none will be sent until start()."""
        with self.lock:
            if self._since is not None:
                self.elapsed += time.monotonic() - self._since
                self._since = None
            self._running.clear()

    def now(self) -> float:
        since = self._since
        return self.elapsed + (time.monotonic() - since if since is not None else 0.0)

    def send(self, action):
        """Run `action` (which sends one input) while the game is running."""
        while True:
            self._running.wait()
            with self.lock:
                if self._running.is_set():
                    return action()

    def sleep(self, seconds: float) -> None:
        """Let `seconds` of running game time pass."""
        target = self.now() + max(0.0, seconds)
        while True:
            self._running.wait()
            remaining = target - self.now()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.02))
