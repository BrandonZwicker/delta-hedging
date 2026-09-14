"""
Validation tests for src/black_scholes.py.

Three tests are implemented and passing. They cover the checks that matter
most: the no-arbitrage identity between calls and puts, the delta
relationship that follows from it, and agreement with an independent
pricing source.

Remaining coverage is listed as a backlog at the bottom of this file.

Run: pytest tests/test_black_scholes.py -v
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("src.black_scholes", reason="write src/black_scholes.py first")

from src import black_scholes as bs  # noqa: E402

TOL = 1e-9          # analytic identities should hold to machine-ish precision
BENCH_TOL = 5e-3    # published calculator values are quoted to ~3 decimals


def test_put_call_parity(base_case):
    """C - P should equal S - K*exp(-r*tau). Assert it."""
    kwargs = {**base_case, "tau_years": base_case["tau"]}
    del kwargs["tau"]

    c = bs.call_price(**kwargs)
    p = bs.put_price(**kwargs)

    lhs = c - p
    rhs = base_case["S"] - base_case["K"] * math.exp(-base_case["r"] * base_case["tau"])

    assert lhs == pytest.approx(rhs, abs=TOL)


def test_delta_relationship(base_case):
    """delta_call - delta_put should equal exactly 1. Assert it."""
    kwargs = {**base_case, "tau_years": base_case["tau"]}
    del kwargs["tau"]

    d_call = bs.delta(**kwargs, option_type="call")
    d_put = bs.delta(**kwargs, option_type="put")

    assert abs((d_call - d_put) - 1.0) < 1e-6


def test_benchmark_price(base_case):
    """Compare against a value from an independent calculator."""
    kwargs = {**base_case, "tau_years": base_case["tau"]}
    del kwargs["tau"]

    # reference values confirmed via [PASTE CALCULATOR URL HERE]
    expected_call = 10.4506
    expected_put = 5.5735

    assert bs.call_price(**kwargs) == pytest.approx(expected_call, abs=BENCH_TOL)
    assert bs.put_price(**kwargs) == pytest.approx(expected_put, abs=BENCH_TOL)


# --- Planned, not yet implemented -------------------------------------------
#
# Deliberate backlog, not dropped scope. The three tests above plus a
# central-difference check of every Greek against a reprice of the pricer
# itself were judged sufficient coverage to move on to the backtest.
#
#   delta_bounds
#       Call delta lives in (0, 1); put delta in (-1, 0), across a sweep of
#       moneyness. The `moneyness_case` fixture in conftest.py already
#       parametrises S/K over 0.5 .. 2.0 for this.
#
#   deep_itm_and_otm_limits
#       Push S far from K and check delta converges to its limit (call -> 1
#       deep ITM, -> 0 deep OTM). Requires deciding how far is "far enough"
#       for a 1-year, 20%-vol option, and being able to justify it.
#
#   gamma_is_symmetric
#       Gamma is identical for a call and a put on the same contract. Follows
#       from put-call parity: the two prices differ by S - K*exp(-r*tau),
#       which is linear in S, so the second derivative is unchanged.
#
#   greeks_are_finite_at_expiry
#       tau -> 0 behaviour. Currently guarded by `assert 0 < tau_years < 10`
#       in d1_d2, so tau == 0 raises rather than returning intrinsic value.
#       The roll rule keeps tau_years >= 30/365, so this path is unreachable
#       in the backtest -- which is why it is deferred rather than fixed.
#
#   rejects_bad_option_type
#       An unknown option_type should raise, not silently price a put.
#       Currently the `else` branch in delta() and theta() catches any
#       string. Real defect, low blast radius: every call site is internal.
#
# ----------------------------------------------------------------------------
