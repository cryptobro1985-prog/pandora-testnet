# HYPE post-local execution: mark/stop/liquidation precedence screen — 2026-11-16 12:40 CET

Research only. New executable module: `liquidation_precedence_gate_20261116.py`. Run locally with Python 3; synthetic assertions passed for LONG and SHORT. No orders or production changes.

## Source reconciliation
Read original `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, `HYPE_ISOLATED_MARGIN_GAP_FEASIBILITY_2026-11-16_1140_CET.md`, and `stop_risk_budget_replay_20261116.py` in the existing research branch. Original frozen D250 and 1% adverse-price cut untouched. The 67-trade result is a sequential model, not verified tick/mark replay.

## New stress calculation (illustrative assumptions, NOT Bybit observed)
For isolated 25x leverage, initial margin / notional = 4.0%. Assume maintenance margin 0.5% notional, fee buffer 0.2% and adverse mark-vs-last divergence 0.3%. The first-order price-move buffer is 4.0%-0.5%-0.2%=3.3%. A 1% stop plus 0.3% adverse mark divergence corresponds to a 1.3% scenario mark move, inside that approximate buffer. With 5% additional stop gap, scenario mark move = 6.3%, exceeding the 3.3% buffer by 3.0 percentage points. Both LOW->LONG and HIGH->SHORT were checked independently with symmetric hypothetical inputs. This is NOT proof of a liquidation or of a safe stop: exact Bybit tier, mark index, liquidation fees, isolated/cross mode, collateral and event order are absent.

Fail-closed statuses: UNKNOWN_MAINTENANCE_MARGIN when tier missing; PRECEDENCE_UNRESOLVED when stressed mark move reaches the approximate buffer; BUFFER_IN_THIS_SCENARIO otherwise. The function always reports historical liquidation count UNKNOWN, never zero. Exact Bybit liquidation engine is intentionally not impersonated.

## Replay blocker
Need each of the 67 individual entry/exit timestamps and prices, D250 confirmation timestamps, acknowledged protective order, trade/mark price sequence, maintenance-tier and account margin mode, stop trigger type, fills and fees/funding. M1 OHLC cannot establish within-bar ordering. Search for real rich Public Trades/CVD/L50/liquidation/OI archives must be followed by matching timestamp windows before performance metrics can be produced.

## Outcomes and governance
Synthetic checks: 4 directional scenarios passed locally. Matched historical executions newly verified: 0. Monthly net equity, MTM DD, fill count, stop count, liquidation count, MFE captured/given back and independent forward: UNKNOWN. Do not promote previously rejected tight trails, K0/K1 exits or pyramiding. Keep baseline untouched and compare only after event-matched same-sample replay with risk 0.25%-0.5% equity/trade and total stop-risk <=1%. No retraining, no new branch, no real orders.
