import threading
import time

from factoriobench.clock import Clock


def test_sleep_counts_only_running_time():
    clock = Clock()
    done = threading.Event()

    def sleeper():
        clock.sleep(0.2)
        done.set()

    threading.Thread(target=sleeper, daemon=True).start()
    time.sleep(0.15)
    assert not done.is_set()  # the clock has not started, so no game time has passed
    clock.start()
    time.sleep(0.1)
    clock.stop()
    time.sleep(0.2)
    assert not done.is_set()  # paused half way through
    clock.start()
    assert done.wait(1.0)
    clock.stop()
    assert 0.2 <= clock.elapsed < 0.6


def test_send_waits_for_the_game_to_run():
    clock = Clock()
    sent = []
    thread = threading.Thread(target=lambda: clock.send(lambda: sent.append(clock.running)), daemon=True)
    thread.start()
    time.sleep(0.1)
    assert sent == []
    clock.start()
    thread.join(1.0)
    assert sent == [True]
