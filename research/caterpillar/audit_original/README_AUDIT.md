# Caterpillar 6H — Codex audit package

Purpose: audit an event-driven PAPER/research strategy before any live trading integration.

Fixed universe only:
ZEC, HYPE, NEAR, SOL, ENA, 1000PEPE, DOGE, SUI, AAVE, WLD.

Core rules:
- confirmed local high => short regime; confirmed local low => long regime;
- executed BUY/SELL flow + price response decide entry/hold/exit/re-entry;
- event-driven, not a 5m/15m timer strategy;
- detect absorption: large aggressor flow without corresponding price progress;
- MFE/MAE tracked continuously after entry;
- normal exit on genuine control transfer; structural opposite local invalidates old regime;
- re-entry allowed after flow exit if original structure remains valid and control returns;
- no private Bybit API, no order placement, no real trading.

Audit priorities for Codex:
1. Look-ahead / causality violations in local detection.
2. Whether event clusters overlap too heavily and create false confidence.
3. Entry/exit churn and re-entry loops.
4. MFE capture/giveback behavior and whether exits are too early/late.
5. Robustness of adaptive robust-z/MAD metrics across all 10 tokens.
6. Price-response/absorption logic correctness.
7. Failure behavior on stale, duplicated, reordered, bursty or sparse trade events.
8. Signal ranking design if several tokens trigger simultaneously.
9. Fees/slippage/funding are intentionally absent from this research skeleton; identify where they must enter before PnL claims.
10. Recommend changes only when supported by causal reasoning; do not optimize to one six-hour sample.

Expected feed contract:
ResearchEngine.on_trade(symbol, price, notional, side, ts)
side = +1 buyer aggressor, -1 seller aggressor.
