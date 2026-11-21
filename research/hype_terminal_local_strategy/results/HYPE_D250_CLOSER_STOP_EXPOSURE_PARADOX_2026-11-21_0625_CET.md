# HYPE D250 — closer-stop exposure paradox / research checkpoint
Date: 2026-11-21 06:25 CET. Research only; no orders, no detector retraining, no production changes.

## Inputs verified in this branch
- `stop_geometry_risk_gate_20261121.py`: stop = max(entry*0.99, local-0.25*ATR) for LONG; min(entry*1.01, local+0.25*ATR) for SHORT. Exposure = risk_budget / (stop_distance + roundtrip_cost + gap_reserve). Missing liquidation price returns PAPER_ONLY_UNVERIFIED_LIQUIDATION. No account-wide simultaneous-risk state.
- Frozen `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 1% adverse cut or closer structural stop; 0.15% assumed round-trip costs; 67 sequential simulated trades, not validated fill replay.
- Frozen `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: D250 entries, 71/71 true-first on sampled history; 67 finalized opposite locals; late-Aug weakness and 61.2% median MFE giveback. Frozen thresholds unchanged.

## New reproducible scenario calculation
Let equity E=100, per-trade planned risk b=0.005, roundtrip cost c=0.0015, gap allowance g=0.02. The gate computes N/E = b/(d+c+g), with d the stop price distance from entry. Loss fraction under a realized additional adverse gap x is (N/E)*(d+c+x). This is a *scenario*, not Bybit historical fills.

| Side | d | N/E | loss if x=0 | loss if x=0.02 | loss if x=0.04 |
|---|---:|---:|---:|---:|---:|
| LOW -> LONG, structural nearer | 0.50% | 0.188679x | 0.12264% | 0.50000% | 0.87736% |
| LOW -> LONG, frozen 1% | 1.00% | 0.158730x | 0.18254% | 0.50000% | 0.81746% |
| HIGH -> SHORT, structural nearer | 0.50% | 0.188679x | 0.12264% | 0.50000% | 0.87736% |
| HIGH -> SHORT, frozen 1% | 1.00% | 0.158730x | 0.18254% | 0.50000% | 0.81746% |

Formula can be reproduced with: `python -c "b=.005;c=.0015;g=.02;[(print(d,b/(d+c+g),[(b/(d+c+g))*(d+c+x) for x in (0,.02,.04)])) for d in (.005,.01)]"`

## Finding
The closer 0.5% structural stop *increases* allowed notional by 18.87% compared with a 1% stop, despite having no demonstrated higher fill reliability. When adverse gap exceeds the fixed allowance (4% example), its loss exceeds the 1% stop variant. This is not proof the tighter stop is worse historically; it is an exposure/stop-geometry sensitivity that must be measured with matched fills, spread and latency. The 2% gap allowance dominates the nominal stop distance and is a modeling assumption, not an empirically validated tail bound.

## Replay gates / no promotion
1. Match 67 original entry IDs and UTC timestamps to real tick/Mark Price, best bid/ask, L50, OI/liquidations/funding where genuinely present. Distinguish unavailable from zero; report per-trade coverage.
2. Run identical entry times and cost model with frozen baseline and alternatives, comparing LONG/SHORT separately; for nearer stop compare both unchanged notional and risk-resized notional to isolate the sizing effect.
3. Stop-market trigger and execution must be distinct; stop and MFE intrabar ordering unresolved without event timestamps. No verified tape -> UNRESOLVED, not a win/no-stop.
4. Track aggregate active stop-risk <=1% of equity, margin use, maintenance margin, liquidation distance, capital occupancy, mark-to-market DD, funding, fees and no double-use of capital.
5. Treat 0.25-0.5% per-trade risk as a *budget under specified gap assumptions*, never guaranteed maximum realized loss. No live deployment.
6. Preserve previously rejected MFE overlays as rejected. No forward result is claimed here.

## Status
Completed code inspection and deterministic quantitative sensitivity calculation. No new historical matched-fill replay, monthly net equity, MTM DD, fill count or liquidation count established. Original frozen artifacts unchanged.
