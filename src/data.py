"""
Data loading and alignment for the delta-hedging backtest.

Three inputs, three different calendars:

    AAPL daily bars      yfinance   -> defines the trading calendar
    VXAPL implied vol    FRED       -> Cboe 30-day IV on Apple options (percent)
    DGS3MO risk-free     FRED       -> 3-month T-bill, bond-equivalent yield (percent)

Everything is aligned onto the AAPL trading calendar. FRED series are
forward-filled onto that calendar (a market holiday for one source is not
always a holiday for the other), and every fill is counted and reported
rather than silently absorbed.

Nothing in this module looks ahead: `build_dataset` only ever propagates a
value forward in time (ffill), never backward (bfill).
"""

from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)

# --- project-level defaults (see DECISIONS.md) ------------------------------
TICKER = "AAPL"
START = "2022-01-01"
END = "2024-12-31"

VOL_SERIES = "VXAPLCLS"   # Cboe Equity VIX on Apple, close
RATE_SERIES = "DGS3MO"    # 3-Month Treasury constant maturity
FALLBACK_RATE = 0.04      # flat 4% if the rate series is unusable

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"


@dataclass
class LoadReport:
    """What happened during a load: row counts, gaps, and how they were filled."""

    rows: int
    start: date
    end: date
    filled: dict[str, int]          # column -> number of forward-filled cells
    dropped_leading: int            # rows dropped because a series had no value yet
    notes: list[str]

    def __str__(self) -> str:
        lines = [
            f"{self.rows} trading days, {self.start} -> {self.end}",
            "  forward-filled: "
            + (", ".join(f"{k}={v}" for k, v in self.filled.items()) or "none"),
        ]
        if self.dropped_leading:
            lines.append(f"  dropped {self.dropped_leading} leading rows (no data yet)")
        lines += [f"  note: {n}" for n in self.notes]
        return "\n".join(lines)


# ---------------------------------------------------------------- yfinance --
def load_prices(
    ticker: str = TICKER,
    start: str = START,
    end: str = END,
    *,
    cache: bool = True,
) -> pd.DataFrame:
    """Daily OHLCV for `ticker` from yfinance, tz-naive DatetimeIndex.

    Returns columns: open, high, low, close, adj_close, volume.

    `close` is the raw traded close; `adj_close` is back-adjusted for
    dividends and splits. Option payoffs settle against the *raw* price, so
    the backtest uses `close`; `adj_close` is kept for total-return
    comparisons. Both are stored so that choice stays visible.

    `end` is inclusive here (yfinance's own `end` is exclusive).
    """
    import yfinance as yf

    cache_path = DATA_DIR / f"{ticker}_{start}_{end}.parquet"
    if cache and cache_path.exists():
        log.info("prices: cache hit %s", cache_path.name)
        return pd.read_parquet(cache_path)

    end_exclusive = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    raw = yf.download(
        ticker,
        start=start,
        end=end_exclusive,
        auto_adjust=False,      # keep raw Close *and* Adj Close
        progress=False,
        actions=False,
    )
    if raw.empty:
        raise RuntimeError(f"yfinance returned no rows for {ticker} {start}..{end}")

    if isinstance(raw.columns, pd.MultiIndex):      # single-ticker download
        raw.columns = raw.columns.get_level_values(0)

    df = raw.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )[["open", "high", "low", "close", "adj_close", "volume"]]
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    df.columns.name = None      # yfinance leaves "Price" here after the flatten

    if cache:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path)
    return df


# -------------------------------------------------------------------- FRED --

