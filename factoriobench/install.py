"""Download and unpack the game. Credentials come from the environment, never from a file here."""
from __future__ import annotations

import os
import shutil
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import paths

BASE = "https://factorio.com/get-download/stable"
URLS = {"full": f"{BASE}/alpha/linux64", "demo": f"{BASE}/demo/linux64", "headless": f"{BASE}/headless/linux64"}
SYSTEM_TOOLS = {"Xvfb": "xvfb", "xdotool": "xdotool", "ffmpeg": "ffmpeg"}


def missing_system_tools() -> list[str]:
    return [package for tool, package in SYSTEM_TOOLS.items() if shutil.which(tool) is None]


def download_url(edition: str) -> str:
    url = URLS[edition]
    if edition != "full":
        return url
    username, token = os.environ.get("FACTORIO_USERNAME"), os.environ.get("FACTORIO_TOKEN")
    if not username or not token:
        raise SystemExit(
            "The full game needs a factorio.com account that owns it. Set FACTORIO_USERNAME and FACTORIO_TOKEN "
            "(the token is on https://factorio.com/profile)."
        )
    return url + "?" + urllib.parse.urlencode({"username": username, "token": token})


def install(edition: str, force: bool = False) -> Path:
    target = paths.install_dir(edition)
    if (target / "bin" / "x64" / "factorio").exists() and not force:
        print(f"{edition}: already installed at {target}")
        return target
    archive = paths.home() / "dl" / f"{edition}.tar.xz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    print(f"{edition}: downloading")
    try:
        with urllib.request.urlopen(download_url(edition)) as response, archive.open("wb") as out:
            if "html" in response.headers.get("content-type", ""):
                raise SystemExit(f"{edition}: factorio.com returned a web page, not the game; check the credentials")
            shutil.copyfileobj(response, out, length=1 << 20)
    except urllib.error.HTTPError as err:
        # The URL carries the token, so report the status without it.
        raise SystemExit(f"{edition}: download failed with HTTP {err.code}; check FACTORIO_USERNAME and FACTORIO_TOKEN") from None
    print(f"{edition}: unpacking to {target}")
    if target.exists():
        shutil.rmtree(target)
    staging = target.with_name(target.name + ".unpack")
    if staging.exists():
        shutil.rmtree(staging)
    with tarfile.open(archive) as tar:
        tar.extractall(staging, filter="data")
    (staging / "factorio").rename(target)
    staging.rmdir()
    archive.unlink()
    return target
