# D250 stop geometry: admissibility of closer-stop test — 2026-11-21 14:33 CET

Research only. No trading, retraining, production changes or inferred execution fills.

## Source and frozen invariants
Read directly on the target branch:
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: D250 rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; flow15 < 0.4504731635235635; no same-side extreme or already-confirmed opposite local.
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 1% adverse price cut, 0.15% round-trip assumed cost; 67 historical sequential simulated trades, not execution verified.
- `stop_geometry_risk_gate_20261121.py`: stop = closer of 1% cut and original local ±0.25 ATR.
- `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`: direction-specific control transfer, not raw counterflow.

## New reproducible geometry audit
Let a = ATR_H1 / entry_price and r = abs(entry-original_local)/ATR_H1. Under the frozen D250 condition r > 2.0840049433824706. Structural stop distance as a fraction of entry is exactly (r+0.25)*a, for either side, when ATR is denominated in price units.

The structural stop is closer than the 1% fixed cut ONLY if
`(r+0.25)*a < 0.01`.
Since r > 2.0840049433824706, this requires
`a < 0.01/2.3340049433824706 = ~0.00428448`, i.e. ATR/entry < ~0.42845%. This is necessary, not sufficient; the actual r must be checked.

The existing module's synthetic closer-stop case LONG entry=100, original_local=99.6, ATR=0.4 has r=1.0, which **fails frozen D250 rev_atr > 2.084**. It is a valid unit test of the standalone stop function but **not a valid D250 strategy episode**. The earlier comparison of closer structural stops cannot be extrapolated to D250 trades without checking the frozen entry gate and actual historical ATR.

Two analytical mirrored D250-eligible boundary examples, assuming other frozen filters pass (NOT observed Bybit trades):
- LONG entry=100, original LOW=99.1, ATR=0.4: r=2.25; structural stop 99.0 (1.00%); fixed stop 99.0 (1.00%).
- SHORT entry=100, original HIGH=100.9, ATR=0.4: r=2.25; structural stop 101.0 (1.00%); fixed stop 101.0 (1.00%).
- LONG entry=100, LOW=99.2, ATR=0.35: r=2.285714; structural stop 99.1125 (0.8875%); closer than 1% cut.
- SHORT entry=100, HIGH=100.8, ATR=0.35: r=2.285714; structural stop 100.8875 (0.8875%); closer than 1% cut.

## Cost-aware sizing sensitivity, scenario only
For assumed round-trip cost 0.15% of notional, reserved adverse gap 2% and equity stop-risk 0.5%, exposure = 0.005/(stop_distance+0.0015+0.02).
- fixed 1% stop: 0.1587301587 x equity.
- 0.8875% structural stop: 0.1646090535 x equity.
These are *risk budget arithmetic*, not actual fills. Stop-market execution can exceed the reserve. At 25x instrument leverage, liquidation depends on maintenance margin, mark-price path, fees and position mode; do not assume a 4% exact liquidation distance.

## Execution replay blocker
No matched 67-trade event-level Bybit Public Trades/L50/OI/liquidation fill records were loaded or replayed in this checkpoint. Therefore monthly net equity, MTM drawdown, slippage, liquidation counts and MFE retention remain unverified. Before using closer structural stops in any 67-trade comparison, join each entry to frozen D250 signal timestamp, original extreme, H1 ATR at decision time, execution ticks and funding, and report fraction satisfying the necessary ATR condition separately for LOW/LONG and HIGH/SHORT. Keep baseline 1% cut unchanged and prior rejected profit overlays rejected.

## Reproduction
`python - <<'PY'`
`rmin=2.0840049433824706; print(0.01/(rmin+0.25)); print(.005/(.01+.0015+.02)); print(.005/(.008875+.0015+.02))`
`PY`