def _fred_csv(series_id: str, start: str, end: str, *, attempts: int = 4) -> str:
    """GET one FRED series as CSV text, retrying on transient network errors.

    FRED occasionally drops a connection mid-handshake; a bare failure here
    would look like "the series does not exist", which is a much more
    alarming and much less true diagnosis.
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            resp = requests.get(
                FRED_CSV,
                params={"id": series_id, "cosd": start, "coed": end},
                timeout=45,
                # No custom User-Agent. FRED's edge sits behind bot mitigation
                # that silently black-holes requests carrying a browser-shaped
                # UA from a non-browser TLS stack -- and a custom UA fares no
                # better. requests' own default UA is accepted. See DECISIONS.md.
            )
            resp.raise_for_status()
            return resp.text
        except (requests.RequestException, OSError) as exc:  # noqa: PERF203
            last = exc
            log.warning("fred %s attempt %d/%d failed: %s", series_id, i + 1, attempts, exc)
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"could not fetch FRED series {series_id}") from last


def load_fred(
    series_id: str,
    start: str = START,
    end: str = END,
    *,
    cache: bool = True,
) -> pd.Series:
    """One FRED series as a float Series indexed by date, NaNs preserved.

    FRED writes missing observations as ".", which become NaN here rather
    than being dropped -- the caller decides how to fill them.

    Values are returned in FRED's own units (percent for both VXAPLCLS and
    DGS3MO). Conversion to decimals happens in `build_dataset`.
    """
    cache_path = DATA_DIR / f"{series_id}_{start}_{end}.parquet"
    if cache and cache_path.exists():
        log.info("fred: cache hit %s", cache_path.name)
        return pd.read_parquet(cache_path)[series_id]

    text = _fred_csv(series_id, start, end)
    df = pd.read_csv(io.StringIO(text))

    date_col, value_col = df.columns[0], df.columns[1]
    s = pd.Series(
        pd.to_numeric(df[value_col], errors="coerce").to_numpy(),
        index=pd.DatetimeIndex(pd.to_datetime(df[date_col])).normalize(),
        name=series_id,
    )
    s.index.name = "date"

    if cache:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        s.to_frame().to_parquet(cache_path)
    return s


# ------------------------------------------------------------------ merge ---
def build_dataset(
    ticker: str = TICKER,
    start: str = START,
    end: str = END,
    *,
    vol_series: str = VOL_SERIES,
    rate_series: str | None = RATE_SERIES,
    fallback_rate: float = FALLBACK_RATE,
    max_ffill_days: int = 5,
    cache: bool = True,
) -> tuple[pd.DataFrame, LoadReport]:
    """Build the aligned daily panel the backtest consumes.

    Columns
    -------
    close, adj_close, volume : AAPL, raw and dividend/split-adjusted
    sigma                    : implied vol as a decimal (VXAPL / 100)
    r                        : risk-free as a decimal (DGS3MO / 100)

    Alignment rules
    ---------------
    * The AAPL trading calendar is authoritative; FRED is reindexed onto it.
    * Gaps are forward-filled up to `max_ffill_days` consecutive days. A
      longer gap is left as NaN and surfaced in the report -- silently
      carrying a three-week-old volatility number is worse than a loud NaN.
    * Leading rows with no FRED value yet are dropped, and counted.
    * No backward filling anywhere: a day never sees a future observation.
    """
    px = load_prices(ticker, start, end, cache=cache)
    notes: list[str] = []
    filled: dict[str, int] = {}

    df = px.copy()

    def attach(series_id: str, out_col: str, scale: float) -> None:
        raw = load_fred(series_id, start, end, cache=cache)
        on_cal = raw.reindex(df.index)
        missing_before = int(on_cal.isna().sum())
        ffilled = on_cal.ffill(limit=max_ffill_days)
        filled[out_col] = missing_before - int(ffilled.isna().sum())
        still_missing = int(ffilled.isna().sum())
        if still_missing:
            notes.append(
                f"{series_id}: {still_missing} trading days still missing after "
                f"{max_ffill_days}-day ffill"
            )
        df[out_col] = ffilled * scale

    attach(vol_series, "sigma", 0.01)

    if rate_series is None:
        df["r"] = fallback_rate
        filled["r"] = 0
        notes.append(f"risk-free held constant at {fallback_rate:.2%}")
    else:
        attach(rate_series, "r", 0.01)

    n_before = len(df)
    df = df.dropna(subset=["sigma", "r"], how="any")
    dropped = n_before - len(df)

    if df.empty:
        raise RuntimeError(
            "no rows survived alignment -- check that the FRED series covers "
            f"{start}..{end}"
        )

    report = LoadReport(
        rows=len(df),
        start=df.index[0].date(),
        end=df.index[-1].date(),
        filled=filled,
        dropped_leading=dropped,
        notes=notes,
    )
    return df, report


def coverage(series_id: str, start: str = START, end: str = END) -> str:
    """One-line description of what a FRED series actually covers. Diagnostic."""
    s = load_fred(series_id, start, end, cache=False).dropna()
    if s.empty:
        return f"{series_id}: NO observations in {start}..{end}"
    return (
        f"{series_id}: {len(s)} obs, {s.index[0].date()} -> {s.index[-1].date()}, "
        f"last={s.iloc[-1]:.2f}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(coverage(VOL_SERIES))
    print(coverage(RATE_SERIES))
    panel, rep = build_dataset()
    print(rep)
    print(panel.head())
    print(panel.tail())
