# HYPE D250 entry-side slippage and stop-gap sizing audit — 2026-11-19 03:29 CET

Research only. Frozen D250 unchanged. No orders, training, or live-performance claims.

## New issue examined
Prior stop-gap budgets focused on exit slippage. An aggressive LONG after LOW is bought at ask, and SHORT after HIGH is sold at bid. If the reference entry is mid/last, entry-side slippage must be reserved **in addition** to stop gap, fees, and funding. Counting it only in the exit gap understates possible stop loss. This is a hypothetical stress budget, NOT calibrated to Bybit HYPE depth.

## Reproducible calculation
Equity E=100 USD. Adverse price move from actual filled entry to stop = 1.00%. Round-trip fees reserve 0.15% notional; funding reserve 0.09%; entry-side slippage versus reference 0.25%; stop gap / exit slippage reserve 3.00%. Total stress loss fraction of notional = 1.00%+0.15%+0.09%+0.25%+3.00% = 4.49%.

Formula: max_notional = equity * per_trade_risk / 0.0449.
- At 0.25% equity risk: $5.5679 notional; worst budgeted loss $0.25.
- At 0.50% equity risk: $11.1359 notional; worst budgeted loss $0.50.
- Two 0.50%-risk trades consume the entire 1% total stop-risk budget **before any correlated stress above assumptions**.
- With 25x instrument leverage, indicative initial margins would be $0.2227 and $0.4454, respectively. This is arithmetic, not permission to use 25x: maintenance margin, mark-price liquidation distance, exchange min-notional, tick/step rounding and isolated/cross behavior must be verified before execution.

Important convention: if stop distance is already measured from the actual fill, do NOT double-count entry slippage; use a reference-price-to-fill convention consistently across all variants. The above intentionally budgets reference-entry uncertainty separately.

## Causal execution replay requirements
1. LOW->LONG: timestamped D250 confirmed signal, ask/L50 sweep at arrival, fill VWAP, sell-to-bid stop sweep; HIGH->SHORT: bid/L50 sell sweep and buy-to-ask stop sweep.
2. Reject if opposite H1 local was confirmed before fill, or if same-side extension invalidated local; stop must execute before liquidation mark threshold including gap.
3. Independently match UTC public trades, book snapshots and mark/funding; gaps are UNKNOWN, never zero-imputed.
4. Compare baseline and risk-based variants on identical chronologically ordered trades, with one shared equity ledger, no double-use of capital; calculate both MTM and closed DD.
5. No MFE overlay promotion until genuinely unseen forward evidence improves net risk-adjusted performance.

## Status
This checkpoint is an incremental arithmetic stress audit, not matched per-trade execution replay. The 67-trade record remains unverified at bid/ask, stop gaps, mark liquidation and MFE. No monthly net equity, liquidation count or forward claim is generated.
