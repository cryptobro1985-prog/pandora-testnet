# HYPE D250 — risk-normalized baseline comparability checkpoint
Date: 2026-11-21 13:34 CET. Research only; no orders, no detector retraining.

## Direct source inspection
Read on target branch: HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md, stop_geometry_risk_gate_20261121.py, entry_execution_manifest_gate_20261119.py, finite_execution_manifest_gate_20261121.py.

## New reproducible numerical reconciliation
Frozen 67-trade result is **fixed exposure**, not fixed stop-risk. At the frozen 1% price stop and 0.15% round-trip costs (ignoring any gap), nominal exposure 3x implies stop loss 3*(0.01+0.0015)=3.45% equity; 5x implies 5.75%. This exactly matches the report's worst modeled losses (-3.45%, -5.75%). These are NOT 0.25–0.5% risk trades.

Conservative sizing formula in current stop_geometry_risk_gate_20261121.py:
 exposure/equity = risk_fraction/(stop_distance + roundtrip_cost + gap_reserve).
For 1% adverse cut, 0.15% costs, and *hypothetical* 2% gap reserve:
- 0.25% equity risk -> 0.0025/0.0315 = 0.079365079x exposure;
- 0.50% equity risk -> 0.005/0.0315 = 0.158730159x exposure;
- at 25x instrument leverage, initial margin fractions are ~0.31746% and ~0.63492% of equity.
The fixed 3x and 5x baseline exposures are respectively 18.9x and 31.5x the conservative 0.5%-risk exposure, **not comparable by raw terminal equity**.

The 2% gap reserve is a sensitivity assumption, NOT empirically calibrated from HYPE order book / stop execution. A risk budget is not a loss guarantee under gaps.

## What this does and does not establish
This calculation reconciles a specific discrepancy in previously preserved frozen research without modifying the frozen baseline. It is deterministic arithmetic; no real fill replay and no new OOS outcome is claimed. Reported $100->$531.16 / 18.56% closed DD for 3x and $100->$1308.86 / 29.36% closed DD for 5x cannot be relabeled as risk-limited outcomes. A 0.25%-0.5% equity-risk result must be re-simulated sequentially with dynamic equity and all trade timestamps, not estimated by scaling final compound return.

## Required matched replay
Use the exact same frozen 67 trade IDs and chronological signals, separately LOW->LONG and HIGH->SHORT. Match real UTC quotes/trades/mark, stop triggers, fill volume, L50 depth, fees/funding, latency, and liquidation margin. If unavailable mark missing, never synthesize or zero-impute. At each fill reserve stop-risk, prevent overlapping capital reuse, record monthly realized and MTM equity, stop-gap distribution, liquidations, MFE given back and forward segment. Compare unchanged fixed 3x/5x baselines against risk-normalized 0.25%/0.5%, staged entry and optional profit protection only on identical inputs. Previously rejected overlays stay rejected absent independent forward evidence.

## Minimal reproduction (Python)
```python
assert abs(3*(.01+.0015)-.0345)<1e-12
assert abs(5*(.01+.0015)-.0575)<1e-12
assert abs(.0025/(.01+.0015+.02)-.07936507936507936)<1e-12
assert abs(.005/(.01+.0015+.02)-.15873015873015872)<1e-12
assert abs(3/(.005/.0315)-18.9)<1e-12
assert abs(5/(.005/.0315)-31.5)<1e-12
```

## Verdict
Risk comparability issue confirmed from existing code and frozen reports. No verified historical execution replay in this checkpoint; no verified liquidations, monthly net return, or MTM DD. No production changes.
