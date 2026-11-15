# HYPE post-local execution semantics / risk audit — 2026-11-15 17:28 CET

Research only. Source files read directly from target branch: H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md, strict_execution_provenance_research.py, HYPE_FORWARD_CHRONOLOGY_AND_STOP_RISK_AUDIT_2026-11-15_1627_CET.md. No detector retraining, no threshold changes, no orders.

## New findings

1. **Time-zero ambiguity**. D250 is defined as 250 minutes after a local *candidate/extreme*, while the requested authorization is AFTER the true H1 local is causally confirmed. The report does not establish for each of the 71 signals that `signal_available_ts >= H1_local_K2_available_ts`. If the local is labeled using future H1 bars, a D250 signal may be post-extreme but not post-confirmation. A matched event replay must compute `entry_eligible_ts=max(D250_signal_available_ts, K2_confirmation_available_ts, required_market_data_available_ts)`; any next opposite K2 local available before this time invalidates entry. This is an audit hypothesis, not a demonstrated leak.

2. **Provenance code is not a replay gate**. `strict_gate` verifies hashes and user-declared coverage, but does not parse event timestamps, schema, sequencing, exchange order IDs, mark-price liquidation trajectory or order ACK content. It requires a `stop_order_accepted_ts_ms` even for `HISTORICAL_SIMULATED` records, potentially conflating modeled protection with actual exchange ACK. Conversely, it accepts identical 4-byte fixture files for all evidence roles in its self-test. Distinguish SIMULATED_STOP_ACTIVE (assumption) from EXCHANGE_STOP_ACK_VERIFIED (exchange evidence). Never infer zero liquidations from passing the gate.

3. **Sample accounting**. The frozen D250 audit has 71 accepted first signals but only 67 entries with finalized next opposite local; 4 lack a finalized opposite local *in that report*. Do not assume these 4 are currently open or actually executed. 67/71 = 94.366% finalized in that historical audit; this is NOT fill rate.

4. **Causal downside versus oracle**. D250 report gives median entry MAE -0.414% and worst observed -1.958%, while the frozen 1% adverse cut was selected on development data. The worst MAE exceeds the 1% stop; thus a stop is not an innocuous bookkeeping addition. To quantify skipped future recovery, replay must use timestamped M1 or richer paths and first-hit chronology, not compare stop thresholds with final outcome only. Intraminute high/low ambiguity must be conservatively resolved or classified unknown.

5. **Late-Aug negative regime persists**. D250 hold-to-causal-opposite local in late-Aug has reported mean price PnL -0.727%, win rate 27.27%; multiplying by risk-sized 0.232558x account notional would be -0.16907% average equity return per trade *if* that reported mean is on the same notional cost basis and executions are unchanged. This is merely linear rescaling, not a replay, and cannot establish profitability. Risk sizing reduces loss magnitude, not a negative price expectancy.

## Reproducible calculations
```python
n_accepted=71; n_finalized=67
print(n_finalized/n_accepted)  # 0.9436619718309859
risk=.005; stop=.01; costs=.0015; gap=.01
exposure=risk/(stop+costs+gap)
print(exposure)                # 0.23255813953488372
print(-.727*exposure)          # -0.16906976744186046 percent equity (conditional)
```

## Required next replay gate
Per LOW/LONG and HIGH/SHORT episode: candidate extreme timestamp; strict H1 K2 availability timestamp; frozen D250 availability timestamp and feature lookback cutoffs; entry order and fill event; stop activation time; price and mark paths; L50/public trade and funding evidence; opposite-local K2 availability; first-hit stop/exit; missing-data mask. Enforce no orders before causal availability; same chronological sample and one account ledger for baseline and risk-sized variants. Compare 0.25%/0.5% stop risk, <=1% aggregate stop risk, gap/slippage stress and no capital reuse. Preserve rejected MFE overlays until independently validated.

## Evidence status
No matched per-trade execution tape or independent unseen forward replay accessed in this iteration. No new monthly equity, verified fills, liquidation counts, MTM DD or MFE capture. Existing 67-trade returns are simulations, not live evidence.
