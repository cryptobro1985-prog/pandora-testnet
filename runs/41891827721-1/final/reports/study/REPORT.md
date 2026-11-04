# HYPE H1 causal study — measured run

Status: **blocked**. No real orders.

## Data and checks

```json
{
  "status": "blocked",
  "final_oos_evaluated": false,
  "input_files": [
    {
      "path": "inputs/micro_2026-10-04_2026-10-08/HYPE_micro5s_2026-10-04_2026-10-08.csv.gz",
      "size_bytes": 4060568,
      "sha256": "f5291fb1cf4e401525a990c73a27982d455e558b0225657fd5e840068a40ef42"
    },
    {
      "path": "inputs/micro_2026-10-09_2026-10-13/HYPE_micro5s_2026-10-09_2026-10-13.csv.gz",
      "size_bytes": 3658047,
      "sha256": "a3425c0cbf78a1756a871c087bc0ec059ca2640ff53139265cf87b7deb5b5c57"
    },
    {
      "path": "inputs/micro_2026-10-14_2026-10-18/HYPE_micro5s_2026-10-14_2026-10-18.csv.gz",
      "size_bytes": 4739344,
      "sha256": "30286cecbeecb698317c276d012e4711abb10020919b5d0db465c9aca33ebdbc"
    },
    {
      "path": "inputs/micro_2026-10-19_2026-10-23/HYPE_micro5s_2026-10-19_2026-10-23.csv.gz",
      "size_bytes": 5086923,
      "sha256": "29023b61d7e5a26f2173ae94988f26f271eafb3c6df05cbf51863aa728e8b938"
    },
    {
      "path": "inputs/micro_2026-10-24_2026-10-28/HYPE_micro5s_2026-10-24_2026-10-28.csv.gz",
      "size_bytes": 4954191,
      "sha256": "8fcd68265689db2bbd4edb4d1f004281fb7c0ca38e8485ca8f9f714f4b67b9a4"
    },
    {
      "path": "inputs/micro_2026-10-29_2026-11-02/HYPE_micro5s_2026-10-29_2026-11-02.csv.gz",
      "size_bytes": 6018139,
      "sha256": "02c0420a9b37169ef7f032991d855b5c9062c8251e5c7fafc96e37e119a264ee"
    }
  ],
  "observed_rows": 456505,
  "coverage": {
    "rows": 456505,
    "covered_fraction": 0.8806037808641975,
    "first_start_ms": 1791072000000,
    "last_end_ms": 1793664000000
  },
  "error": "ValueError: Sparse 5s coverage and no unique independently collected minute archive",
  "traceback": "Traceback (most recent call last):\n  File \"/home/runner/work/pandora-testnet/pandora-testnet/research/hype_local_v5/ci_run.py\", line 79, in main\n    raise ValueError('Sparse 5s coverage and no unique independently collected minute archive')\nValueError: Sparse 5s coverage and no unique independently collected minute archive\n",
  "market_metrics": null
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
