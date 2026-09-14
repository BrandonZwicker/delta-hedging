"""
The backtest: run a protective-put hedge over the 2022-2024 AAPL panel.

One loop, one day at a time. Three configurations share the same loop and
differ only in how often they rebalance.

    unhedged        100 shares, no options
    hedged_daily    rebalance to zero net delta every trading day
    hedged_weekly   same target, every 5th trading day

Contract spec, which is set out in full in DECISIONS.md, is a 90 calendar day
tenor struck at 0.95 * spot on the roll date, rolled under 30 days to expiry,
100 shares a contract with fractional contracts allowed and no trading costs.

Every decision on day t uses only `row`, meaning that day's close, sigma and r.
If a number is not in `row` it cannot enter a decision, which is what keeps
lookahead out. The only state carried across days is the position itself,
being shares, contracts, cash, strike and expiry.

Nothing in this file is ever exercised or settled, b/c the roll rule sells
each put at 30 DTE with time value still in it, so every option is opened and
closed at a model price.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src import data
from src import plots
from src.constants import (
    CONTRACT_SIZE,
    DAY_COUNT,
    MIN_HEDGE_DELTA,
    OTM_FRACTION,
    ROLL_AT_DTE,
    START_SHARES,
    TENOR_DAYS,
)
from src.black_scholes import delta as bs_delta
from src.black_scholes import put_price
from src.hedging import contracts_to_hedge

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


@dataclass(frozen=True)
class Config:
    """One backtest configuration."""

    name: str
    hedged: bool
    rebalance_every: int = 1        # trading days between rebalances

    @property
    def label(self) -> str:
        return self.name


CONFIGS = [
    Config("unhedged", hedged=False),
    Config("hedged_daily", hedged=True, rebalance_every=1),
    Config("hedged_weekly", hedged=True, rebalance_every=5),
]


def run_backtest(panel: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Run one configuration over the panel and return the daily path.

    Parameters
    ----------
    panel : DataFrame from src.data.build_dataset(), indexed by date, with
            columns close, sigma, r, plus others which go unused here.
    config : which configuration to run.

    Returns
    -------
    DataFrame indexed by date with one row per trading day and columns:
        close, sigma, r          the inputs used that day
        strike, dte, tau_years   the option currently held
        put_px, put_delta        its model price and delta (NaN if unhedged)
        contracts                contracts held at end of day
        cash                     cash balance
        portfolio_value          shares + options + cash, marked to market
        portfolio_delta          net delta of the whole position
        rebalanced               True if contracts changed today
        rolled                   True if the option was rolled today
        trade_contracts          signed change in contracts
        option_cashflow          signed cash from option trades (negative = paid)
        cum_hedge_cost           cumulative net cash spent on protection
    """
    # Opening position is 100 shares bought at the first close. Cash starts at
    # zero, so all three configs open at the same portfolio value and the
    # equity curves can be read against each other directly.
    shares = float(START_SHARES)
    contracts = 0.0
    cash = 0.0
    strike: float | None = None
    expiry: pd.Timestamp | None = None

    records: list[dict] = []
    cum_hedge_cost = 0.0
    prev_date: pd.Timestamp | None = None

    for i, (date, row) in enumerate(panel.iterrows()):
        S, sigma, r = row["close"], row["sigma"], row["r"]

        # Accrue interest on the cash balance. Cash goes negative once puts are
        # bought, which is a real financing cost, and rates ran from 0.08% to
        # 5.6% inside this window.
        if prev_date is not None:
            dt = (date - prev_date).days / DAY_COUNT
            cash *= np.exp(r * dt)

        rolled = False
        rebalanced = False
        trade_contracts = 0.0
        option_cashflow = 0.0
        put_px = np.nan
        put_delta = np.nan
        dte = np.nan
        tau_years = np.nan

        if config.hedged:
            # Days to expiry on the option currently held.
             if expiry is not None:
                dte = (expiry - date).days
                tau_years = dte / DAY_COUNT

            # Roll if the option is too close to expiry. The existing contract
            # has to be sold first, at the old strike and old tau, before those
            # get overwritten. Getting that order wrong prices the sale against
            # a contract which isn't held yet, and it fails silently.
             if expiry is None or dte < ROLL_AT_DTE:
                       if contracts != 0:
                           old_px = put_price(S, strike, tau_years, sigma, r)
                           cash += contracts * CONTRACT_SIZE * old_px
                           cum_hedge_cost -= contracts * CONTRACT_SIZE * old_px
                           contracts = 0.0
                       strike = (1 - OTM_FRACTION) * S
                       expiry = date + pd.Timedelta(days=TENOR_DAYS)
                       dte = TENOR_DAYS
                       tau_years = dte / DAY_COUNT
                       rolled = True

            # Price today's option and take its delta.
             put_px    = put_price(S, strike, tau_years, sigma, r)
             put_delta = bs_delta(S, strike, tau_years, sigma, r, "put")

            # Rebalance on schedule, and always on a roll day.
             if rolled or (i % config.rebalance_every == 0):
                       # Size off a floored delta but log the real one. This
                       # leg is always a put, so the floored magnitude is
                       # re-signed negative to match the signed delta
                       # contracts_to_hedge expects.
                       hedge_delta = -max(abs(put_delta), MIN_HEDGE_DELTA)
                       target = contracts_to_hedge(shares, hedge_delta)
                       trade_contracts = target - contracts
                       if trade_contracts != 0:
                           option_cashflow = -trade_contracts * CONTRACT_SIZE * put_px
                           cash += option_cashflow
                           cum_hedge_cost -= option_cashflow
                           contracts = target
                           rebalanced = True
                           
        # Mark the whole position to market.
        if config.hedged:
            option_value    = contracts * CONTRACT_SIZE * put_px
            portfolio_value = shares * S + option_value + cash
            portfolio_delta = shares + contracts * CONTRACT_SIZE * put_delta
        else:
            portfolio_value = shares * S + cash
            portfolio_delta = shares

        records.append(
            dict(
                date=date, close=S, sigma=sigma, r=r,
                strike=strike if config.hedged else np.nan,
                dte=dte, tau_years=tau_years,
                put_px=put_px, put_delta=put_delta,
                contracts=contracts, cash=cash,
                portfolio_value=portfolio_value,
                portfolio_delta=portfolio_delta,
                rebalanced=rebalanced, rolled=rolled,
                trade_contracts=trade_contracts,
                option_cashflow=option_cashflow,
                cum_hedge_cost=cum_hedge_cost,
            )
        )
        prev_date = date

    return pd.DataFrame(records).set_index("date")


