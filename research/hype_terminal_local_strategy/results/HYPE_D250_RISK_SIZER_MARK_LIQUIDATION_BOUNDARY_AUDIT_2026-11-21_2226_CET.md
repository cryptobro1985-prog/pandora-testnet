# HYPE D250 — stop vs liquidation boundary audit (2026-11-21 22:26 CET)

## Scope
Inspected the existing frozen-D250 conservative sizer `d250_conservative_stop_risk_sizer_20261121.py` and preceding sizing checkpoint. No retraining, no production edits, no live orders. This checkpoint is an executable-logic audit with reproducible algebraic counterexamples, **not** historical trade replay.

## New finding: liquidation-price validation is not sufficient
The sizer checks `adverse + adverse_gap_fraction < liquidation_distance`, treating a supplied liquidation price as an authenticated scalar. It does not check the source timestamp, account/margin mode, maintenance margin tier, mark-price trigger basis, or whether liquidation distance changes as equity and other positions move. Therefore a `SIZED` result **cannot** be interpreted as a verified liquidation-safe entry. Treat it as `PROVISIONAL` until exchange-state provenance and a mark-price tape exist.

### Reproducible synthetic boundary cases
Using $100 equity, LONG entry 100, stop 99, round-trip cost 0.0015, gap 0.02, risk 0.005, no other risk, 25x, 20% margin cap:

- Liquidation price 97.00: liquidation distance = 3.00%, stress stop excursion = 3.00%; function correctly BLOCKS at equality.
- Liquidation price 96.99: liquidation distance = 3.01%, stress stop excursion = 3.00%; function SIZES ~$15.8730 notional. **Only 1 basis point of entry price separates the stressed stop from the assumed liquidation boundary**, with no extra mark/basis or model uncertainty buffer.
- Liquidation price 95.00: distance 5.00%, function SIZES ~$15.8730. This remains hypothetical unless sourced from the actual account state.

SHORT symmetry: entry 100, stop 101, liquidation 103.00 => BLOCK; liquidation 103.01 => SIZED, again with just 1 bp nominal clearance.

### Required next validation before replay results can be called safe
1. Keep frozen D250 and baseline unchanged. Add a separate research-only provenance gate requiring exchange timestamp, mark price, margin mode, maintenance tier, position inventory, and liquidation-price calculation source.
2. Require an explicit, predeclared positive clearance buffer beyond stress stop excursion; reject stale or missing mark/basis inputs. Do not tune buffer on held-out trades.
3. Compute dynamic liquidation distance and mark-to-market equity at every event; account for other open positions and margin consumption. Never infer zero liquidations from static liquidation price alone.
4. Recover exact original 67-row UTC manifest and trade-matched public trades, mark/funding and L50; report missingness by month and side, and do not fabricate fills.
5. Replay original baseline and low-risk alternatives on the same causal event sequence, with identical fees/funding/slippage assumptions; keep rejected MFE overlays rejected absent independent forward evidence.

## Status
The above is a concrete new boundary audit, not an empirical trade performance result. No authenticated 67-trade event replay, monthly net equity, MTM DD, MFE protection or zero-liquidation claim. The original sizing code was deliberately not changed in this iteration, to avoid altering historical baseline and to preserve auditability.
