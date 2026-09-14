# Decisions log

Every parameter choice in this project, what I picked and why. Written as I go
rather than reconstructed after the fact. If I can't write the why line, I
don't understand the choice yet.

---

## Setup

**AAPL, 2022-01-01 to 2024-12-31, 100 shares long, hedged with European puts
priced by Black-Scholes.**
Picked the window b/c it has the 2022 drawdown and the 2023-24 recovery in it.
Hedge pays in one, drags in the other. A bull-only sample would have decided
the answer before I started.

**Implied vol from VXAPL (FRED `VXAPLCLS`), divided by 100.**
A vol I made up would be circular, ie it would only confirm itself. VXAPL is
what the market actually charged for Apple vol that day, premium and all,
which is what makes the protection genuinely cost something. Checked coverage
first: 3,922 obs going back to 2010-06-01, so the whole window is there.

**Risk-free from `DGS3MO`, not a constant.**
Rates went ~0% to ~5.4% inside this window, so a flat 4% would misprice both
ends of it. Left `build_dataset(rate_series=None)` in as a constant-rate mode
for sanity checks.

**Raw `close` for option payoffs, not `adj_close`.**
A real option settles against the price that actually traded. Back-adjusting
for dividends rewrites history and shifts every strike relative to spot. Store
`adj_close` anyway for total-return comparison on the share leg.
*Still open: no dividend yield in the pricer. AAPL yields ~0.5% so puts come
out slightly underpriced. Need to decide whether to add `q`.*

**Forward-fill FRED up to 5 days, then fail loudly.**
Calendars disagree by a day here and there, which is harmless. Carrying a
three-week-old vol into a pricing model is not, b/c that's a bug that looks
exactly like a result. Never backward-fill either, that's lookahead.

---

## Model choices

**Day count: 365 calendar days throughout, no 252-trading-day split.**
Keeps it consistent with all my validated reference numbers, and avoids mixing
day-count conventions between σ and τ.

**90 day tenor and a strike at exactly 0.95 * spot, both synthetic.**
Real listed options come on a grid, being monthly third-Friday expiries and
strikes in $2.50 or $5 steps, and I could have snapped to that grid. Decided
against it b/c every option price in this project is already generated from a
single at-the-money volatility with no smile, so snapping the expiry and strike
would add the appearance of realism to a price which is not real anyway.
Holding tenor and moneyness constant also means the hedging error I measure is
down to rebalancing frequency rather than tenor drifting between cycles.

**Fractional contracts allowed.**
A real account trades whole contracts, so this is a simplification. Took it b/c
integer rounding would add a second source of error on top of the one I am
trying to isolate, and the hedge ratio lands around 3.31 contracts where
rounding to 3 would be a ~9% error in the hedge itself.

**No transaction costs, commissions or slippage.**
Every trade happens at the model price. Means the cost of hedging reported here
is a floor rather than a realistic number, which is stated in the README.
Adding costs would push all three configurations down and would push the weekly
one down least, since it trades a quarter as often.

### Pricing & Greeks (`black_scholes.py`)

- `d1_d2` had two bugs early on. Messed up order of operations, only scaled
  σ²/2 by tau instead of the whole (r−σ²/2) term, and a numpy array sneaking
  in instead of a plain float from bracket indexing. Both squashed.
- `call_price`, `put_price`, `delta`, `gamma`, `theta`, `vega` are all built
  and checked against my base case numbers, being 100 shares AAPL @ $180, $171
  strike, 90 days out, σ=28%, r=4.5%, where the put should come out to
  $5.1871.

---

## Backtest choices

### Hedging + backtest build (`hedging.py`, `backtest.py`)

- Built `contracts_to_hedge` for delta-neutral sizing.
- Built the backtest loop piece by piece instead of all at once (roll,
  price/delta, rebalance, mark-to-market), which was a good thing b/c it caught
  a bunch of structural bugs before I ever got a full run.

---

### Delta floor of 0.10

**`MIN_HEDGE_DELTA = 0.10`, applied to the delta used for sizing only.**
Sizing to zero net delta means holding `-shares / (contract_size * delta)`
contracts, which runs away as delta approaches zero. A 5% OTM put loses delta
as the stock rallies, and on 2024-12-06 the loop bought 439.7 contracts against
100 shares, ie a long volatility bet rather than a hedge. The floor caps the
position at 10 contracts.

Put it in `constants.py` and applied it at the call site rather than inside
`contracts_to_hedge`, b/c that function has to keep returning the count which
actually reaches the target it was asked for. A function quietly returning a
number that misses its own target would be lying to every future caller.

The real delta is still what gets logged, so the output shows what the option
actually was rather than the floored stand-in. Worth being clear that the floor
does not fix the underlying problem. The portfolio is not delta-neutral on ~27%
of days and its net delta reaches 97.7 on the worst of them, which is close to
unhedged.

### Two extra hedge variants moved to a branch

**A static 1:1 protective put and a dealer-style share overlay both came off
`main` onto the `hedge-variants` branch.**
Built both while working out why the delta sizing kept blowing up, and the
share overlay is the one which actually solves it, b/c a share has a delta of
exactly 1 so nothing divides by a number approaching zero. Took them off main
to keep the project to the three configurations it set out to compare. Neither
is polished enough to present, and the README discusses the approach rather
than pointing at the code.

## Things that broke

**FRED silently timed out on a "polite" User-Agent.**
Every request hung for the full timeout then failed, but `curl` to the same URL
came back 200 instantly. Looked like a Python or TLS problem. Swept the UA
across four values instead of guessing: `curl/8.7.1` and the requests default
both returned in under half a second, a browser-shaped `Mozilla/5.0` UA and my
own `delta-hedging/0.1` UA timed out every single time. So never the client,
just FRED's bot mitigation black-holing anything it doesn't recognise. Fix was
to send no UA at all.

Worth noting a hang is a diagnosis too. A silent read timeout means something
dropped the request, which points at the shape of the request rather than
where it was going.

### 2026-09-11 - The 2022 gain looked wrong and my first two explanations were both wrong

**What broke:** The daily hedged config returned +10.7% over the 2022 drawdown
while Apple fell 31%. A hedge is not supposed to make money like that, so
either the result was real and interesting or something was broken.

**First explanation, wrong:** Gamma scalping. A long put position is long
gamma, so it profits when realized volatility beats implied. Checked it instead
of assuming. Realized came in at 35.7% against 36.5% implied over 2022, so
gamma net of theta actually contributed -$204. Wrong sign.

**Second explanation, also wrong:** The roll mechanics. Thought the re-strike
every ~60 days might be mispricing one leg. Attribution put the residual on
roll days at -$53 across all six rolls in 2022, which is nothing.

**What it actually was:** Full attribution of the $1,942 gain comes to vega
+$1,425, third-order convexity on large down days +$1,152, residual delta on
floor-pinned days -$496, gamma net of theta -$204, and interest +$64. That
reconciles to $1. VXAPL went from 30.8% to 45.1% over the year, so most of the
gain was from holding puts while implied volatility spiked.

**Lesson:** The position was closer to a long-volatility bet than a delta
hedge, which is the honest description of it. Also worth noting that a
plausible explanation which fits the direction of a result is not evidence, and
checking it cost about twenty minutes.