# --- runner and file output -------------------------------------------------
def run_all(panel: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Run every configuration and return {name: path DataFrame}."""
    if panel is None:
        panel, _ = data.build_dataset()
    return {c.name: run_backtest(panel, c) for c in CONFIGS}


def equity_frame(paths: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Collapse the runs into one DataFrame of equity curves, for plotting."""
    return pd.DataFrame({name: p["portfolio_value"] for name, p in paths.items()})


def save_results(paths: dict[str, pd.DataFrame]) -> None:
    """Write each daily path to results/ as CSV."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, p in paths.items():
        p.to_csv(RESULTS_DIR / f"path_{name}.csv")
    equity_frame(paths).to_csv(RESULTS_DIR / "equity_curves.csv")


def save_figures(panel: pd.DataFrame, paths: dict[str, pd.DataFrame]) -> list:
    """Write every figure to results/ and return the paths written."""
    eq = equity_frame(paths)
    return [
        plots.save(plots.plot_inputs(panel), "00_inputs"),
        plots.save(plots.plot_equity_curves(
            eq, shade={"2022 drawdown": ("2022-01-03", "2023-01-03")}), "01_equity_curves"),
        plots.save(plots.plot_drawdown(eq), "02_drawdown"),
        plots.save(plots.plot_delta_path(
            paths["hedged_daily"], title="Portfolio delta, daily rebalance"), "03_delta_daily"),
        plots.save(plots.plot_delta_path(
            paths["hedged_weekly"], title="Portfolio delta, weekly rebalance"), "04_delta_weekly"),
        plots.save(plots.plot_hedge_cost(
            {k: v for k, v in paths.items() if k != "unhedged"}), "05_hedge_cost"),
    ]


if __name__ == "__main__":
    panel, report = data.build_dataset()
    print(report)

    paths = run_all(panel)
    save_results(paths)
    for fig in save_figures(panel, paths):
        print(f"  wrote {fig.name}")

    eq = equity_frame(paths)
    print("\nequity curves (first and last row):")
    print(eq.head(1).to_string())
    print(eq.tail(1).to_string())

    for name, p in paths.items():
        print(
            f"\n{name}: {int(p['rebalanced'].sum())} rebalances, "
            f"{int(p['rolled'].sum())} rolls, "
            f"hedge cost ${p['cum_hedge_cost'].iloc[-1]:,.0f}"
        )
