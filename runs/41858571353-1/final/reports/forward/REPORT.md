# HYPE H1 causal study — measured run

Status: **forward_coverage_audited**. No real orders.

## Data and checks

```json
{
  "status": "forward_coverage_audited",
  "files": [
    {
      "path": "recovered/prior/original/artifacts/HYPE-H1-LOCAL-V5-LIVE-MICROSTRUCTURE/HYPE_live_microstructure_1s.jsonl",
      "size_bytes": 919083,
      "sha256": "62e1e819b4dfa48aea5c28cb5139c7b5fd313e5a428b4025979dc3d2f093d8ca",
      "snapshots": 1200,
      "duration_seconds": 1198.694,
      "snapshots_with_oi": 1199,
      "snapshots_with_explicit_oi_time": 0,
      "sufficient_six_hour_warmup": false
    }
  ],
  "precision": null,
  "causal_reason": "No six-hour raw-price warmup/complete forward reference supplied; coverage alone cannot validate H1 precision",
  "no_synthetic_market_data": true
}
```

## Interpretation

The score is an uncalibrated sequential heuristic; it is not a probability.
A 100% sample precision is not a guarantee of future precision.
The reference is strict offline L6/K2 with same-side collapse; it is not live evidence.
Final OOS was evaluated once only if discovery selected an eligible rule.
Historical OI/book/liquidations are not synthesized. Missing ablations are unmeasured.
Any existing forward artifact was already observed by prior research and is a forward sample, not a new untouched test.
Only outputs with actual counts establish a measurement; absent values mean unmeasured.
