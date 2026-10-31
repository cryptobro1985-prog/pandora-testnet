# PANDORA Strategy 1 — BYBIT PAPER restoration specification (2026-10-31)

## Historical reference
Reference commit: 0ad29b4944a572aa78658d250234a4304559e1c2. On 2026-10-29 20:59 UTC Neon local_v12_trade_history closed four SHORT positions (ETH/LIT/NEAR/BTC) for a combined +429.21 USD PAPER PnL, reason portfolio_emergency_profit_take. All were H1 LOCAL_HIGH and 25x. This does NOT establish that the portfolio profit-taking threshold can be inferred from trade reason alone.
Historical persisted feature keys: profit_lock_armed=true, profit_lock_mode=mfe_persistent_m15_confirmation, mfe_roe_pct, profit_lock_stop, profit_lock_floor_move, required_retrace, mfe_giveback_move, execution_interval=15m.
This historical implementation includes M15; current user specification supersedes it with M1/M3/M5, so no implicit reintroduction of M15 is authorized.

## Requested ten Bybit PAPER symbols
INIT, NEAR, BTC, SOL, ETH, LIT, HYPE, ZEC, TAO, GRASS (confirmed from app.py LOCAL_EXPERIMENT_SYMBOLS on main 2026-10-31).

## Required behavior for integration and verification
- Confirmed causal H1 Local High = SHORT ONLY; confirmed H1 Local Low = LONG ONLY; opposite H1 confirmed pivot closes old direction regardless of PnL. Never use future candles.
- Fresh Bybit Public Trades executed buyer/seller volume by side; never fabricate fresh flow from stale data.
- Maintain best observed favorable price / MFE for each live PAPER position, and persist across restart.
- When opposite executed side takes control and favorable move recoils, exit per causal flow-based rules with modeled execution costs. Record separate MFE, giveback, exit reason, realized PnL.
- After exit, wait for real counter-flow/pullback, then resumed H1-aligned executed flow, and re-enter in SAME H1 direction; repeat until opposite confirmed H1 pivot. Re-entry cannot occur in same stale observed window.
- Margin 20% of current equity per position, target 25x leverage, account exposure guard, startup equity 500 USD, PAPER ONLY, no real account keys or exchange order placement.
- No additional MACD/EMA/MFI/M15 filters; document every other gate and blocked-entry reason. Do not arbitrarily erase losses, positions, or actual trade history.
- Data and state isolation for testing is mandatory to avoid two concurrent engines acquiring same Neon lease or writing to same PAPER account.

## Mandatory gate before production monitor cutover
1. Compare historical reference implementation against current v17 executed flow code and actual 2026-10-29 Neon features.
2. Add unit tests for H1 pivot confirmation, fresh flow, MFE max/persistence, profit giveback exit, opposite-pivot emergency closure, repeated pullback/re-entry, and restart.
3. Run event-level replay without lookahead; separate hypothetical replay PnL from executed PAPER trades.
4. Deploy to a separately isolated test instance (or single-engine maintenance cutover) and verify working health, feed freshness, durable paper orders, monitor and logs.
5. Collect a full 12-hour observation window and publish hourly counts, PnL and MFE giveback; do not claim a completed test before evidence exists.

## Findings 2026-10-31
The current local_caterpillar.py file is byte-identical on restored branch and main, carrying POLICY local_h1_m1_m3_m5_executed_flow_v17_no_m15. Merely deploying the restored branch would NOT restore the historical portfolio profit-taking mechanism or reliably repair no-trade state. Current Render service pandora-testnet-monitor uses main and autoDeploy=yes. No code change to main or Render deployment was performed in this restoration note.
