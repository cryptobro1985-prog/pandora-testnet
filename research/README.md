# Local/Pump execution review

`baseline_local_v5.py` freezes source commit `5d0c60b` for reproducible comparisons.
`review_replay.py` reads `analysis_data/candles/{SYMBOL}_{1h,15m,1m}.json` and a
`candles_manifest.json` from the working directory. Run it from the directory
containing that dataset. `pump_review.py` additionally uses `trade_tables.json`
and the recorded symbols' `{SYMBOL}_pump_1m.json` histories.

The comparisons are exploratory one-minute candle proxies. They use causal H1
confirmation, observed minute prices, configured fees and a slippage sensitivity.
They do not reconstruct intrabar ticks, executed flow, actual fills, shared
portfolio reservations, funding, or exchange liquidations. Training/test windows
are chronological; additional variants inspected after the first results are
not an untouched holdout. Percentage sums are per-entry notional contributions,
not account ROI. The current flow-confirmed caterpillar has separate behavioral
regressions and still requires forward evaluation.
