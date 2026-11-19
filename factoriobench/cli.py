"""Every command: python -m factoriobench --help"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import install, report
from .llm import PRICES
from .run import SOLO_FORCE, RunConfig, run


def cmd_setup(args: argparse.Namespace) -> None:
    missing = install.missing_system_tools()
    if missing:
        print("Missing system packages. Install them with:\n  sudo apt-get update && sudo apt-get install -y " + " ".join(missing))
    editions = [name for name in ("full", "headless", "demo") if getattr(args, name)] or ["full"]
    for edition in editions:
        install.install(edition, force=args.force)


def cmd_run(args: argparse.Namespace) -> None:
    if args.team:
        teams = {}
        for spec in args.team:
            name, _, models = spec.partition("=")
            if not name or not models:
                raise SystemExit(f"--team wants NAME=MODEL[,MODEL...], got {spec!r}")
            teams[name] = models.split(",")
        if not 2 <= len(teams) <= 4:
            raise SystemExit("a versus run needs two to four --team options")
    else:
        teams = {SOLO_FORCE: args.model.split(",")}
    cfg = RunConfig(
        out=args.out, teams=teams, effort=args.effort, seed=args.seed, peaceful=not args.hostile,
        cease_fire=not args.war, minutes=args.minutes, max_turns=args.max_turns, max_usd=args.max_usd,
        compact_at_tokens=args.compact_at_tokens, keep_turns=args.keep_turns,
        render_threads=args.render_threads, gpu=args.gpu, ledger=args.ledger, budget_usd=args.budget,
        org=args.org, handbook=args.handbook, write_handbook=not args.no_handbook,
    )
    summary = run(cfg)
    print(json.dumps(summary, indent=2))
    if (Path(args.out) / "milestones.json").exists():
        print(report.render(Path(args.out)))


def cmd_report(args: argparse.Namespace) -> None:
    for run_dir in args.runs:
        print(report.render(Path(run_dir)))


def cmd_timelapse(args: argparse.Namespace) -> None:
    if args.screens:
        print(report.grid_timelapse(Path(args.run), fps=args.fps))
    elif args.overview:
        print(report.overview_timelapse(Path(args.run), fps=args.fps))
    else:
        print(report.timelapse(Path(args.run), agent=args.agent, fps=args.fps))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="factoriobench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="download the game (the full game needs FACTORIO_USERNAME and FACTORIO_TOKEN)")
    p.add_argument("--full", action="store_true", help="the full game (default)")
    p.add_argument("--headless", action="store_true", help="the free headless server")
    p.add_argument("--demo", action="store_true", help="the free demo (tutorial levels only)")
    p.add_argument("--force", action="store_true", help="download again even if installed")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("run", help="one agent, one team, or two teams play one freeplay map to a deadline")
    p.add_argument("--out", required=True, help="run directory, for example runs/opus55-seed1001")
    p.add_argument("--model", default="claude-opus-5-5",
                   help="model name, or a comma-separated list for a team (one agent each). Known: " + ", ".join(sorted(PRICES)))
    p.add_argument("--effort", default=None, help="low, medium, high, xhigh or max; default is the model's own default")
    p.add_argument("--seed", type=int, default=1001, help="map generation seed")
    p.add_argument("--hostile", action="store_true", help="enemies attack (default is peaceful mode)")
    p.add_argument("--team", action="append", default=[], metavar="NAME=MODEL[,MODEL...]",
                   help="give two to four times for a versus run, for example --team red=claude-opus-5-5 --team blue=gpt-6.2-astra")
    p.add_argument("--war", action="store_true", help="versus only: the teams can attack each other (default is a cease-fire)")
    p.add_argument("--minutes", type=float, default=20.0, help="the deadline, in game minutes")
    p.add_argument("--org", choices=["flat", "manager", "roles"], default="flat",
                   help="how a team is organised: no structure, the first agent leads, or roles assigned in advance")
    p.add_argument("--handbook", default=None, help="a file of notes left by an earlier team, shown to every agent")
    p.add_argument("--no-handbook", action="store_true", help="do not ask the agents for notes at the end")
    p.add_argument("--max-turns", type=int, default=2000, help="per agent")
    p.add_argument("--max-usd", type=float, default=25.0, help="for the whole run")
    p.add_argument("--compact-at-tokens", type=int, default=100_000, help="summarise older history past this context size")
    p.add_argument("--keep-turns", type=int, default=6, help="recent turns kept verbatim through a compaction")
    p.add_argument("--ledger", default="runs/ledger.jsonl", help="spend ledger shared by all runs")
    p.add_argument("--budget", type=float, default=500.0, help="stop when the ledger's total reaches this many dollars")
    p.add_argument("--render-threads", type=int, default=None, help="software-rendering threads for the game client")
    p.add_argument("--gpu", action="store_true", help="use the machine's GPU instead of software rendering")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("report", help="print the score of one or more runs")
    p.add_argument("runs", nargs="+")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("timelapse", help="make an mp4 from a run's end-of-turn screenshots")
    p.add_argument("run")
    p.add_argument("--agent", default="agent-1")
    p.add_argument("--fps", type=int, default=6)
    p.add_argument("--overview", action="store_true", help="the whole base from above instead of one agent's screen")
    p.add_argument("--screens", action="store_true", help="every agent's screen side by side, in step with the game clock")
    p.set_defaults(func=cmd_timelapse)

    args = parser.parse_args(argv)
    args.func(args)
