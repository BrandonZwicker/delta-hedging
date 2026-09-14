"""
*
- First calculating Black Scholes to determine fair price (Premium) of an option today
aka the cost to build a replication of stock + cash which can match the options payoff.

- For the sake of this project, ive simplified things by using European Options
versus American options. B/c European options can only be exercised exactly at expiry,
it lets us know exactly what the option will pay and when, which is what gives us
a closed form solution rather than having to solve it numerically.

- B/c American options can be exercised at any point before expiry, it adds additional
layers of complication. Can explore this at a later time.

Reference case: S=180, K=171, tau_years=90/365, sigma=0.28, r=0.045 -> put = $5.1871
"""

import numpy as np
from scipy.stats import norm


def d1_d2(S, K, tau_years, sigma, r):
    """
    *
    - First d1 and d2 need to be calculated.
    - d2 is a measure of how many standard deviations away from an average value sits (Z-Score)
    In a more intuitive sense, it is the number of standard deviations the strike sits below
    where the stock is expected to end up, so a higher d2 means deeper in-the-money.
    This is then converted into the probability that the option finishes in-the-money.
    *Worth noting this is the risk neutral probability rather than the real world one.
    - d1 measures this same probability but is reweighted based on how much a stock backs each outcome.
    This means scenarios where the option pays off more money are weighted more than scenarios where
    the option pays off less.

    Parameters
    ----------
    S : float — current stock price
    K : float — strike price
    tau_years : float — time to expiry, IN YEARS (not days!)
    sigma : float — annualized volatility (e.g. 0.28, not 28)
    r : float — risk-free rate (e.g. 0.045, not 4.5)

    Returns
    -------
    (d1, d2) : tuple of floats
    """
    assert 0 < tau_years < 10, "tau_years looks wrong — did you pass days instead of years?"

    d2 = ( np.log(S/K) + ( (r - ((sigma**2)/2))* tau_years) ) / (sigma * np.sqrt(tau_years))
    d1 = d2 + ( sigma*np.sqrt(tau_years))

    return d1, d2


def call_price (S,K,tau_years,sigma,r):
    """
    - This function calculates the fair price of a European call option (in dollars).
    """
    d1, d2 = d1_d2(S, K, tau_years, sigma, r)
    C = (S * norm.cdf(d1) ) - (K * np.exp(-r*tau_years)* norm.cdf(d2))

    return C

def put_price(S,K,tau_years,sigma,r):
    """Same for a European put. The only pricer the backtest calls."""
    d1,d2 = d1_d2(S,K,tau_years,sigma,r)

    P = (K*np.exp(-r*tau_years)*norm.cdf(-d2)) - (S * norm.cdf(-d1))

    return P


# --- Next is calculating the greeks -----------------------------------------


def delta(S,K,tau_years,sigma,r,option_type):
    """
    Delta

    - Beginning with Delta, which represents number of shares held in the replication portfolio
    - ie how much the option price moves per $1 the stock moves
    """
    assert option_type in ("call", "put"), f"option_type must be 'call' or 'put', got {option_type!r}"
    d1, d2 = d1_d2(S,K,tau_years,sigma,r)

    if option_type == "call":
        delta_value = norm.cdf(d1)

    else:
        delta_value = norm.cdf(d1)-1

    return delta_value


def gamma(S,K,tau_years,sigma,r):
    """
    Gamma

    - Gamma, which represents how much delta moves per $1 stock move
    - ie calculating how much and how quickly your delta is changing,
    which in turn helps to indicate how much rebalancing needs to be done and how frequently
    """
    d1, d2 = d1_d2(S,K,tau_years,sigma,r)

    gamma_value = norm.pdf(d1) / (S*sigma* np.sqrt(tau_years))

    return gamma_value


def theta (S,K,tau_years,sigma,r,option_type):
    """
    Theta

    - Theta next, which represents the dollar cost of a day passing, if everything else was
    considered to be fixed. Usually a cost, though deep in-the-money puts can have positive
    theta b/c the strike is worth more discounted less.
    """
    assert option_type in ("call", "put"), f"option_type must be 'call' or 'put', got {option_type!r}"
    d1, d2 = d1_d2(S,K,tau_years,sigma,r)

    x = -(S * norm.pdf(d1) * sigma) /(2 * np.sqrt(tau_years))

    if option_type == "call":
        theta_value = x - (r*K* np.exp(-r*tau_years)* norm.cdf(d2))

    else:
        theta_value = x + (r*K* np.exp(-r*tau_years)* norm.cdf(-d2))

    #Convert theta value to per day instead of annual
    theta_value = theta_value/365
    return theta_value


def vega(S,K,tau_years,sigma,r):
    """
    Vega

    - Vega next, which represents the options price change with a small shift in volatility
    """
    d1, d2 = d1_d2(S,K,tau_years,sigma,r)

    vega_value = S * norm.pdf(d1) * np.sqrt(tau_years)

    #Convert vega value to price change per 1% point instead of per 100 points of sigma
    vega_value = vega_value / 100

    return vega_value
