"""
Plotting for the backtest results. Pure presentation -- no finance logic here.

Every function takes already-computed results and returns a matplotlib Figure.
If a plot needs a number that isn't in the input frame, that number belongs in
metrics.py or backtest.py, not here.

Expected inputs (produced by src/backtest.py):

    equity : DataFrame indexed by date, one column per configuration
             ("unhedged", "hedged_daily", "hedged_weekly"), values = portfolio
             value in dollars.

    path   : DataFrame indexed by date for a single configuration, with at
             least the columns
                 portfolio_delta   net delta of shares + options
                 rebalanced        bool, True on days a trade was made
                 cum_hedge_cost    cumulative dollars spent on protection
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.use("Agg")  # file output only; no interactive backend needed

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# One colour per configuration, used consistently across every figure.
COLORS = {
    "unhedged": "#8c8c8c",
    "hedged_daily": "#1f77b4",
    "hedged_weekly": "#d62728",
}
LABELS = {
    "unhedged": "Unhedged (100 sh AAPL)",
    "hedged_daily": "Full hedge, daily rebalance",
    "hedged_weekly": "Full hedge, weekly rebalance",
}


def _style(ax, title: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=12, loc="left")
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)


def save(fig: plt.Figure, name: str, *, dpi: int = 150) -> Path:
    """Write `fig` to results/<name>.png and return the path."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}.png"
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_equity_curves(
    equity: pd.DataFrame,
    *,
    normalize: bool = False,
    shade: dict[str, tuple[str, str]] | None = None,
    title: str = "Portfolio value: hedged vs unhedged",
) -> plt.Figure:
    """Equity curves for every configuration on one axis.

    normalize -- rebase every series to 100 at the first date, which makes the
                 shapes comparable when the configs start at different capital.
    shade     -- optional {label: (start_date, end_date)} regions to shade,
                 e.g. {"2022 drawdown": ("2022-01-03", "2023-01-06")}.
    """
    data = equity / equity.iloc[0] * 100 if normalize else equity

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for col in data.columns:
        ax.plot(
            data.index,
            data[col],
            label=LABELS.get(col, col),
            color=COLORS.get(col),
            linewidth=1.4,
        )

    for label, (lo, hi) in (shade or {}).items():
        ax.axvspan(pd.Timestamp(lo), pd.Timestamp(hi), color="#000000", alpha=0.05)
        ax.text(
            pd.Timestamp(lo), ax.get_ylim()[1], f" {label}",
            va="top", ha="left", fontsize=9, color="#555555",
        )

    _style(ax, title, "Index (start = 100)" if normalize else "Portfolio value ($)")
    ax.legend(frameon=False, fontsize=9)
    fig.autofmt_xdate()
    return fig


def plot_drawdown(equity: pd.DataFrame, title: str = "Drawdown from running peak") -> plt.Figure:
    """Drawdown of each configuration, as a negative percentage."""
    dd = equity / equity.cummax() - 1.0

    fig, ax = plt.subplots(figsize=(11, 4))
    for col in dd.columns:
        ax.plot(dd.index, dd[col] * 100, label=LABELS.get(col, col),
                color=COLORS.get(col), linewidth=1.2)
    ax.axhline(0, color="black", linewidth=0.8)
    _style(ax, title, "Drawdown (%)")
    ax.legend(frameon=False, fontsize=9)
    fig.autofmt_xdate()
    return fig


def plot_delta_path(
    path: pd.DataFrame,
    *,
    target_delta: float = 0.0,
    band: tuple[float, float] | None = None,
    delta_col: str = "portfolio_delta",
    rebalance_col: str = "rebalanced",
    title: str = "Portfolio delta and rebalance events",
) -> plt.Figure:
    """Net portfolio delta over time, with rebalance days marked.

    band -- optional (lower, upper) no-trade band drawn around the target, so
            the plot shows *why* each rebalance fired.
    """
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(path.index, path[delta_col], color="#1f77b4", linewidth=1.2,
            label="Portfolio delta")
    ax.axhline(target_delta, color="black", linewidth=0.9, linestyle="--",
               label=f"Target ({target_delta:g})")

    if band is not None:
        ax.axhspan(band[0], band[1], color="#1f77b4", alpha=0.08, label="No-trade band")

    if rebalance_col in path.columns:
        hits = path[path[rebalance_col].astype(bool)]
        ax.scatter(hits.index, hits[delta_col], s=14, color="#d62728", zorder=3,
                   label=f"Rebalance ({len(hits)})")

    _style(ax, title, "Delta (shares equivalent)")
    ax.legend(frameon=False, fontsize=9, ncol=2)
    fig.autofmt_xdate()
    return fig


def plot_hedge_cost(
    paths: dict[str, pd.DataFrame],
    *,
    cost_col: str = "cum_hedge_cost",
    title: str = "Cumulative cost of protection",
) -> plt.Figure:
    """Cumulative dollars spent on the hedge, one line per configuration."""
    fig, ax = plt.subplots(figsize=(11, 4))
    for name, path in paths.items():
        ax.plot(path.index, path[cost_col], label=LABELS.get(name, name),
                color=COLORS.get(name), linewidth=1.3)
    _style(ax, title, "Cumulative cost ($)")
    ax.legend(frameon=False, fontsize=9)
    fig.autofmt_xdate()
    return fig


def plot_inputs(panel: pd.DataFrame, title: str = "Backtest inputs") -> plt.Figure:
    """Sanity-check figure for the raw inputs: price, implied vol, risk-free rate.

    Look at this before trusting any result -- a flat line or a step change in
    `sigma` usually means a data problem, not a market event.
    """
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)

    axes[0].plot(panel.index, panel["close"], color="#333333", linewidth=1.2)
    _style(axes[0], "AAPL close", "$")

    axes[1].plot(panel.index, panel["sigma"] * 100, color="#d62728", linewidth=1.2)
    _style(axes[1], "VXAPL implied volatility", "%")

    axes[2].plot(panel.index, panel["r"] * 100, color="#2ca02c", linewidth=1.2)
    _style(axes[2], "3-month T-bill (DGS3MO)", "%")

    fig.suptitle(title, x=0.125, ha="left", fontsize=13)
    fig.autofmt_xdate()
    return fig


def metrics_table(metrics: pd.DataFrame, title: str = "Summary metrics") -> plt.Figure:
    """Render a metrics DataFrame as a figure, so results/ holds the whole story."""
    fig, ax = plt.subplots(figsize=(2 + 2.0 * len(metrics.columns), 0.5 * len(metrics) + 1.4))
    ax.axis("off")
    tbl = ax.table(
        cellText=[[f"{v}" for v in row] for row in metrics.round(4).to_numpy()],
        rowLabels=metrics.index,
        colLabels=[LABELS.get(c, c) for c in metrics.columns],
        loc="center",
        cellLoc="right",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.4)
    ax.set_title(title, loc="left", fontsize=12)
    return fig
