import threading
import time

from factoriobench.clock import GameClock, WallClock


def make():
    events = []
    clock = GameClock(lambda: events.append("pause") or 100, lambda: events.append("resume") or 50, settle=0.05)
    return clock, events


def test_wall_clock_is_plain_time():
    start = time.monotonic()
    WallClock().sleep(0.05)
    WallClock().checkpoint()
    assert time.monotonic() - start >= 0.05


def test_sleep_counts_only_running_time():
    clock, _ = make()
    finished = []

    def worker():
        clock.enter()
        clock.sleep(0.3)
        finished.append(time.monotonic())
        clock.exit()

    start = time.monotonic()
    clock.resume()
    thread = threading.Thread(target=worker)
    thread.start()
    time.sleep(0.1)
    assert clock.pause() == 100          # the worker is parked mid-sleep
    time.sleep(0.4)                      # a long think; no game time passes
    assert not finished
    clock.resume()
    thread.join(timeout=2)
    elapsed = finished[0] - start
    assert 0.65 <= elapsed <= 0.95       # 0.3 s of running time plus the 0.4 s pause


def test_pause_waits_for_executors_to_park_and_input_waits_for_the_settle():
    clock, events = make()
    sent = []

    def worker():
        clock.enter()
        clock.checkpoint()               # parks: the game is not running yet
        sent.append(time.monotonic())
        clock.exit()

    thread = threading.Thread(target=worker)
    thread.start()
    time.sleep(0.05)
    assert not sent
    resumed = time.monotonic()
    clock.resume()
    thread.join(timeout=2)
    assert sent and sent[0] - resumed >= 0.045   # no input in the first moments after unpausing
    clock.pause()
    assert events == ["resume", "pause"]


def test_an_executor_that_never_runs_does_not_block_a_pause():
    clock, _ = make()
    clock.resume()
    started = time.monotonic()
    assert clock.pause(timeout=1.0) == 100
    assert time.monotonic() - started < 0.5
