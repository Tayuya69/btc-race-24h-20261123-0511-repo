"""Donchian breakout + dip-buy bot for the btc-race-24h-20261123-0511 bounty.

Trades cbBTC (CBBTC) against USDC on 1-minute bars, long only, one position at
a time, full size. Speaks agent-fun/bars-replay/v1 through the kit's Python
shim (vendor/makefun_bars.py, a byte-identical copy of the kit SDK).

Strategy (designed from the kit's frozen 24h dev window, where BTC rose
+3.6% in one concentrated 2-hour rally and then chopped sideways):

- The dev window punishes fast signals: a plain EMA(8)/EMA(21) cross trades
  ~76 times and loses about $115 to whipsaw and fees. What works is catching
  a genuine break of the recent range and then holding it with a wide
  trailing stop, plus buying sharp dips only while the long-term trend is up.
- Entry A (breakout): the close breaks above the highest close of the last
  30 minutes, and the close is above the 240-minute EMA (long-term uptrend).
  Before the 240-bar EMA exists the filter is skipped.
- Entry B (dip): the close falls 0.5% below the 30-minute EMA while staying
  above the 240-minute EMA -- a dip inside an uptrend.
- Exit: the whole position is sold when the close falls 1.5% below the best
  close since entry (trailing stop), or 2% below the entry close (hard
  stop); a dip entry also takes profit at +1.5% over entry. A breakout entry
  has no take-profit: it rides the move until the trailing stop fires.
- One full-size round trip costs about 26 bps in fees, slippage and price
  impact, so entries wait for moves well above that; the wide stops keep the
  trade count low (5 trades on the dev window) and the max drawdown small.

All arithmetic is deterministic float64 on the closes the harness sends; no
clock, no environment, no randomness, no network, no files outside the repo.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

SYMBOL = "CBBTC"

# --- strategy parameters (bars are 1 minute) ---
DONCHIAN_BARS = 30        # breakout lookback: highest close of the last 30 bars
FAST_EMA_BARS = 30        # dip reference: 30-minute EMA
TREND_EMA_BARS = 240      # long-term trend: 240-minute EMA
DIP_BPS = 50              # dip entry: close this far below the fast EMA (0.5%)
DIP_TAKE_PROFIT_BPS = 150  # dip entry takes profit at +1.5% over entry
TRAIL_BPS = 150           # exit: close this far below the best close since entry
STOP_BPS = 200            # exit: close this far below the entry close
MAX_SLIPPAGE_BPS = 300    # orders are refused past 3% from the latest close


class Ema:
    """An EMA seeded as the mean of its first span of closes, then updated
    by 2 / (span + 1) of the way to each new close (float64, deterministic)."""

    def __init__(self, span):
        self.span = span
        self.warm = []
        self.value = None

    def push(self, close):
        if self.value is not None:
            self.value += (2.0 / (self.span + 1)) * (close - self.value)
            return
        self.warm.append(close)
        if len(self.warm) == self.span:
            self.value = sum(self.warm) / self.span
            self.warm = []


class Bot:
    def __init__(self):
        self.closes = []            # closes seen, oldest first
        self.fast_ema = Ema(FAST_EMA_BARS)
        self.trend_ema = Ema(TREND_EMA_BARS)
        self.entry_close = None     # close at the bar the current buy was decided on
        self.peak_close = None      # best close since entry
        self.mode = None            # "breakout" or "dip"
        self.pending_buy = False    # a buy was sent and not yet confirmed filled

    def on_batch(self, state, batch):
        bar = state.latest.get(SYMBOL)
        if bar is None:
            return []
        price_scale = state.symbols[SYMBOL]["price_scale"]
        close = int(bar["c"]) / (10 ** price_scale)
        self.closes.append(close)
        self.fast_ema.push(close)
        self.trend_ema.push(close)

        holding = state.positions.get(SYMBOL)
        has_position = holding is not None and holding.qty > 0

        # A buy sent last bar either filled (position now held) or was
        # rejected (no position): clear the pending flag either way.
        if self.pending_buy:
            self.pending_buy = False
            if not has_position:
                self.entry_close = None
                self.peak_close = None
                self.mode = None

        if has_position and self.entry_close is not None:
            self.peak_close = max(self.peak_close, close)

        if state.warming_up:
            return []

        if not has_position:
            return self._maybe_enter(state, close)
        return self._maybe_exit(state, close)

    def _maybe_enter(self, state, close):
        trend_up = True
        if self.trend_ema.value is not None:
            trend_up = close > self.trend_ema.value

        breakout = False
        if len(self.closes) > DONCHIAN_BARS:
            breakout = close > max(self.closes[-DONCHIAN_BARS - 1:-1])

        dip = False
        if self.fast_ema.value is not None and self.trend_ema.value is not None:
            dip = (
                close < self.fast_ema.value * (1 - DIP_BPS / 10000.0)
                and close > self.trend_ema.value
            )

        mode = None
        if breakout and trend_up:
            mode = "breakout"
        elif dip:
            mode = "dip"
        if mode is None:
            return []

        cash = state.cash
        if cash <= int(state.hello["fees"]["min_notional_quote_units"]):
            return []
        self.entry_close = close
        self.peak_close = close
        self.mode = mode
        self.pending_buy = True
        return [
            {
                "side": "buy",
                "symbol": SYMBOL,
                "notional_quote_units": cash,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }
        ]

    def _maybe_exit(self, state, close):
        if self.entry_close is None:
            # Holding a position we did not open (should not happen): hold.
            return []
        sell = False
        if self.peak_close is not None and close < self.peak_close * (1 - TRAIL_BPS / 10000.0):
            sell = True
        if close < self.entry_close * (1 - STOP_BPS / 10000.0):
            sell = True
        if (
            self.mode == "dip"
            and close > self.entry_close * (1 + DIP_TAKE_PROFIT_BPS / 10000.0)
        ):
            sell = True
        if not sell:
            return []
        holding = state.positions[SYMBOL]
        self.entry_close = None
        self.peak_close = None
        self.mode = None
        return [
            {
                "side": "sell",
                "symbol": SYMBOL,
                "qty": holding.qty,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }
        ]


def main():
    bot = Bot()
    makefun_bars.run(bot.on_batch)


if __name__ == "__main__":
    main()
