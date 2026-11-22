# HYPE D250 — causal timestamp and execution feasibility gate
Date: 2026-11-22 15:30 UTC. Research only; no orders or production changes.

## Evidence read this run
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md (frozen D250, 71 accepted, 67 completed)
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md (1% adverse-price cut, 0.15% round-trip notional costs, 22 modeled stops)
- HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md (K2 causal availability and asymmetric LOW/HIGH persistence)
GitHub code search queries for per-trade 67-trade CSV and rich historical Public Trades/L50 artifacts returned no matching indexed files. This does NOT prove the artifacts do not exist on the research branch (code search indexes default branch). No event-level replay claimed.

## New audit: D250 clock is not sufficient by itself to authorize a strict H1 trade
The frozen rule says 250 minutes after the local candidate/extreme, and no more-extreme same-side print. The contract separately requires confirmed strict H1 terminal local and causal K2 availability. Therefore an event replay must record:
1. UTC timestamp of candidate extreme;
2. UTC timestamp of K2 confirmation **as it became observable**, not the historical pivot's candle timestamp;
3. UTC timestamp at which all three D250 features were finalized (including trade count and 15m flow windows);
4. earliest executable UTC timestamp after max(K2_available_utc, candidate_utc + 250m, features_available_utc);
5. cancellation if another same-side extreme or opposite terminal local was already known before execution.
This is a replay *integrity gate*, not a modification to frozen D250. If the old backtest assumed a fill at D250 before K2 became available, that trade must be marked look-ahead-contaminated rather than silently delayed and counted as the same baseline. LOW and HIGH require separate rows; do not merge their MAE, slippage, or fill distributions.

## New numerical stress: risk budget and execution-side asymmetry
Let E=100 USD, risk budget R=0.5 USD (0.5% E), fixed adverse stop d=1%, round-trip fee allowance f=0.15% of notional, additional adverse execution gap g. Then max notional N=R/(d+f+g). This is a scenario cap, NOT guaranteed loss control.
- g=0: N=$43.4783; at 25x isolated initial margin $1.7391
- g=0.5%: N=$30.3030; margin $1.2121
- g=1%: N=$23.2558; margin $0.9302
- g=2%: N=$15.8730; margin $0.6349
For a 1% fixed stop, a 2% gap and 0.15% fees, the modeled loss at the **unbuffered** $43.4783 notional is $1.3696 (1.3696% equity), 2.739x the intended 0.5% budget.
For LONG, entry ask, stop-side executable bid, and mark-based liquidation must be separately timestamped; for SHORT, entry bid, stop-side executable ask, and mark-based liquidation must be separately timestamped. Trade prints alone cannot prove fill or liquidation distance. A mark-price trigger and last-price trigger are not interchangeable.

## Liquidity, causal exit, and data acceptance
- Preserve original 67-trade baseline unchanged; no replacement of frozen thresholds or rejected profit trails.
- Compute matched trade IDs and order priority before alternative policies. A stop-market fill is bounded by observed executable book and impact; no exact-book snapshot => fill UNKNOWN, not zero slippage.
- Realized break-even is not the entry price: 0.15% round-trip costs plus realized adverse exit slippage must be recovered.
- MFE measured from executable prices (bid for closing LONG, ask for closing SHORT), not future opposite extreme; record MFE captured and given back with UTC.
- Test sustained opposite **price-impact efficiency** and persistence only as an unpromoted candidate; do not reintroduce previously rejected raw-flow/MFE trails.
- Monthly net equity, MTM drawdown, stop-fill count, liquidation count, and independent forward return remain NOT MEASURED until UTC fills, fees/funding, mark path, and four censored positions are recovered.

## Reproducible arithmetic (Python 3, stdlib)
```python
equity=100.0
risk=0.005*equity
stop=0.01
fees=0.0015
for gap in (0,0.005,0.01,0.02):
    notional=risk/(stop+fees+gap)
    print(gap, round(notional,4), round(notional/25,4))
unbuffered=risk/(stop+fees)
assert abs(unbuffered*(stop+fees+0.02)-1.3695652173913044)<1e-10
```

## Decision
This iteration completed a deterministic risk calculation and a source-contract timestamp audit, **not** a matched Bybit event replay. The priority blocker is recovering actual per-trade UTC signal and book/mark data. Do not promote any live sizing or MFE overlay on these results.
