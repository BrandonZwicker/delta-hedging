"""Shared pytest fixtures, being the inputs each test runs against.

The assertions about what Black-Scholes should produce live in the test files
themselves, b/c these fixtures only decide what gets priced rather than what
counts as the right answer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))          # so `import src.black_scholes` works


@pytest.fixture
def base_case() -> dict:
    """A plain vanilla setup at S=100, K=100, tau=1 year, sigma=20%, r=5%.

    Round numbers, which makes checking any of it by hand straightforward.
    """
    return dict(S=100.0, K=100.0, tau=1.0, sigma=0.20, r=0.05)


@pytest.fixture
def otm_put_case() -> dict:
    """Roughly the option this project actually trades, a 5% OTM put 90 days out."""
    return dict(S=180.0, K=171.0, tau=90 / 365, sigma=0.28, r=0.045)


@pytest.fixture(params=[0.5, 0.8, 1.0, 1.25, 2.0], ids=lambda m: f"S/K={m}")
def moneyness_case(request, base_case) -> dict:
    """The base case swept across moneyness, from deep OTM to deep ITM."""
    case = dict(base_case)
    case["S"] = base_case["K"] * request.param
    return case


@pytest.fixture
def synthetic_panel() -> pd.DataFrame:
    """A deterministic 250-day price/vol/rate panel shaped like src.data output.

    Geometric random walk on a fixed seed, which lets the backtest loop be
    exercised without touching the network.
    """
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2022-01-03", periods=250, name="date")
    rets = rng.normal(0.0003, 0.018, len(dates))
    close = 180.0 * np.exp(np.cumsum(rets))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "adj_close": close,
            "volume": 1_000_000,
            "sigma": 0.25 + 0.05 * np.sin(np.arange(len(dates)) / 20),
            "r": 0.04,
        },
        index=dates,
    )
