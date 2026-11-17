# HYPE D250 stop-distance and aggregate risk envelope — 2026-11-17 16:35 CET

Research only. Frozen D250 thresholds, baseline and rejected overlays unchanged. No retraining, production changes or orders.

## Executed work
Read the existing HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, the recovered Actions M1 audit, and the most recent entry-bar consistency module. Implemented and locally executed `hype_stop_risk_envelope_20261117.py`: **PASS 7/7 deterministic checks**. This is a numerical preflight, **not** matched historical execution replay.

## Concrete quantitative comparison
For a hypothetical $100 account, LONG 100 -> stop 99 or mirrored SHORT 100 -> stop 101, round-trip fees 0.15% of notional, slippage allowance 0.10%, gap allowance 0.50%, the stressed loss per unit notional is 1.75%. Risk 0.25% equity gives maximum notional $14.2857 (0.142857x account exposure) and initial margin $0.5714 at 25x; risk 0.50% gives $28.5714 (0.285714x) and margin $1.1429. The allowances are illustrative assumptions, not measured exchange data.

With $100 equity and $0.90 already reserved in aggregate stop-risk, a new 0.5% trade is capped at **$0.10 risk** by the 1% aggregate limit, or $5.7143 notional under the same scenario. When $1 is reserved, new notional is zero. LONG/SHORT symmetry and invalid stop-side rejection were tested.

The model computes a *stress sizing budget*, not a guaranteed loss bound: gap size is unbounded, stop fill, maintenance margin, funding, and liquidation path are unverified. The baseline 67 trades, 3x $100->$531.16 and 5x $100->$1,308.86, remain unverified modeled results; this exercise cannot be substituted for their replay.

## Reproduction
`python research/hype_terminal_local_strategy/hype_stop_risk_envelope_20261117.py`

## Critical missing evidence
Original immutable 67-trade UTC ledger, per-event Public Trades/mark-price/L50 execution context and actual quote/stop fill model. The recovered 157,375 M1 bars alone cannot certify fills. No new net PnL, monthly equity, closed/MTM DD, liquidation count or MFE retention is asserted. Next empirical work must reconstruct the ledger and perform same-sample event replay with UNKNOWN outcomes where evidence is missing.
