# HYPE H1 causal study — measured run

Status: **market_replay_completed**. No real orders.

## Data and checks

```json
{
  "status": "market_replay_completed",
  "final_oos_evaluated": true,
  "input_files": [
    {
      "path": "recovered/refetched/artifacts/universal-minute-HYPE/HYPE_minutes.csv.gz",
      "size_bytes": 2029209,
      "sha256": "45bc63998f1a7ca3a9c50bf86601d25e249cdd1d242008998c1d482a6f1c62ce"
    }
  ],
  "observed_rows": 43198,
  "coverage": {
    "rows": 43198,
    "covered_fraction": 0.9999537037037037,
    "first_start_ms": 1791072000000,
    "last_end_ms": 1793664000000
  },
  "auxiliary_5s": {
    "input_files": [
      {
        "path": "inputs/micro_2026-10-04_2026-10-08/HYPE_micro5s_2026-10-04_2026-10-08.csv.gz",
        "size_bytes": 4060568,
        "sha256": "60f98bce5ba2f3dede461406c08e9f9732fed45831f15a755e39e0ae9b24706d"
      },
      {
        "path": "inputs/micro_2026-10-09_2026-10-13/HYPE_micro5s_2026-10-09_2026-10-13.csv.gz",
        "size_bytes": 3658047,
        "sha256": "c5d460b03586edaf82aa09674d949f96002030103b657e8609d671e4cad7dab2"
      },
      {
        "path": "inputs/micro_2026-10-14_2026-10-18/HYPE_micro5s_2026-10-14_2026-10-18.csv.gz",
        "size_bytes": 4739344,
        "sha256": "74161a8f2f1fcfff4fcc22f95812d5331e85464f4279636fcddfc1104c259a1a"
      },
      {
        "path": "inputs/micro_2026-10-19_2026-10-23/HYPE_micro5s_2026-10-19_2026-10-23.csv.gz",
        "size_bytes": 5086923,
        "sha256": "00b90efd9ae8157cdfa77c12cfd0050628b0dcdaba03d6a90a4d29619dff5af1"
      },
      {
        "path": "inputs/micro_2026-10-24_2026-10-28/HYPE_micro5s_2026-10-24_2026-10-28.csv.gz",
        "size_bytes": 4954191,
        "sha256": "ea00cd9c192b3489e0c6b8c432b15731b869f936664bcd59493b24a4e22ecd60"
      },
      {
        "path": "inputs/micro_2026-10-29_2026-11-02/HYPE_micro5s_2026-10-29_2026-11-02.csv.gz",
        "size_bytes": 6018139,
        "sha256": "38a6f2c637425fe5a4aadb1b25dbbc6772f2a711821db621976c52791d8a4976"
      }
    ],
    "observed_rows": 456505,
    "coverage": {
      "rows": 456505,
      "covered_fraction": 0.8806037808641975,
      "first_start_ms": 1791072000000,
      "last_end_ms": 1793664000000
    },
    "used_for_primary_signals": false,
    "reason": "Legacy sparse execution buckets do not prove contiguous observation windows"
  },
  "primary_resolution_ms": 60000,
  "subminute_signal_claim": false,
  "source_selection_reason": "Use genuine independently collected minute OHLC/flow; no fabricated empty5s intervals",
  "historical_oi": {
    "status": "unavailable",
    "error": "HTTP Error 403: Forbidden",
    "observations_synthesized": false
  },
  "discovery_selection": {
    "status": "selected_for_oos",
    "selected_config": {
      "model_family": "B",
      "maturity_atr": 1.25,
      "accept_score": 0.8,
      "min_survival_seconds": 60.0,
      "warmup_hours": 6,
      "retracement_scale": 0.4,
      "evidence_half_life_seconds": 60.0,
      "require_absorption": true,
      "climax_activity_ratio": 1.5,
      "absorption_activity_ratio": 1.0,
      "absorption_efficiency_decay": 0.5
    },
    "selection_basis": "maximum pooled Wilson lower bound among configs with decisions in both chronological folds; no calibrated probability claim",
    "folds": [
      [
        1792368000000,
        1792713600000
      ],
      [
        1792713600000,
        1793059200000
      ]
    ],
    "coverage": {
      "rows": 33118,
      "covered_fraction": 0.99993961352657,
      "first_start_ms": 1791072000000,
      "last_end_ms": 1793059200000
    },
    "source_manifest": [
      {
        "path": "recovered/refetched/artifacts/universal-minute-HYPE/HYPE_minutes.csv.gz",
        "size_bytes": 2029209,
        "sha256": "45bc63998f1a7ca3a9c50bf86601d25e249cdd1d242008998c1d482a6f1c62ce"
      }
    ],
    "implementation_manifest": {
      "data.py": "95fd7696d22abebca9385a1668817f0adb3f3026d362f95c20917b63d7cdac71",
      "features.py": "24091dba55ea517902cdf761697ad994b7baf7c5a3b7194c23910a5cd2ccebc3",
      "engine.py": "8f5c5c560e6558ea0248d1a7d40964e2b32e2deb8df85ca86859732e8c4a2d6c",
      "labels.py": "93d22c8d7221ee37b0a9de6a9e1271f426c996a5807ef4e649714c62e29509cc",
      "evaluation.py": "e64acaee85083033d24b7f9476ad77da7f16180d501acdaf292a60bc8048844e",
      "pipeline.py": "0d7d4b417b3a713bcfa6758af3f4d5f5e04624785630ca8cbca05ff4a366ae33"
    },
    "interval_ms": [
      60000
    ],
    "untouched_oos_start_ms": 1793059200000,
    "label_spec": "strict L6/K2; ambiguous OHLC hours excluded",
    "forward_only_families": "C/D/E/F require actual fresh corresponding observations; no synthetic backfill",
    "limitations": [
      "heuristic sequential evidence score, not SPRT or fitted likelihood",
      "small samples cannot establish perfect future precision",
      "folds compare fixed rules; no within-fold learned model parameters"
    ],
    "selection_sha256": "abf0e9164ce4bdd5bba94b1d708f08df36de531389210786995a50969322b945"
  },
  "oos_metrics": {
    "accepted": 5,
    "true": 2,
    "false": 3,
    "engine_episode_accepted": 6,
    "engine_episode_precision": 0.8333333333333334,
    "reference_locals": 19,
    "reference_censored": 0,
    "reference_locals_evaluable": 19,
    "missed": 17,
    "censored_accepted": 0,
    "first_accepted_precision": 0.4,
    "precision_wilson_95": [
      0.11762077423264783,
      0.769275718723987
    ],
    "false_local_rate": 0.6,
    "recall": 0.10526315789473684,
    "missed_local_rate": 0.8947368421052632,
    "median_delay_min_upper": 95.5,
    "p90_delay_min_upper": 124.7,
    "median_entry_distance_pct": 2.3118683630359516,
    "p90_entry_distance_pct": 2.6872202037318416,
    "candidate_invalidation_rate": 0.9556962025316456,
    "confidence_is_calibrated_probability": false,
    "by_side": {
      "HIGH": {
        "accepted": 2,
        "true": 1,
        "precision": 0.5
      },
      "LOW": {
        "accepted": 3,
        "true": 1,
        "precision": 0.3333333333333333
      }
    },
    "volatility_cutoffs_from_pre_evaluation_history": [
      0.008136029062638259,
      0.010061618843746794
    ],
    "by_volatility_regime": {
      "low": {
        "accepted": 1,
        "true": 1,
        "precision": 1.0
      },
      "medium": {
        "accepted": 2,
        "true": 0,
        "precision": 0.0
      },
      "high": {
        "accepted": 2,
        "true": 1,
        "precision": 0.5
      },
      "unknown": {
        "accepted": 0,
        "true": 0,
        "precision": null
      }
    }
  }
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
