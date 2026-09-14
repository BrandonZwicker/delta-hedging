"""Contract specification, shared by every strategy file."""

# --- contract spec ---------------------------------------------------------
TENOR_DAYS = 90         # calendar days from roll to expiry
ROLL_AT_DTE = 30        # roll when fewer than this many days remain
OTM_FRACTION = 0.05     # strike = (1 - OTM_FRACTION) * spot
CONTRACT_SIZE = 100     # shares per contract
DAY_COUNT = 365.0       # tau_years = calendar_days / DAY_COUNT
START_SHARES = 100

# Floor on the delta used for SIZING the hedge. A 5%-OTM put loses delta as it
# goes further out of the money, and the hedge ratio -shares/(size*delta)
# diverges as delta -> 0: without a floor the loop bought 440 contracts against
# 100 shares on 2024-12-06, which is a long-gamma bet, not a hedge. The floor
# caps the position at shares / (CONTRACT_SIZE * MIN_HEDGE_DELTA) = 10
# contracts and says, in effect, "below this delta the option is not a usable
# hedging instrument; stop pretending it is."
MIN_HEDGE_DELTA = 0.10
