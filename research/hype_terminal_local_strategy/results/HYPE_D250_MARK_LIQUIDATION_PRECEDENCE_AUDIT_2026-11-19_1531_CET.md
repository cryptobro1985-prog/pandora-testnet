# HYPE D250 — mark-price liquidation precedence audit
Date: 2026-11-19 15:31 CET. Research-only checkpoint; no real orders or detector training.

## Source audit
Read frozen H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, quote_event_stop_replay_research.py, d250_trade_replay_manifest_gate.py, trade_event_coverage_gate_20261116.py in the requested branch. Frozen D250 thresholds unchanged: rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, flow15 < 0.4504731635235635. LOW->LONG, HIGH->SHORT. No new detector fitting.

## New concrete code-path finding
quote_event_stop_replay_research.py validates e.mark as finite positive but never uses it to test liquidation or stop-trigger provenance; it returns liquidation_verified=False. The notional formula equity*risk_fraction/(stop_pct+roundtrip_cost_fraction) does not enforce leverage/margin availability or aggregate open risk. Therefore a price-stop outcome can be reported in a hypothetical quote replay even when a mark-price margin event may have happened earlier. d250_trade_replay_manifest_gate.py checks mark_coverage COMPLETE as a label, not mark-price path or liquidation thresholds. trade_event_coverage_gate_20261116.py explicitly returns liquidations=None even when coverage passes.

## Deterministic event-order counterexample (NOT Bybit history)
Equity $100, LONG entry $100, instrument leverage 25x, hypothetical isolated maintenance margin 0.5% of notional, zero fees/funding for the illustrative liquidation-price approximation. Approximate liquidation boundary P_liq = 100*(1 - 1/25 + 0.005) = $96.50; actual Bybit liquidation depends on position tier, margin, fees, mark price, risk limits and exchange rules. Stop trigger is configured at $99 using last price. At t=1: last $99.40, bid $99.35, mark $96.40. At t=2: last $98.90, bid $98.80, mark $96.20. A last-trigger-only replay would label STOP at t=2; the illustrative mark threshold is already breached at t=1. This is a **possible liquidation-first ordering**, not a verified exchange liquidation. Both the last and mark streams need timestamps and exchange-specific margin accounting to adjudicate.

SHORT symmetry: illustrative P_liq = 100*(1 + 1/25 - 0.005) = $103.50; last-trigger stop $101. At t=1 last $100.60, ask $100.65, mark $103.60; at t=2 last $101.20, ask $101.30, mark $103.80. Again the hypothetical mark threshold precedes last-price stop activation.

## Acceptance criteria for the 67-trade matched replay
1. Preserve original trade IDs and UTC entry/exit eligibility. Confirm entry strictly after frozen D250 signal and actual H1 confirmation, reject same-side invalidations.
2. For each event in timestamp order, update mark-price equity, margin tier, maintenance margin, liquidation buffer, trigger-source price, and executable L50 book; distinguish order activation from fill.
3. If a mark margin threshold is crossed before a verified stop fill, classify LIQUIDATION_POSSIBLE / UNKNOWN rather than STOP_SUCCESS; do not assert zero liquidations.
4. If mark/last/L50 timestamps do not resolve order, classify ORDER_UNRESOLVED. No interpolated candles or forward quotes.
5. Use 0.25%-0.5% per-trade planned stop risk and <=1% concurrent aggregate stop risk, with separate gap/slippage stress and available margin cap.
6. Compare original baseline, risk-sized mandatory stop, staged entry, and rejected overlays only as negative controls on the identical chronological sample and same fees/funding. Report monthly net equity, MTM and closed DD, fills, stop count, MFE retention, and unseen forward results, or explicitly N/A if evidence missing.

## Outcome
New finding is a verified source-code coverage gap plus two transparent synthetic ordering counterexamples; **zero matched historical executions have been verified in this checkpoint**. No new historical PnL, liquidation count, or MFE claim. This is not evidence that the 67 historical trades were liquidated. Next run should retrieve the actual per-trade event ledger and calculate event-order outcomes; avoid further cosmetic arithmetic-only patches.
