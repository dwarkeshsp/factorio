#!/usr/bin/env python3
"""Run a queue of benchmark runs one after another.

A queue file has one run per line: NAME then the arguments for `python -m factoriobench run`
(without --out). Lines can be appended while the queue is running. A run whose directory
already exists is skipped, so a queue can be restarted while its current run is still going.

Several queues can share one machine: each run reserves one slot per game client, and a run
waits until the machine has room (MAX_CLIENTS, about 2 GB of memory each).

  scripts/runq.py runs/night1 queues/a.txt
"""
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

MAX_CLIENTS = int(os.environ.get("MAX_CLIENTS", "5"))
root, queue = Path(sys.argv[1]), Path(sys.argv[2])
slots = root / ".slots"
slots.mkdir(parents=True, exist_ok=True)


def seats(args: list[str]) -> int:
    count = 0
    for flag, value in zip(args, args[1:]):
        if flag == "--model":
            count += len(value.split(","))
        elif flag == "--team":
            count += len(value.partition("=")[2].split(","))
    return count or 1


def in_use() -> int:
    total = 0
    for slot in slots.iterdir():
        if (root / slot.name / "summary.json").exists():
            slot.unlink(missing_ok=True)  # that run is over
        else:
            total += int(slot.read_text() or 0)
    return total


def next_run() -> tuple[str, list[str]] | None:
    for line in queue.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, *args = shlex.split(line)
        if not (root / name).exists():
            return name, args
    return None


while True:
    pending = next_run()
    if pending is None:
        if queue.with_suffix(".stop").exists():
            break
        time.sleep(20)
        continue
    name, args = pending
    need = seats(args)
    if in_use() + need > MAX_CLIENTS:
        time.sleep(15)
        continue
    (slots / name).write_text(str(need))
    (root / name).mkdir(parents=True, exist_ok=True)
    print(f"=== {time.strftime('%H:%M:%S')} starting {name}: {' '.join(args)}", flush=True)
    with (root / f"{name}.out").open("w") as log:
        code = subprocess.run([sys.executable, "-m", "factoriobench", "run", "--out", str(root / name), *args],
                              stdout=log, stderr=subprocess.STDOUT).returncode
    (slots / name).unlink(missing_ok=True)
    print(f"=== {time.strftime('%H:%M:%S')} finished {name} (exit {code})", flush=True)
