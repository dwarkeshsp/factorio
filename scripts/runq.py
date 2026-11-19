#!/usr/bin/env python3
"""Run a queue of benchmark runs one after another.

A queue file has one run per line: NAME then the arguments for `python -m factoriobench run`
(without --out). Lines can be appended while the queue is running. A run whose directory
already has a summary.json is skipped, so a queue can be restarted.

  scripts/runq.py runs/night1 queues/a.txt
"""
import shlex
import subprocess
import sys
import time
from pathlib import Path

root, queue = Path(sys.argv[1]), Path(sys.argv[2])
root.mkdir(parents=True, exist_ok=True)
done: set[str] = set()
while True:
    pending = None
    for line in queue.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, *args = shlex.split(line)
        if name in done or (root / name / "summary.json").exists():
            continue
        pending = (name, args)
        break
    if pending is None:
        if (queue.with_suffix(".stop")).exists():
            break
        time.sleep(20)
        continue
    name, args = pending
    done.add(name)
    out = root / name
    print(f"=== {time.strftime('%H:%M:%S')} starting {name}: {' '.join(args)}", flush=True)
    with (root / f"{name}.out").open("w") as log:
        code = subprocess.run([sys.executable, "-m", "factoriobench", "run", "--out", str(out), *args],
                              stdout=log, stderr=subprocess.STDOUT).returncode
    print(f"=== {time.strftime('%H:%M:%S')} finished {name} (exit {code})", flush=True)
