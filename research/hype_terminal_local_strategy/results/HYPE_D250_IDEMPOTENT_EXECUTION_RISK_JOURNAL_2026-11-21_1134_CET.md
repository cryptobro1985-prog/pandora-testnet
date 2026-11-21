# HYPE D250 execution-fill idempotency checkpoint — 2026-11-21 11:34 CET

Research only; no orders, production changes, retraining, or modification to frozen D250.

## Existing defect
The existing execution_risk_reservation_20261121.py close_confirmed(order_id, fraction_of_open) accepts a fraction without an exchange execution ID. Replaying the same close callback twice reduces the remaining risk twice, potentially releasing risk capacity that is still exposed.

## New executable implementation
- execution_fill_idempotency_20261121.py: execution ID journal, exact duplicate no-op, conflicting duplicate fail-closed, unknown order fail-closed, over-close fail-closed, pending cancellation retains open risk, mark-to-market equity cap.
- test_execution_fill_idempotency_20261121.py: five deterministic regression scenarios for duplicate close, conflicting duplicate, over-close, MTM cap and partial-fill cancellation.
- The same five scenarios were executed locally with Python unittest and passed (5/5). GitHub CI execution not yet verified.

## Concrete risk replay
Equity $100; A risk reservation $0.50. Fill $0.20 of original risk; cancel unfilled $0.30; close fill ID close1 releases $0.10. Re-delivery of identical close1 is ignored; remaining risk $0.10, not $0.05. A conflicting reuse of close1 blocks new entries.

## Limitations
This journal uses stop-risk reservation units rather than native exchange quantity. Production-grade replay must reconcile execution IDs, actual HYPE quantity, partial prices, fees, funding, order status and exchange timestamps, including restart persistence. This code is NOT a fill simulator or a validated liquidation model. It does not produce new historical returns or MFE measurements.

## Next evidence gate
Match frozen 67 trades to historical UTC Public Trades and L50 executable quotes, then replay identical baseline and conservative risk alternatives. Report unresolved records instead of synthetic fills. No rejected MFE overlay promoted without unseen-forward evidence.
