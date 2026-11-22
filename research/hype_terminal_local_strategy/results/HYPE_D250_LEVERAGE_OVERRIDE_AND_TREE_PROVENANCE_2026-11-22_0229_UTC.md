# D250 post-local execution safety: leverage override and full Git-tree provenance — 2026-11-22 02:29 UTC

Research only. Existing branch. No detector training, threshold changes, production deployment, or orders.

## Source-backed new audit
Read current source blobs `d250_conservative_stop_risk_sizer_20261121.py`, `d250_combined_risk_gate_20261122.py`, `d250_liquidation_clearance_research_gate_20261121.py`, and the frozen 67-trade aggregate report. Enumerated the COMPLETE recursive Git tree at parent commit `62eda3513917c6aa59dfc29be8dcf8460a236cd0`: 1,110 entries, `truncated=false`. The root `MANIFEST.json` is a Pandora release/package file hash manifest, not a 67-trade execution manifest. Movement-strategy trade CSVs exist but are NOT proven to be the D250 67-trade ledger. Git tree enumeration cannot rule out external Actions, LFS or remote object-store artifacts.

## Concrete new defect: caller-controlled leverage overrides
The existing `Candidate` dataclass defaults `max_leverage=25.0` and `max_margin_fraction=0.20`, but `size()` accepts ANY positive `max_leverage` and ANY `max_margin_fraction` up to 1. The composed `evaluate()` never checks these caps. Thus a caller can pass `max_leverage=100`, `max_margin_fraction=1`, and receive `RESEARCH_CANDIDATE_ONLY` if risk-notional and liquidation-clearance gates otherwise pass. The nominal risk budget still caps modeled stress loss, but the declared instrument/margin policy is not enforced and isolated margin can become unrealistically small.

Adversarial deterministic calculation: equity $100, entry $100, LONG stop $99, 0.5% equity risk, 0.15% round-trip fee, 2% adverse gap => notional = 0.5/(0.01+0.0015+0.02) = $15.873015873. At 25x implied initial margin $0.634920635; at caller-supplied 100x implied margin $0.158730159, a 4x understatement. The separate liquidation clearance uses a supplied liquidation price rather than deriving it from actual leverage/margin and cannot independently detect this inconsistent leverage claim. These are hypothetical inputs, not Bybit executions.

## Required research gate before any execution
1. Reject `max_leverage>25` and `max_margin_fraction>0.20` in an immutable policy wrapper; never treat caller inputs as permission to raise the limits. Verify actual account leverage and isolated-margin state against authenticated exchange snapshots.
2. Require executable quantity rounding DOWN to the exchange's contemporaneous lot step; reject if below min quantity/min notional. Never round UP beyond risk budget.
3. Keep `RESEARCH_CANDIDATE_ONLY` non-executable. No zero-liquidation assertion until mark/stop precedence and actual fills are replayed.
4. Recover 67 UTC event rows and matched Public Trades/bid-ask/mark/L50/funding, then run same-sample paired original baseline vs 0.25%-0.5% equity stop-risk, non-overlapping capital, monthly net and MTM DD. Preserve rejected MFE overlays unless truly unseen evidence reverses that result.

## Evidence / reproducibility
- Git tree SHA `7a42169e83203317c5d906265f1d774b7967f318`; API GET `/repos/cryptobro1985-prog/pandora-testnet/git/trees/<sha>?recursive=1`.
- `research/hype_terminal_local_strategy/d250_conservative_stop_risk_sizer_20261121.py`: positive-only leverage check and margin fraction <=1.
- `research/hype_terminal_local_strategy/d250_combined_risk_gate_20261122.py`: calls `gate(state)` and `size(candidate)` without policy cap.
- `research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: aggregates, not timestamped execution tape.

No 67-trade matched event replay was run; no new validated return, fill, MTM drawdown, or liquidation result. Frozen D250 unchanged.
