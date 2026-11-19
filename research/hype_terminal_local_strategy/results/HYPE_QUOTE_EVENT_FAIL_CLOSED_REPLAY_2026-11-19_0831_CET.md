# HYPE quote-event fail-closed replay checkpoint — 2026-11-19 08:31 CET

Scope: frozen D250 only, LOW→LONG / HIGH→SHORT; no detector training, production changes or real orders.

## New concrete implementation
Added `research/hype_terminal_local_strategy/quote_event_stop_replay_research.py` on the existing branch.
This research-only module consumes strictly increasing event timestamps with bid, ask, mark and opposite-confirmation availability. It never reads M1 candle close or full-bar high/low. LONG exits at observed bid; SHORT at observed ask. Stop/confirmation simultaneously present => ORDER_UNRESOLVED. Crossed, invalid or non-monotonic quotes are rejected. Missing exit => OPEN_UNRESOLVED. The fixture includes LONG gap stop, SHORT gap stop, ambiguous ordering and crossed-quote assertions.

## Critical limitations
Quote-only exit is a hypothetical top-of-book execution, **not** a verified fill. It does not establish executable size, latency, L50 depth, partial fills, trigger source, fees/funding actually charged, margin maintenance, liquidation or mark-to-market drawdown. No 67-trade UTC join performed. The self-test is authored but **not executed in this run**. Therefore no new PnL, monthly equity, MTM DD, fills, liquidations, MFE capture or OOS performance claims.

## Causal contract and remaining work
1. Join each frozen D250 trade ID and terminal-local availability timestamp to raw UTC Bybit Public Trades, bid/ask L50, mark and funding. Never fill missing microstructure with zeros.
2. Separate actual order-side trigger from executable quote and depth. Use order latency and partial-fill simulation; flag unavailable fields instead of claiming exact fills.
3. At every event apply stop and opposite confirmation only if order is provable; equal timestamps with unknown sequence stay unresolved.
4. Track MFE only on quotes observed before execution, and account for liquidation risk using mark-price and maintenance-margin parameters.
5. Run original baseline and conservative 0.25–0.5% equity stop-risk variants on the same sequential capital ledger; aggregate planned stop risk <=1% equity. Keep rejected overlays rejected pending independent OOS evidence.
6. Run deterministic fixtures and full chronology / untouched forward before promoting any results.

Frozen entry thresholds remain rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, side-normalized flow15 < 0.4504731635235635, D250. Historical 71/71 first-accepted and 67-trade figures remain historical research claims, not verified execution results.
