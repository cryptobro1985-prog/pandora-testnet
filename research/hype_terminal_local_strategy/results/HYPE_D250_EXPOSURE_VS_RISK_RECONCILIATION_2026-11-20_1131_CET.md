# HYPE D250 — stop-risk versus fixed exposure, 2026-11-20 11:31 CET

Research-only quantitative consistency checkpoint. Frozen D250 and all existing detector thresholds unchanged. No production changes, orders, or detector retraining.

## Source inspected directly
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: 71/71 historical first signals, 67 finalized next locals; median structural stop distance 3.140%; causal opposite-local exit median MFE giveback 61.2%; rich market features not uniformly available.
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 67 sequential simulated trades; 22 fixed-cut exits; 5x exposure closed DD 29.36%, 3x closed DD 18.56%; 0.15% assumed roundtrip fee. These are not event-level fills or MTM results.
- `independent_risk_reconciliation_20261120.py`: risk-based notional uses stop distance + fee + gap + funding reserve, but reports scenario authorization, not execution verification.

## New independent cross-model reconciliation

For equity E=100 USD, per-trade risk 0.5 USD, assumed 0.15% roundtrip cost, 2% adverse gap reserve, and zero funding *only as a sensitivity scenario*:

| Stop distance | Loss per $1 notional | Risk-limited notional | Equivalent account exposure | Fixed 3x exposure stressed loss | Fixed 5x exposure stressed loss |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1.00% | 3.15% | $15.8730 | 0.1587x | $9.45 (9.45% equity) | $15.75 (15.75% equity) |
| 3.14% | 5.29% | $9.4518 | 0.0945x | $15.87 (15.87% equity) | $26.45 (26.45% equity) |

Formula: allowed notional = min(0.005 E, 0.01 E - existing stop-risk) / (abs(entry-stop)/entry + 0.0015 + 0.02 + funding reserve). 3x and 5x columns are *stress loss at reserved stop-gap*, not realized historical drawdowns. Thus the 3x/5x compounding reports cannot be treated as backtests of a 0.5%-risk implementation. With the 1% stop, the fixed 3x and 5x positions exceed the single-trade risk cap by 18.9x and 31.5x respectively under this scenario.

At 25x instrument leverage, 1%-stop risk-limited $15.873 notional uses ~$0.635 initial margin before exchange requirements, not 20% of equity. Leverage is not a substitute for risk-based notional.

## Important newly identified ambiguity
The 1% adverse cut in the 67-trade baseline is an *assumed adverse-price exit*. The code and aggregate report do not establish whether the adverse crossing was observed in bid/ask or Mark Price, whether the stop filled at the assumed price, or whether Mark Price reached liquidation before fill. The 0.15% roundtrip cost is a model assumption, not verified event-level fee + slippage + funding. Therefore neither the 67-trade baseline nor the above sizing calculation supports a claim of zero liquidations.

## Next reproducible replay gate
Reconstruct the 67 individual trade IDs with UTC local-extreme, K2 confirmation, D250 eligibility, entry, stop, next-opposite K2, and the full intervening timestamped bid/ask/Mark Price/L50/funding path. Require immutable source identifiers and gap audit. Apply unchanged entries and identical paths to baseline and risk-limited alternatives. Reject any trade lacking a causal time chain or necessary execution evidence; report matched coverage and rejected reasons. Separate LONG and SHORT, monthly closed and MTM equity, fee/funding/slippage, stop fills, gap losses, liquidation checks, MFE captured and given back, and unseen forward periods. Keep previously rejected exit overlays rejected until independent forward evidence.

## Result and limitation
This iteration completed a new **quantitative cross-model risk reconciliation** on the saved original studies. It did **not** reconstruct or execute any of the 67 historical event-level trades. No new claim about net return, fills, liquidation count, or MFE protection is warranted.