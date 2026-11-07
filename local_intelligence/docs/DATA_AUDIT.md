# Retained historical data and causal availability audit

Audit date: 2026-11-07 UTC. Scope: the supplied 2026-10-04 00:00 through 2026-11-03 00:00 UTC HYPEUSDT history, source provenance, teacher labels, candidate selection, gap joins, and retained JSON/gzip datasets. No market fetch, external write, model promotion, or order submission was needed for this audit. **MONITOR UNCHANGED: YES.**

The retained source data pass integrity and reconciliation checks. The **original candidate feature dictionaries are not a causal training dataset**: the old generator reads final values of uncompleted 5-second and minute buckets. Retain these inputs as historical evidence; rebuild fitted features from completed `compact_1m.jsonl.gz` bars. Gzip validity, source hash validity, and separation of target IDs alone do not remove temporal leakage.

## Integrity and actual coverage

`INPUT_INTEGRITY.json` records the original ZIP SHA-256 and the pre-change archive audit: 127 declared hashes match, no declared file is missing, and the sole mismatch is the original `SHA256SUMS.txt` self-hash. The new offline verifier reads every retained JSON/JSONL record, checks complete gzip CRC/trailers, rejects NaN/Infinity and overflowing JSON floats, checks embedded artifact hashes/sizes, and reconciles chronological datasets. `DATA_INTEGRITY.json` contains the machine-readable results and file hashes. The initial verification passed all 8 gzip datasets and all 11 embedded manifest entries with zero data errors; the total JSON file count can increase as other reports are produced.

| Retained source | Actual coverage | Findings |
|---|---:|---|
| Executed-trade compact minutes | 43,198 of 43,200 | Two empty/missing minutes; no interpolation |
| Completed H1 bars | 718 of 720 | The two incomplete hours are excluded from teacher windows |
| Trade count summed from compact minutes | 14,594,337 | Exactly equals the 30-day archive provenance count |
| Daily raw archive provenance | 30 days | URLs, original archive bytes and SHA-256 retained; raw archives themselves were discarded |
| 5-second aggregates | 456,504 claimed in original manifest | Not retained; exact replay/reconstruction cannot be independently repeated from this ZIP |
| Mark-price minute bars | 43,200 | Complete ordered one-minute grid |
| Index-price minute bars | 43,200 | Complete ordered one-minute grid |
| Open-interest observations | 8,640 | Complete ordered five-minute grid |
| Funding settlements | 90 | Complete ordered eight-hour grid |

The missing compact minutes are **2026-10-04 01:44 UTC** and **2026-10-04 04:19 UTC**. Archive provenance reports a maximum intertrade gap of 84.975 seconds, consistent with minutes containing no recorded executions; without retained raw sources it is not possible to distinguish every source omission from no-trade time. Neither minute is fabricated. The labels exclude reference windows spanning incomplete hours.

All retained compact extreme timestamps fall within their physical minute. However, 7,924 `high_ts_ms` and 7,519 `low_ts_ms` equal bucket start. The original bucket constructor initializes these timestamps to the bucket boundary, and replaces them only on a strictly improved price. Some timestamps can therefore precede the first actual execution in that bucket. Treat minute extreme intervals as the defensible timing precision; exact subminute delays require raw-trade evidence.

## Teacher labels and chronology

Recomputation from retained compact minutes reproduces both archived teacher datasets and their exclusions exactly:

| Teacher | Retained labels | HIGH / LOW | Finalized / terminal censored | Confirmation after extreme interval |
|---|---:|---:|---:|---:|
| H1 L6/K2 strict | 77 | 38 / 39 | 76 / 1 | 2–3 hours |
| H1 L3/K1 internal | 123 | 62 / 61 | 122 / 1 | 1–2 hours |

Strict exclusions comprise three missing-hour windows and one hour whose HIGH/LOW ordering cannot be recovered from OHLC. Internal exclusions comprise three missing-hour windows and seven ambiguous HIGH/LOW hours. Excluded/censored events are not negatives.

`label_available_ms` denotes completion/availability of the required future teacher hours. `reference_finalized_ms` denotes availability of the next retained opposite pivot and is later: consecutive same-side pivots can replace an earlier extreme in the collapsed reference. These timestamps serve different purposes. A training split must require its selected label maturity/finalization before the split boundary, and evaluation must censor the unresolved terminal swing. At each of the original train/validation and validation/OOS boundaries, one retained strict reference spans the boundary. Splitting only on candidate time leaks dependent reference outcomes across folds.

Independent review of the new benchmark caught the same boundary issue in selection: the Oct 25–27 threshold-validation interval initially included three positive stage records from one candidate whose reference matured on Oct 27 at 11:00 UTC, after OOS began. A six-hour maturity embargo removes 30 validation records from 16 candidates, including nine positive records. Architecture/threshold selection must filter both examples and teacher denominators by maturity before its cutoff; the Quantum owner repaired this and reruns the experiment with the original selection rule unchanged. Early results from the flawed selection pass are superseded and cannot support performance claims.

`labels.py` now rejects invalid physical/availability chronology (`ts_ms < bar_end_ms`), invalid OHLC, and invalid pivot-window parameters. It normalizes intrahour input order and requires reference finalization to be at least as late as both its own pivot availability and the next opposite pivot availability. This matters when an earlier lookback bar arrives late. Its output schema and all valid archived labels remain unchanged. Completed bars with delayed receipt keep their physical duration while delaying label availability.

## Original feature leakage and selection bias

