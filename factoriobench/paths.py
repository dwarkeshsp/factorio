"""Where the game installs live. Nothing here is inside the repository."""
from __future__ import annotations

import ctypes
import os
import signal
from pathlib import Path

EDITIONS = ("full", "demo", "headless")


def home() -> Path:
    return Path(os.environ.get("FACTORIO_BENCH_HOME", "~/.factorio-bench")).expanduser()


def install_dir(edition: str) -> Path:
    if edition not in EDITIONS:
        raise ValueError(f"unknown edition {edition!r}; expected one of {EDITIONS}")
    return home() / edition


def binary(edition: str) -> Path:
    path = install_dir(edition) / "bin" / "x64" / "factorio"
    if not path.exists():
        raise FileNotFoundError(
            f"Factorio ({edition}) is not installed at {path}. Run: python -m factoriobench setup --{edition}"
        )
    return path


def write_instance_config(instance_dir: Path, edition: str, sections: dict[str, dict[str, str]] | None = None) -> Path:
    """Give one game process its own write directory, so several can run from one install."""
    instance_dir.mkdir(parents=True, exist_ok=True)
    lines = ["[path]", f"read-data={install_dir(edition) / 'data'}", f"write-data={instance_dir.resolve()}", ""]
    for section, values in (sections or {}).items():
        lines.append(f"[{section}]")
        lines.extend(f"{key}={value}" for key, value in values.items())
        lines.append("")
    path = instance_dir / "config.ini"
    path.write_text("\n".join(lines))
    return path


def die_with_parent() -> None:
    """For Popen(preexec_fn=...): the child is killed if the harness dies, so a crash leaves no game running."""
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
