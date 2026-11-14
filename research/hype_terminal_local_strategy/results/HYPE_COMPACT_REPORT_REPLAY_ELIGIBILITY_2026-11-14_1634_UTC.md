# HYPE compact artifacts: execution-replay eligibility audit
Date: 2026-11-14 16:34 UTC. Research only. No orders, retraining, production changes or threshold changes.

## Actual branch-scoped reads
Fetched and parsed JSON from:
- `research/hype_full_micro_202607/results/LATEST_REPORT.json`
- `research/hype_full_micro_202607/results/RECENT_48H_FROZEN_REPLAY_LATEST.json`
- `research/hype_full_micro_202607/results/LATEST_FEATURE_AVAILABILITY.json`
Also reread the frozen D250 and asymmetric-risk research and prior raw-retention audit.

## Concrete eligibility findings
1. `LATEST_REPORT.json` is an aggregate model/feature report (top-level keys split, features, rows, models, relationships, overall_95pct_gate). No top-level timestamped trade/event tape or D250 71-signal ledger. Its older 297-feature ExtraTrees/HistGB candidate classifier is **not** the frozen D250 post-local entry rule. Do not substitute its snapshots or model performance for terminal H1 trade replay.
2. `RECENT_48H_FROZEN_REPLAY_LATEST.json` covers Nov08 00:00 to Nov10 00:00 UTC, not the original 67 completed D250 historical trade paths. It reports 2,880 minute rows and 30,772 five-second rows **as counts**, but does not include those raw rows. It contains `candidate_replay.signals=[]`, `accepted_candidate_signals=0`, `paper_trade_path.trades=[]`, `completed_trades=0`. Therefore it cannot support a per-trade D250 replay or new net equity/stop/MFE claims.
3. The recent report's `fees_funding_slippage` is explicitly `not included`; it is unsuitable as a cost-aware execution baseline even if it had trades. Source coverage is asymmetric: 24 trades files versus one each for book, liquidations, mark, OI and ticker, with 9 missing files reported. These are file counts, not verified continuous event coverage.
4. `LATEST_FEATURE_AVAILABILITY.json` confirms 116 total documented points = 86 causal inputs, 28 target/eval and 2 metadata; missing causal IDs 111–113. No zero-imputation or future labels allowed.
5. Previous manifest reported `raw_files_retained:false`. Neither aggregate JSON inspected supplies the original event-level bytes or per-trade hashes. This is a **negative eligibility result for these particular compact artifacts**, not proof that no usable tape exists elsewhere in repository, Actions artifacts or remote storage.

## Frozen trade research (unchanged)
D250 thresholds: rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; side-normalized flow15 < 0.4504731635235635; checkpoint D250. 71 first accepted historical signals; 67 finalized next-opposite-local paths; four censored until MTM. 1% adverse entry-price cut is frozen candidate; no tight trailing. Rejected MFI-flow and ATR-trail exits remain rejected.

## What the replay must require
A 71-row signal ledger with immutable IDs, side, original extreme timestamp, confirmation/availability timestamp, executable entry timestamp, entry bid/ask or defensible spread/slippage bounds, original-local and structural-stop references; all four censored cases retained. Each source path must have verifiable hash and timestamp range. Match mark/price tape for stop-first ordering and MTM; orderbook/trades for bounded slippage; funding timestamps and margin/liquidation model. Mark missing data UNKNOWN. Public prints cannot establish private stop acknowledgement or fills. LOW->LONG and HIGH->SHORT must be evaluated separately with identical sample, fees and capital constraints. No future opposite extreme as an exit.

## Outcome and next step
This iteration performed concrete inspection of retained compact JSON structures and **rejected two specific artifacts as sources for matched 67-trade execution replay**. No trade-level replay, monthly net PnL, MTM DD, liquidation count, or MFE retention can be verified from these files. Next inspect any retained timestamped compact M1 data/ledger and workflow artifact storage; otherwise recover historical raw archives with hashes. Truly unseen forward must be later than previously inspected periods.
