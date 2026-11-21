# Frozen D250 — raw M1 pre-entry extension gate (2026-11-21 17:32 CET)

## Concrete change
Read the existing D250 pre-entry chronology gate and the frozen asymmetric risk report in the requested branch. The earlier gate explicitly relied on a confirmed-pivot event list, which cannot exclude a same-side intraperiod price extension that has not yet become a confirmed pivot. Added independent research-only script `d250_raw_m1_preentry_gate_20261121.py` to check **raw completed M1 highs/lows** between original terminal local extreme and entry. LONG is invalidated by a lower low; SHORT by a higher high. Rejects incomplete minute coverage, nonfinite prices, invalid chronology, and entries that occur within an unfinished M1 bar without tick evidence. Does not change frozen thresholds or historical baseline.

## Run when immutable data are available
```bash
python research/hype_terminal_local_strategy/d250_raw_m1_preentry_gate_20261121.py original_67_manifest.csv bybit_m1_utc.csv --out raw_m1_preentry_audit.json
```
Manifest: `trade_id,side,local_extreme_utc,local_extreme_price,h1_confirmed_utc,d250_signal_utc,entry_utc`. M1: `utc,high,low,closed_utc`, one closed one-minute candle per UTC minute. A zero-reason result is only **pre-entry M1 eligibility**, not execution proof. Requires independently verified source hashes and UTC coverage.

## Limitations and status
This iteration did **not** reconstruct or replay the 67 historical trades: original timestamped manifest and matched Bybit tapes remain unavailable from the inspected tracked research artifacts. No new measured stop fills, slippage, funding, monthly net equity, MTM drawdown, liquidation count, MFE retention, or independent forward result. No synthetic pass rate is represented as market evidence. This script has not been verified in CI. M1 cannot establish subminute fills or liquidation path; requires Public Trades, quotes/mark, and execution model.

## Next evidence
Join original frozen trade IDs to raw M1 with independently verified tape coverage, then Public Trades/mark/L50/funding. Reject invalidated pre-entry anchors before comparing unchanged 1% adverse-cut baseline against 0.25%/0.5% equity stop-risk and 1% portfolio cap. Compare LONG and SHORT separately, maintain chronological equity and mark-to-market drawdown, and do not promote previously rejected MFE overlays without unseen evidence.
