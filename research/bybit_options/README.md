# PANDORA Bybit Options — Gamma Burst Research

Research-only option engine for **Bybit only**. It is intentionally isolated from HYPE production/live code.

## Objective

Learn whether a reproducible edge exists in buying convexity before large BTC/ETH/SOL moves. The first strategy family is **Gamma Burst Directional**: buy a CALL or PUT with bounded loss (premium paid) when Bybit underlying flow, liquidations, book imbalance and short momentum agree, while the option has acceptable spread/liquidity and useful gamma/theta geometry.

This repository does **not** promise fixed daily returns. A model is promoted only on forward evidence after costs. No real order placement is implemented here.

## Data contract

Public Bybit-only data:

- Options instruments: symbol, option type, expiry, lot/tick rules.
- Full option ticker surface: bid/ask, bid/ask/mark IV, mark/underlying price, OI, volume, delta/gamma/vega/theta.
- L25 option order book for top candidates.
- Underlying BTCUSDT/ETHUSDT/SOLUSDT: recent trades, L50 book, ticker/OI/funding, 5m OI history.
- Real-time underlying public trades and allLiquidation are retained in the Render relay cache and exposed as recent causal context.

The initial research collector deliberately uses a Render relay + REST snapshots for reproducibility and to avoid GitHub-runner regional REST blocks. Later research can add direct option WebSocket capture on the relay.

## Outputs

Each capture segment writes:

- RUN_MANIFEST.json
- surfaces.jsonl.gz — periodic full option surfaces + underlying context
- candidates.jsonl.gz — top scored near-expiry candidates
- signals.jsonl.gz — paper-only CALL/PUT buy signals
- errors.jsonl.gz
- SUMMARY.json

verify.py fails closed if non-paper actions appear.

## Safety invariant

paper_only=true, allow_naked_short=false. The system never stores an API key, never authenticates to trading endpoints, and never creates a Bybit order.

## Promotion path

1. Capture and verify.
2. Label each signal at 1m/3m/5m/15m/30m/1h/3h/6h/expiry using executable bid/ask, not only mark.
3. Measure premium-return MFE/MAE, time-to-MFE, slippage/spread, IV expansion/contraction and underlying move.
4. Train champion/challenger without future leakage.
5. Require positive forward expectancy after estimated fees/slippage and acceptable drawdown.
6. Only then design Telegram notifications. Real execution remains a separate explicit step.
