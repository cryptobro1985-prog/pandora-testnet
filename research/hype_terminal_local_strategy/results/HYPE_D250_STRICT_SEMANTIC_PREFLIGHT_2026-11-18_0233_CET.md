# D250 strict semantic preflight — 2026-11-18 02:33 CET

Research only. Original frozen D250, original 67-trade baseline, rejected overlays, production and live orders unchanged.

## Work completed
Read the frozen D250 rule report, asymmetric-risk report, existing d250_trade_replay_manifest_gate.py, and prior regression probe. Executed four synthetic semantic regression checks locally (4/4 passed) for same-side invalidation, already-confirmed opposite local, checkpoint timing, and missing event evidence.

## New finding
The existing manifest gate accepts self-declared COMPLETE coverage without raw tape proof. It also does not reject same-side extension before entry, and STOP rows can pass without proof that opposite H1 local had not already been confirmed before entry. Thus ELIGIBLE_FOR_EVENT_REPLAY is not proof of causal trade eligibility or exchange execution.

## Required strict gate before replay
1. Match extreme, H1 confirmation, D250 checkpoint, feature as-of, entry, exit timestamps in UTC; reject invalid order and future features.
2. Require evidence of no new same-side extreme between original extreme and entry, and no already-confirmed opposite local before entry, based on historical event tape (not just self-reported manifest timestamps).
3. Match M1, Public Trades, mark-price event interval files with immutable SHA256 and independently verify UTC interval completeness; hash alone proves file identity, not coverage.
4. Replay stop trigger and fill with available book/trade events, gap/slippage and mark-price liquidation; fail closed on absent L50, OI, funding rather than zero-imputing.
5. Separate LOW→LONG from HIGH→SHORT, reserve capital across overlapping positions, enforce 0.25–0.5% risk per trade and 1% total stop-risk, retain baseline unchanged for paired comparisons.

## Limits
No original 67-trade individual UTC ledger or independently matched event replay was recovered in this iteration. Therefore no new monthly net equity, MTM DD, fill count, stop count, liquidation count or MFE captured/given back is asserted. Four synthetic tests do not establish historical profitability. Next step is to reconstruct the 71 signals/67 completed trades and verify all four unresolved candidates.

Frozen thresholds: rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; side-normalized flow15 < 0.4504731635235635. No threshold changes or retraining.
