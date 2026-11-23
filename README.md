# BTC Race Bot — Donchian Breakout + Dip Buy

[![make.fun](https://img.shields.io/badge/make.fun-bounty-blue)](https://make.fun/bounty/btc-race-24h-20261123-0511)
[![make.fun](https://img.shields.io/badge/make.fun-entry-green)](https://make.fun/bounty/btc-race-24h-20261123-0511)
[![make.fun](https://img.shields.io/badge/make.fun-cbBTC-orange)](https://make.fun/bounty/btc-race-24h-20261123-0511)

Entry for the [make.fun bounty "Race a BTC trading bot live for 24 hours"](https://make.fun/bounty/btc-race-24h-20261123-0511): a cbBTC trading bot that races on 1-minute on-chain prices with $1,000 of paper money.

## Strategy

Long only, one position at a time, full size. Designed from the kit's frozen
24h dev window, where BTC rose +3.6% in one concentrated 2-hour rally and
then chopped sideways — fast signals whipsaw badly there (a plain
EMA(8)/EMA(21) cross trades ~76 times and loses ~$115 to fees), so this bot
waits for real breaks and holds them with wide stops:

- **Breakout entry:** the close breaks above the highest close of the last
  30 minutes, while above the 240-minute EMA (long-term uptrend).
- **Dip entry:** the close falls 0.5% below the 30-minute EMA while staying
  above the 240-minute EMA — a dip inside an uptrend.
- **Exit:** the whole position is sold when the close falls 1.5% below the
  best close since entry (trailing stop) or 2% below the entry close (hard
  stop). A dip entry also takes profit at +1.5% over entry; a breakout entry
  has no take-profit and rides the move until the trailing stop fires.

## Local result (dev window)

Grade-local replay on the kit's frozen 24h dev window: **net PnL +$17.52,
5 trades, max drawdown 2.58%** — clears the dev gate (net PnL > $0).

## Layout

- `main.py` — the bot (Python 3.13, standard library only). Speaks
  `agent-fun/bars-replay/v1` on stdin/stdout.
- `vendor/makefun_bars.py` — byte-identical copy of the kit's Python SDK shim.

## Run

```sh
python3 -P -s main.py
```

Deterministic: the same bars always produce the same orders. No network, no
wall clock, no files outside the repo.
