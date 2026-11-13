# HYPE stop-before-liquidation feasibility audit — 2026-11-13 19:26 Europe/Stockholm

Research only; NO orders, production changes, detector refit, or claims of tick-level execution.

## Sources read on branch
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md (frozen D250 71/71, 67 completed opposite-local examples, median structural stop 3.14%, median MAE -0.414%, worst observed -1.958%, median MFE giveback 61.2%)
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md (frozen 1% price cut; 22/67 stop exits; 5x closed DD 29.36%; 3x 18.56%; 0.15% round-trip assumed; stop fills NOT tick verified)
- HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md (price-impact control-transfer contract; previously rejected overlays remain rejected)

## New quantitative feasibility diagnostic: stop before liquidation
Isolated-margin first-order approximation only: available initial price-loss buffer = 1/leverage. Reserve assumed maintenance-margin fraction 0.50% of notional, round-trip fee reserve 0.15%, and stress additional stop gap/slippage. Maximum admissible instrument leverage in this **simplified** model:
L_max = 1 / (stop_distance + gap + 0.005 + 0.0015).
This is a *necessary screening bound*, not an exchange liquidation-price calculation; actual Bybit maintenance tiers, funding, mark-vs-last divergence, position mode, and collateral may differ.

| Stop distance | Extra gap | Loss+reserve fraction | Screening L_max | 25x isolated screen |
| --- | --- | --- | --- | --- |
| 1.00% | 0.00% | 1.65% | 60.61x | pass approximate |
| 1.00% | 1.00% | 2.65% | 37.74x | pass approximate |
| 1.00% | 2.00% | 3.65% | 27.40x | pass narrowly |
| 1.00% | 2.50% | 4.15% | 24.10x | fail |
| 3.14% | 0.00% | 3.79% | 26.39x | pass narrowly |
| 3.14% | 0.50% | 4.29% | 23.31x | fail |
| 3.14% | 1.00% | 4.79% | 20.88x | fail |
| 3.14% | 2.00% | 5.79% | 17.27x | fail |

## Distinct account risk vs liquidation risk
At a fixed 1% stop + 1% gap + 0.15% fee, a conservative approximate notional/equity cap is:
0.25% risk -> 0.0025/0.0215 = 0.11628x; 0.50% risk -> 0.005/0.0215 = 0.23256x.
At median structural 3.14% stop, same 1% gap/fee: 0.25% -> 0.06039x; 0.50% -> 0.12077x.
These account-risk caps do not ensure isolated liquidation safety at a chosen instrument leverage. SHORT execution-side fee exactness and funding need per-trade replay.

## Causal trading contract for matched replay
1. LOW -> LONG and HIGH -> SHORT only at timestamp of *first* frozen acceptance, never the retrospective extreme; invalidate if same-side extreme renews or opposite local is already K2-confirmed.
2. Simulate original unchanged 1%-cut + opposite-K2 exit baseline FIRST. Record each accepted timestamp and entry side, order book state, mark/index, actual next trade, fees, funding, stop trigger and fill; missing L50/OI/liquidations = missing, not zero.
3. Compare on identical immutable 67 event IDs (or explicitly report subset coverage): baseline exposure, 0.25% and 0.5% stop-risk sized exposure, staged entry, and break-even/profit-lock challenger. Reject overlays until independent unseen evidence improves net/DD without capital reuse.
4. Report separately for LOW/LONG and HIGH/SHORT: pre-confirmation adverse excursion, entry delay, gap/slippage, realized stop-fill, mark-to-market and closed DD, liquidations, MFE captured/given back, monthly net and true unseen-forward.
5. Exit-control-transfer challenger requires sustained opposite price-impact efficiency AND weakening own-side efficiency, not opposite raw volume or hindsight exact extreme. Previously rejected fixed trails, MFI+flow exits, K0/K1 overlays remain rejected.

## Coverage/limitations and next dependency
No per-trade timestamped execution files or L50 replay were fetched in this checkpoint. Therefore this is a NEW deterministic liquidation-feasibility matrix, **not** a matched 67-trade replay, and it cannot establish monthly net equity, fills, mark-to-market DD, or zero liquidations. Do not promote to live trading. Next iteration should locate exact 67 event IDs and corresponding rich M1 partitions before asserting execution outcomes.
