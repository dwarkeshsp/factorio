"""Clocks for the code that presses keys and waits.

With one agent, or with rounds, an action's durations are plain wall time: the game runs for the whole
batch. With several agents acting on their own schedules the game is paused whenever any of them is
thinking, so the others' batches have to freeze too: a key held for five seconds must be held for five
seconds of running game, however many pauses fall inside it. `GameClock` gives executors that.
"""
from __future__ import annotations

import threading
import time
from typing import Callable


class WallClock:
    """Real time. Used when the game runs without interruption for the whole batch."""

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def checkpoint(self) -> None:
        pass


class GameClock:
    """Time that passes only while the game is running.

    Executors (one thread per acting agent) call `enter` before a batch and `exit` after it, `sleep`
    for every duration, and `checkpoint` before every input they send. `pause` stops the clock, waits
    until every executor is parked at a sleep or a checkpoint, and only then pauses the game, so no
    input is ever sent to a paused game (where it would be lost).
    """

    def __init__(self, pause_game: Callable[[], int], resume_game: Callable[[], int], settle: float = 0.15):
        self._pause_game = pause_game
        self._resume_game = resume_game
        self._settle = settle  # after unpausing the client needs a few ticks before it accepts input
        self._cond = threading.Condition()
        self.running = False
        self._input_ok_at = 0.0
        self._active = 0
        self._parked = 0

    # --- for executors -----------------------------------------------------
    def enter(self) -> None:
        with self._cond:
            self._active += 1

    def exit(self) -> None:
        with self._cond:
            self._active -= 1
            self._cond.notify_all()

    def _park(self) -> None:
        """Wait, holding the lock, until the game runs again."""
        self._parked += 1
        self._cond.notify_all()
        try:
            while not self.running:
                self._cond.wait()
        finally:
            self._parked -= 1

    def checkpoint(self) -> None:
        """Block until input may be sent: the game is running and has been for the settle time."""
        with self._cond:
            while True:
                if not self.running:
                    self._park()
                wait = self._input_ok_at - time.monotonic()
                if wait <= 0:
                    return
                self._cond.wait(timeout=wait)

    def sleep(self, seconds: float) -> None:
        remaining = seconds
        with self._cond:
            while True:
                if not self.running:
                    self._park()
                if remaining <= 0.0005:
                    return
                started = time.monotonic()
                self._cond.wait(timeout=remaining)  # woken early when the clock stops
                remaining -= time.monotonic() - started

    # --- for the scheduler -------------------------------------------------
    def pause(self, timeout: float = 5.0) -> int:
        """Stop the clock, wait for every executor to park, then pause the game. Returns the game tick."""
        deadline = time.monotonic() + timeout
        with self._cond:
            self.running = False
            self._cond.notify_all()
            while self._parked < self._active and time.monotonic() < deadline:
                self._cond.wait(timeout=0.05)
        return self._pause_game()

    def resume(self) -> int:
        """Unpause. Time counts at once (a held key works from the first tick); new input waits for the settle."""
        tick = self._resume_game()
        with self._cond:
            self._input_ok_at = time.monotonic() + self._settle
            self.running = True
            self._cond.notify_all()
        return tick
