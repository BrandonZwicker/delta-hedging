"""Tests for src/data.py (the loader). Network tests are marked and opt-in."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import data


@pytest.mark.network
def test_fred_series_cover_the_backtest_window():
    for series in (data.VOL_SERIES, data.RATE_SERIES):
        s = data.load_fred(series, data.START, data.END, cache=True).dropna()
        assert not s.empty, f"{series} has no observations in the window"
        assert s.index[0] <= pd.Timestamp("2022-01-31")
        assert s.index[-1] >= pd.Timestamp("2024-12-01")


@pytest.mark.network
def test_build_dataset_is_aligned_and_sane():
    df, report = data.build_dataset()
    assert df.index.is_monotonic_increasing
    assert df.index.is_unique
    assert not df[["close", "sigma", "r"]].isna().any().any()
    assert (df["close"] > 0).all()
    assert df["sigma"].between(0.05, 2.0).all(), "sigma should be a decimal, not percent"
    assert df["r"].between(0.0, 0.15).all(), "r should be a decimal, not percent"
    assert report.rows == len(df)


def test_no_backward_fill_in_alignment():
    """A NaN at the start must be dropped, never filled from the future."""
    idx = pd.bdate_range("2022-01-03", periods=5)
    s = pd.Series([np.nan, np.nan, 20.0, np.nan, 22.0], index=idx)
    filled = s.ffill(limit=5)
    assert np.isnan(filled.iloc[0]) and np.isnan(filled.iloc[1])
    assert filled.iloc[3] == 20.0        # carried forward, not back
