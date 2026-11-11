# HYPE Tradeable Path Oracle — verified audit (2026-11-11)

## Confirmed GitHub Actions result
- Workflow: HYPE tradeable-path oracle audit
- Run ID: 42944064986
- Commit: a9838c9dd285ff6d8fc5f90fc49d1d95e370956d
- Created: 2026-11-11T02:09:42Z
- Status: completed
- Conclusion: success
- URL: https://github.com/cryptobro1985-prog/pandora-testnet/actions/runs/42944064986

Workflow executes:
`python -m unittest -v test_tradeable_path_oracle_v2.py test_tradeable_path_oracle_v2_bruteforce.py`

This validates the code's unit tests including 729 tiny synthetic price paths and cooldown boundary. It DOES NOT validate the historical market performance or that the evaluation oracle is executable live.

## Reviewed implementation
File: `research/hype_movement_signature/tradeable_path_oracle_v2.py`
- Ex-post dynamic programming, O(n^2) per contiguous segment.
- No same-timestamp flips; minimum hold and cooldown.
- Entry/exit use executable ask/bid when present; otherwise mid.
- Charges round-trip fees and slippage.
- Reports simple-return sum, NOT compounded equity return.
- Separates segments on time gaps.
- Uses future prices and therefore must remain evaluation-only.

## Important evaluation caveats
1. If bid/ask are absent, falling back to mid makes the execution assumptions optimistic. Realistic historical spread/depth/slippage are needed before calling this a tradeable upper bound.
2. The optimization maximizes the sum of simple returns, not compound equity or risk-adjusted utility. Do not interpret `total_net_pct` as leveraged portfolio PnL.
3. The oracle knows future paths. It must never be included in runtime X, thresholds, gating, or signal logic.
4. Minimum holding time and cooldown are only coarse execution constraints; order-book depth, funding, latency, adverse selection, and liquidation are not simulated by the oracle.
5. Data freshness masks and missing intervals need an explicit coverage report. Never silently treat missing book/OI/liquidation fields as zeros.
6. Historical Nov8–Nov10 data previously inspected for tuning must not be called untouched holdout for new revisions.

## Next reproducible milestone
1. Materialize price time series from existing compact artifacts (first verify exact artifact availability, timestamp coverage, schema and integrity).
2. Produce daily oracle report for each threshold with source hashes, coverage/gaps, costs, trade count and LONG/SHORT path.
3. Align frozen strategy trades on identical timestamps and identical execution-cost assumptions.
4. Report path capture, missed LONG/SHORT opportunities, and MFE giveback. If costs/data differ, do not compute a misleading ratio.
5. Freeze any new strategy BEFORE a genuinely fresh forward window; retain real orders OFF.

No new PnL or OOS edge is claimed by this audit.
