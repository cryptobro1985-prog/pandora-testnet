# HYPE D250 causal stop feasibility: structural-vs-fixed stop and risk budget — 2026-11-22 05:26 UTC

Research only. Frozen D250 unchanged. No orders, no detector retraining, no production change. This is an independent deterministic audit, **not** matched historical execution replay.

## Directly verified source facts
Read on this branch: `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, and `HYPE_D250_MIN_ORDER_RISK_FEASIBILITY_2026-11-22_0434_UTC.md`.
The D250 frozen rule confirms after 250 minutes, with 71 accepted episodes and 67 completed next-local pairs. Historical median structural stop distance from entry was 3.140% (0.25 ATR beyond original extreme). The separately selected frozen adverse-price cut is 1.0% from entry, with 0.15% assumed round-trip fees and no verified fill/slippage. The 1% cut is an **early loss cut**, not a structural invalidation level; its risk of ordinary stop-outs must be measured in event-time replay.

## New analytical reconciliation: stop risk and feasibility
For account equity E, risk budget r, stop price distance d, round-trip cost c and adverse fill gap g, maximum notional is N = E*r/(d+c+g). Apply exchange quantity step by rounding DOWN, never increase risk to satisfy min-notional. This cap assumes full fills and a finite g: actual gap can exceed reserve.

For E=$100, c=0.15%, g=2%, fixed d=1% => total stressed loss fraction 3.15% of notional:
- r=0.25%: N <= $7.9365; r=0.5%: N <= $15.8730.
For the *median observed structural-stop distance* d=3.14% instead, total stressed fraction is 5.29%:
- r=0.25%: N <= $4.7259; r=0.5%: N <= $9.4518.
Thus a hypothetical $10 minimum notional is feasible under the fixed 1% cut at 0.5% risk, but NOT under the median structural stop even at 0.5% risk. The structural distance is a historical median, NOT a trade-specific executable stop. Actual positions require their own causal stop geometry.

Break-even gross move before funding under 0.15% round-trip fee is >0.15% price movement with no additional entry/exit slippage; under 0.20% additional total slippage, >0.35%. These costs disproportionately affect partial exits. The 2% stress reserve is a loss-tail budgeting assumption, NOT a universal fill cost deducted from all winners.

## Geometry and causal restrictions
- LOW -> LONG: original LOW extreme L, entry P>L. Candidate fixed cut P*0.99. Structural stop L - 0.25*ATR14. If structural stop is closer to entry than fixed cut, choose that closer stop; otherwise the frozen 1% early cut applies. Never use a later revised L or future opposite local.
- HIGH -> SHORT: original HIGH extreme H, entry P<H. Candidate fixed cut P*1.01. Structural stop H + 0.25*ATR14. If structural stop is closer, choose it. Stop comparison and tick rounding must be direction-aware.
- Stop triggered on observed tradable price, mark-based liquidation evaluated independently. A successful quantity calculation alone never authorizes an order.
- If the original extreme was revised before D250 or opposite local already confirmed, NO_TRADE.
- Profit-protection overlays previously rejected stay rejected until independently validated.

## New falsifiable replay requirements
1. Recover immutable 67 UTC entry/exit event ledger, plus 4 unmatched accepted episodes' status; do not equate 71 accepted with 71 executable round trips.
2. Join per-trade mark/trades/book and exchange filters with explicit missingness. For 1% early cut, record which of the 22 modeled stop exits would actually have filled, including gaps and adverse selection.
3. On SAME 67 trades, compare original 3x/5x baseline unchanged, fixed 1% cut with 0.25/0.5% stop-risk sizing, and structural-stop sizing. Do not attribute performance to risk control without a matched path.
4. Report rejected-minimum-order trades as NO_TRADE, not silently omit from denominator. Use sequential equity and mark-to-market excursions, no capital reuse.
5. Separate LOW and HIGH entry delays, pre-confirmation adverse excursions, stop hits, funding and fill outcomes; hold-to-opposite-local is causal K2 confirmation, not the oracle opposite extreme.
6. Only challenge staged entry / profit lock on development, freeze and test on genuinely unseen chronological forward. The earlier flow+MFE, K0/K1 and pyramiding overlays remain rejected.

## Evidence status
New result is a **quantified trade-off**: using the median structural stop instead of the fixed 1% cut shrinks conservative permissible notional by 40.47% under the stated gap/fee assumptions. This is not a realized performance improvement. No new real fills, monthly net equity, MTM DD, liquidation count or independent forward performance established. Missing: immutable per-trade UTC ledger, event-time trade/mark/orderbook archives and historical exchange lot rules.
