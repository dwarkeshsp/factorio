"""A spend ledger shared by every run, so an overall budget holds across runs and processes."""
from __future__ import annotations

import json
import time
from pathlib import Path


class Ledger:
    def __init__(self, path: Path, run: str):
        self.path = path
        self.run = run
        self.recorded = 0.0

    def total(self) -> float:
        if not self.path.exists():
            return 0.0
        total = 0.0
        for line in self.path.read_text().splitlines():
            if line.strip():
                total += float(json.loads(line)["usd"])
        return total

    def total_with(self, spent: float) -> float:
        """All spend on the ledger plus this run's spend not yet written to it."""
        return self.total() + (spent - self.recorded)

    def record(self, spent: float) -> None:
        delta = spent - self.recorded
        if delta <= 0:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as handle:
            handle.write(json.dumps({"run": self.run, "usd": round(delta, 6), "t": round(time.time())}) + "\n")
        self.recorded = spent
