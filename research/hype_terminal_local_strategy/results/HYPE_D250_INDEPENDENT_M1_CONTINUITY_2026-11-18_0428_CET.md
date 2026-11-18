# HYPE D250 independent M1 continuity gate — 2026-11-18 04:28 CET

Research only. Frozen entry, 67-trade baseline, production, rejected overlays and real orders unchanged.

## New executable evidence check
Previous d250_event_causality_gate_20261118.py checks SHA256, declared first/last timestamps and producer-provided continuous=true. This cannot establish whether there are gaps, duplicates or out-of-order records inside the claimed interval. Added d250_m1_continuity_audit_20261118.py to independently scan every timestamp of a real M1 CSV (UTC ISO, Unix seconds or milliseconds), require minute alignment, calculate SHA256, count missing minutes, duplicates, out-of-order timestamps and outside-window records, and return verified_continuous only when all checks pass.

Command example:
python research/hype_terminal_local_strategy/d250_m1_continuity_audit_20261118.py /path/to/real_m1.csv --timestamp-column timestamp --start 2026-09-01T00:00:00Z --end 2026-09-01T01:00:00Z

## Verification
Local synthetic timestamp tests executed 4/4 passing: contiguous 3-minute sequence; missing minute; duplicate minute; out-of-order minute. This tests the algorithm only. No real historical M1 file was passed to the new scanner this iteration, and no individual 67-trade UTC ledger was recovered. Do not infer real tape completeness or trade profitability from synthetic tests.

## Replay admission contract
A passing M1 check is necessary but not sufficient. Require independent Public Trades, mark price and order-book timestamp/provenance verification; reconcile all 71 signals and 67 completed episodes, including four unresolved; independently derive same-side invalidation and opposite-local availability; reject missing evidence, not zero-fill. Only then execute paired LOW→LONG and HIGH→SHORT fill/stop simulations with consistent costs, funding, conservative 0.25–0.5% stop risk and <=1% aggregate stop risk. A complete M1 tape alone cannot reconstruct actual fills, intra-minute stop sequencing or liquidation.

## Status
Historical executions replayed this iteration: 0. No new verified monthly net equity, closed/MTM DD, stops, fills, liquidations or MFE capture. Frozen D250 thresholds unchanged (rev_atr>2.0840049433824706; trade_ratio5>0.2727842248141979; flow15<0.4504731635235635). No new branches, no retraining, no orders.
