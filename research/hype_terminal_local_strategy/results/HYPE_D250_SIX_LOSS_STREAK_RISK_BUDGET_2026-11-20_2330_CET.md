# D250: six-loss-streak risk-budget stress reconciliation — 2026-11-20 23:30 CET
Research-only; arithmetic stress test, NOT event replay or measured Bybit execution.

## Frozen evidence (read from existing branch)
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md: D250 thresholds remain unchanged, 71/71 first accepted on historical periods, 67 with finalized opposite local; median MFE giveback 61.2%.
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md: 67 modeled sequential trades, **six consecutive losing trades maximum**, 22 stop cuts, 0.15% round-trip cost, 3x closed-equity DD 18.56%, 5x closed-equity DD 29.36%. These are not observed executable fills or MTM DD.
- HYPE_D250_EXPOSURE_RISK_INCOMPATIBILITY_2026-11-20_2230_CET.md: original 3x/5x exposure violates conservative stop-risk mandate.

## New computation: six consecutive adverse exits
Assume a 1.00% stop distance + 0.15% round-trip cost + **illustrative** 2.00% execution-gap reserve = 3.15% of notional at stress. Size notional/equity x = target risk / 0.0315. Without the gap, normal stopped loss = x * 0.0115. Compound six sequential losses as 1-(1-loss)^6. Ignore funding and changing margin constraints; gap reserve is not a guaranteed cap.

| Initial stop-risk budget | Exposure x | Normal stopped equity loss | Six normal stops compound DD | Stress stop equity loss | Six stress stops compound DD |
|---|---:|---:|---:|---:|---:|
| 0.50% | 0.158730x | 0.1825% | 1.0903% | 0.5000% | 2.9627% |
| 0.25% | 0.079365x | 0.0913% | 0.5464% | 0.2500% | 1.4907% |

At 0.50% risk the nominal stress budget loses ~2.96% equity after six sequential stressed stops, *if* each exit fits inside the assumed 2% gap reserve. Any larger gap, funding or failure to execute can exceed this; this is not a hard bound or proof of zero liquidations. Compare original six modeled worst-loss stops at 3x: 1-(1-0.0345)^6 = 18.995%; at 5x: 1-(1-0.0575)^6 = 29.905%. Those are hypothetical repeated worst losses, not observed loss-streak DD.

## Decision
Keep the original 67-trade frozen baseline unchanged. Treat 0.25–0.5% sizing as **candidate only**, with total concurrent stop-risk <=1% equity. A low-risk model must be rejected on any unverified instrument minimum notional, stale Mark Price, missing quote/depth, unverified liquidation buffer, funding, or impossible UTC chronology. Never promote a trailing/profit-lock overlay based on these calculations.

## Missing evidence for promotion
Matched per-trade UTC bid/ask + L50 depth, Mark Price tape continuity, instrument minQty/qtyStep/minNotional, funding, fee tier, liquidation maintenance margin and independent forward fills. No monthly equity, MTM DD, real fills, or MFE protection claims can be inferred from this arithmetic.
