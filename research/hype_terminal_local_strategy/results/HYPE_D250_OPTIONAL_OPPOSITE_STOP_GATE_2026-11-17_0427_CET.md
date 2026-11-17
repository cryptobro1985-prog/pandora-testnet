# Frozen D250 STOP chronology gate: optional future opposite local
2026-11-17 04:27 CET. Research only; no orders or detector retraining.

## Verified source-code defect and correction
Read the actual gate source on the existing branch and the previous checkpoint. The prior gate required `opposite_confirmed_utc` in every row, including `STOP` exits. It also unconditionally parsed the opposite timestamp. Consequently a legitimate protective STOP before any subsequent opposite H1 confirmation was blocked by missing future information, creating selection bias against stopped trades.

The corrected gate no longer requires `opposite_confirmed_utc` in its global CSV column schema or parses it for STOP. For `OPPOSITE_CONFIRMED`, it requires a nonblank timestamp, validates it is not before D250 signal, and rejects an exit preceding opposite confirmation. For STOP it retains entry-to-exit chronology and all frozen D250/feature as-of checks. STOP with a supplied future opposite timestamp does not use it in the entry or exit eligibility decision. No D250 threshold or production rule changed.

## Reproducibility
Changed `research/hype_terminal_local_strategy/d250_trade_replay_manifest_gate.py`; added `research/hype_terminal_local_strategy/test_d250_trade_replay_manifest_gate.py` with 8 synthetic regression scenarios: missing/future opposite for STOP, missing/late/valid opposite for OPPOSITE_CONFIRMED, stop-before-entry, future feature, and side/local mismatch.

Run from repo root:
`python -m unittest discover -s research/hype_terminal_local_strategy -p 'test_d250_trade_replay_manifest_gate.py' -v`

Tests were committed but **not executed in this iteration**. Synthetic fixtures are not historical trades. The manifest remains a pre-replay eligibility gate, not verified fills or event replay. Manifest coverage COMPLETE is a claim, not independently checked evidence.

## Next data-dependent step
Locate original individual 67-row UTC ledger and join by time to recovered historical Bybit Public Trades/M1/mark/L50. Independently validate gap intervals, bid/ask fill feasibility, mark-price liquidation distance, funding and fees, STOP versus opposite-confirmed exit order, overlapping exposure, and separate LOW/LONG and HIGH/SHORT results. Compare frozen original against 0.25–0.5% stop-risk variants on identical chronologically held-out trades. Do not report MTM drawdown, net equity, liquidations, or MFE capture until the tape replay exists. Previously rejected overlays remain rejected.

No real orders, production modifications, detector retraining, or invented market features.
