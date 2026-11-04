# HYPE H1 causal study — measured run

Status: **forward_coverage_audited**. No real orders.

## Data and checks

```json
{
  "status": "forward_coverage_audited",
  "files": [
    {
      "path": "recovered/fresh_live/HYPE_live_microstructure_1s.jsonl",
      "size_bytes": 1876559,
      "sha256": "69ff5cab2aedf01d54f10f452761c2f75bda78faaa577da2775d8ad76b8976ab",
      "snapshots": 1200,
      "duration_seconds": 1198.902,
      "snapshots_with_oi": 1121,
      "snapshots_with_explicit_oi_time": 1199,
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