The original `snapshot_features` selects 5-second rows by **bucket start < prediction time**, then reads their final flow/OHLC. A final row overlapping the prediction time is future information. 6,240 of 6,261 snapshots lie inside a five-second bucket; this is timing exposure, not a claim that all numerical values necessarily changed after the prediction. The 5-second stream is absent, so this exposure cannot be numerically removed from the archived dictionary.

The original minute feature lookup selects the latest **minute start <= prediction time**, then uses final extrema, volatility, volume and turnover from that minute. All **6,261** archived snapshots select a source minute whose physical end is after their prediction timestamp, including 17 forecasts exactly on a minute boundary. All original minute-derived features must be rebuilt. The enriched snapshot file preserves these original features, so adding correct mark/index/OI/funding cannot make the old dataset causal.

Candidate eligibility also uses the final minute's six-hour record extreme. A forecast at the eventual extreme time or 30 seconds afterward may precede completion of that selection minute. The saved 0/30-second snapshots cannot establish a prospective candidate-generation result. Delays of at least 60 seconds are after candidate-minute completion, although their other original input features still need rebuilding. One-minute history cannot support honest independent 0/30-second feature comparisons.

| Unit | Count | Interpretation |
|---|---:|---|
| Unique selected candidates | 1,797 | Six-hour record eligibility, highly serially dependent |
| Candidate snapshots | 6,261 | Mean 3.48 correlated views per candidate; not independent successes |
| Snapshots at 0 / 30 / 60 seconds | 1,797 / 1,366 / 1,129 | Declining count includes survival filtering |
| Snapshots at 180 / 300 / 600 / 900 seconds | 689 / 543 / 396 / 341 | Later cohorts condition on survival; cross-horizon metrics need common-cohort or survival-aware interpretation |
| Strict labels represented by candidates | 77 / 77 | All strict reference events represented |
| Internal labels represented by candidates | 95 / 123 | 28 internal pivots omitted; candidate-conditional recall overstates internal event recall |
| Strict positive candidate prevalence | 4.285% | Class imbalance is substantial |

The original 30-day partition has 29 strict events in the discovery training interval (Oct 11–23), 10 in validation (Oct 23–27), and only **20 in final OOS** (Oct 27–Nov 3), ten of each side. The earlier Oct 4–11 interval contains 18 more strict labels. Repeated views cannot create additional independent market events. Per-side performance, regime slices, calibration bins, and neural architecture comparisons have wide uncertainty at these sample sizes. Use event/swing grouping, chronological purging, delayed-label maturity and confidence intervals; neither fine-grained confidence percentages nor claims of general superiority are supported by 30 days alone. Archived legacy OOS scores are tainted by the input leakage and are historical evidence, not usable performance estimates.

## Mark/index/OI/funding availability fixes

The archived gap join correctly treats mark/index timestamps as bar starts and requires `source_start + 60000 <= snapshot`. No completed-bar end-time leakage was found in that part of the join. OI/funding timestamps describe exchange observations/settlements. **No source includes historical receive timestamps or measured publication latency.** Complete source grids establish coverage, not contemporaneous delivery.

`hype_history_backfill/run.py` now:

- Requires physical completion/observation plus an explicit assumed publication lag, default 1,000 milliseconds, before joining.
- Honors recorded availability/receipt when present, with earlier still-fresh observations allowed while a later receipt is pending.
- Expires mark/index after two minutes, OI after five minutes, and funding after eight hours; missing/stale inputs stay absent. Tight OI/funding limits deliberately create short missing windows near a new publication rather than use an expired observation.
- Anchors OI deltas to the current observation time and refuses absent, excessively distant, or not-yet-received historical baselines.
- Clears previous `hist_*` fields on re-enrichment so stale original values cannot survive changed availability assumptions.
- Validates source ordering/values and prevents overwriting the original snapshot file.
- Emits source time, physical end, assumed availability, age, maximum age, explicit unknown receipt, and an upstream-causality-unverified flag. Download completion time is distinct from historical receipt time.

The one-second publication lag is a research sensitivity assumption, **not proof of actual historical availability**. Validate lag sensitivity and then measure actual forward receive times before allowing promotion. The gap utility cannot repair causal errors inside its upstream snapshot feature dictionaries. Original uploaded artifacts remain unchanged for reproducibility.

The archived 116-point availability file declares **46 of 86 predictive IDs** observed in its archive-only pass. Its 84 engineered feature names are transformations of those sources, not 84 independently observed contract inputs. Later gap data provide additional real sources, but matching historical/live names, normalization, definitions and cadence remains necessary. Historical L50 replay, liquidation events, receive latency, sequence health and clock offset remain unavailable; the verifier and gap utility do not synthesize them.

## Reproduction and tests

From the bundle root:

```bash
PYTHONPATH=src python -m research.hype_history_backfill.verify \
  --root . --output docs/DATA_INTEGRITY.json
PYTHONPATH=src python -m unittest \
  research.hype_history_backfill.test_integrity \
  research.hype_local_v5.tests.test_evaluation -v
```

The second command passed **28 tests**, including twelve new data-integrity/availability/teacher tests. Cases cover gzip truncation, nonfinite JSON, hash tampering, malformed manifests, manifest traversal, both project receipt timestamp aliases, completion/publication/receipt boundaries, stale source removal, OI horizon alignment, delayed teacher maturity/finalization, incomplete/overlapping hours and invalid chronology. The verifier exits nonzero on integrity/schema failures and never deserializes uploaded pickles. The new Quantum benchmark separately rebuilds causal features and reports independently measured results; this report does not substitute legacy metrics for that experiment.
