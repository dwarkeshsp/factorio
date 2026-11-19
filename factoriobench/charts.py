"""Charts and tables from finished or running runs.

  python -m factoriobench.charts lines out.png "Solo=runs/a" "Team of 2=runs/b" [--title T] [--per-agent]
  python -m factoriobench.charts versus out.png runs/match
  python -m factoriobench.charts table runs/night1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SURFACE, TEXT, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e0"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
TEAM_COLOR = {"red": "#e34948", "blue": "#2a78d6"}


def events(run_dir: Path) -> list[dict]:
    path = run_dir / "log.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:  # a line still being written
            pass
    return rows


def score_series(run_dir: Path) -> dict[str, list[tuple[float, float]]]:
    """team -> [(game minutes, production score)] at every pause."""
    out: dict[str, list[tuple[float, float]]] = {}
    for row in events(run_dir):
        if row.get("event") == "pause":
            for team, score in (row.get("scores") or {}).items():
                out.setdefault(team, [(0.0, 0.0)]).append((row["game_ticks"] / 3600, score))
    return out


def agents_of(run_dir: Path) -> list[dict]:
    config = run_dir / "config.json"
    return json.loads(config.read_text())["agents"] if config.exists() else []


def _axes(title: str, subtitle: str = "", ylabel: str = "Production score"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 5), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, length=0, labelsize=10)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=10)
    fig.suptitle(title, x=0.07, y=0.97, ha="left", fontsize=14, fontweight="bold", color=TEXT)
    if subtitle:
        fig.text(0.07, 0.892, subtitle, ha="left", fontsize=10, color=MUTED)
    return fig, ax


def _finish(fig, ax, out: Path, xlabel: str = "Game time (minutes)") -> Path:
    ax.set_xlabel(xlabel, color=MUTED, fontsize=10)
    ax.set_ylim(bottom=0)
    ax.set_xlim(left=0)
    ax.yaxis.set_major_formatter(lambda value, _: f"{value:,.0f}")
    legend = ax.legend(frameon=False, fontsize=10, loc="upper left", labelcolor=TEXT)
    for line in legend.get_lines():
        line.set_linewidth(2.5)
    fig.subplots_adjust(left=0.09, right=0.86, top=0.84, bottom=0.11)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE)
    return out


def _end_labels(ax, ends: list[tuple[float, float, str]]) -> None:
    """Value labels at the line ends, nudged apart when they would overlap."""
    if not ends:
        return
    top = max(y for _, y, _ in ends) or 1.0
    gap = top * 0.045
    placed: list[float] = []
    for x, y, text in sorted(ends, key=lambda e: e[1]):
        at = y
        if placed and at - placed[-1] < gap:
            at = placed[-1] + gap
        placed.append(at)
        ax.annotate(text, (x, y), xytext=(x, at), textcoords="data", xycoords="data", fontsize=9.5, color=TEXT,
                    va="center", ha="left", annotation_clip=False,
                    bbox={"boxstyle": "square,pad=0.1", "fc": SURFACE, "ec": "none"},
                    arrowprops=None).set_position((x + ax.get_xlim()[1] * 0.012, at))


def lines(out: Path, runs: list[tuple[str, Path]], title: str, subtitle: str = "", per_agent: bool = False) -> Path:
    fig, ax = _axes(title, subtitle, "Production score per agent" if per_agent else "Production score")
    ends = []
    xmax = 0.0
    for index, (label, run_dir) in enumerate(runs):
        series = score_series(run_dir)
        if not series:
            continue
        points = next(iter(series.values()))
        divide = max(1, len(agents_of(run_dir))) if per_agent else 1
        xs, ys = [p[0] for p in points], [p[1] / divide for p in points]
        ax.plot(xs, ys, color=SERIES[index % len(SERIES)], linewidth=2, solid_capstyle="round", solid_joinstyle="round", label=label)
        ends.append((xs[-1], ys[-1], f"{ys[-1]:,.0f}"))
        xmax = max(xmax, xs[-1])
    ax.set_xlim(0, xmax * 1.0 or 1)
    _end_labels(ax, ends)
    return _finish(fig, ax, out)


def versus(out: Path, run_dir: Path, title: str | None = None) -> Path:
    series = score_series(run_dir)
    by_team: dict[str, list[str]] = {}
    for agent in agents_of(run_dir):
        by_team.setdefault(agent["team"], []).append(agent["model"])
    names = {team: f"{team}: {' + '.join(models)}" for team, models in by_team.items()}
    fig, ax = _axes(title or "Two teams, one map", "Production score of each team over the match")
    ends = []
    for index, (team, points) in enumerate(series.items()):
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        ax.plot(xs, ys, color=TEAM_COLOR.get(team, SERIES[index]), linewidth=2, solid_capstyle="round",
                solid_joinstyle="round", label=names.get(team, team))
        ends.append((xs[-1], ys[-1], f"{ys[-1]:,.0f}"))
    ax.set_xlim(0, max((e[0] for e in ends), default=1))
    _end_labels(ax, ends)
    return _finish(fig, ax, out)


def bars(out: Path, rows: list[tuple[str, float]], title: str, subtitle: str = "", xlabel: str = "Production score") -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows = sorted(rows, key=lambda r: r[1])
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(rows) + 1.6), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.barh([r[0] for r in rows], [r[1] for r in rows], height=0.5, color=SERIES[0])
    top = max((r[1] for r in rows), default=1) or 1
    for label, value in rows:
        ax.text(value + top * 0.012, label, f"{value:,.0f}", va="center", ha="left", fontsize=10, color=TEXT)
    ax.set_xlim(0, top * 1.12)
    ax.tick_params(colors=TEXT, length=0, labelsize=10.5)
    ax.xaxis.set_visible(False)
    fig.suptitle(title, x=0.02, y=0.98, ha="left", fontsize=14, fontweight="bold", color=TEXT)
    if subtitle:
        fig.text(0.02, 1 - 0.62 / fig.get_figheight(), subtitle, ha="left", fontsize=10, color=MUTED)
    fig.subplots_adjust(left=0.26, right=0.97, top=1 - 0.85 / fig.get_figheight(), bottom=0.05)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE)
    return out


def table(root: Path) -> str:
    """A markdown table of every finished run under `root`."""
    lines_ = ["| Run | Mode | Team | Models | Score | Turns | Cost | Game time | Furthest milestone |", "|---|---|---|---|---|---|---|---|---|"]
    for summary_path in sorted(root.glob("*/summary.json")):
        summary = json.loads(summary_path.read_text())
        for team, result in summary["teams"].items():
            models = ", ".join(result["models"])
            won = " (won)" if summary.get("winner") == team else ""
            lines_.append(
                f"| {summary_path.parent.name} | {summary['mode']} | {team}{won} | {models} | {result['score']:,.0f} | "
                f"{result['turns']} | ${result['usd']:.2f} | {summary['game_time']} | {result['furthest_label'] or '-'} |")
    return "\n".join(lines_)


def main(argv: list[str]) -> None:
    kind = argv[0]
    if kind == "table":
        print(table(Path(argv[1])))
        return
    out = Path(argv[1])
    rest = argv[2:]
    title, per_agent = "Production score over time", False
    if "--title" in rest:
        title = rest[rest.index("--title") + 1]
        del rest[rest.index("--title"):rest.index("--title") + 2]
    if "--per-agent" in rest:
        per_agent = True
        rest.remove("--per-agent")
    if kind == "lines":
        runs = [(spec.partition("=")[0], Path(spec.partition("=")[2])) for spec in rest]
        print(lines(out, runs, title, per_agent=per_agent))
    elif kind == "versus":
        print(versus(out, Path(rest[0]), None if title == "Production score over time" else title))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
