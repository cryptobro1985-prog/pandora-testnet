# HYPE M1 stop-path ambiguity probe — 2026-11-17 14:33 CET

Research only. Frozen D250 and 1% stop unchanged. No detector training, orders, production changes or new branch.

## New reproducible work
Read original frozen D250 and asymmetric 67-trade reports, the previously recovered Actions M1 audit, and current d250_trade_replay_manifest_gate.py. Implemented `research/hype_terminal_local_strategy/hype_stop_ambiguity_probe.py` and executed its eight synthetic assertions locally: **8/8 passed**.

The probe labels (a) STOP_TOUCHED_FILL_UNVERIFIED, (b) GAP_THROUGH_STOP with adverse opening-price proxy, (c) INTRABAR_ENTRY_UNKNOWN_PATH, (d) OPPOSITE_CONFIRMED_IN_BAR_FILL_UNVERIFIED, (e) HOLD, (f) BEFORE_ENTRY. Mirrored LONG and SHORT tests passed. The stop proxy is NOT an executable fill: real market-stop slippage may be worse; mark-trigger rules and bid/ask are absent.

## Newly isolated risk
The recovered 157,375 M1 rows have high/low timestamps, but a D250 signal, stop touch, and opposite confirmation within the same minute still cannot establish a valid trade path or executable exit without event-level Public Trades/mark/book evidence. In particular, entering *inside* an M1 candle and then attributing its entire low/high to the post-entry position creates look-ahead/phantom stop or MFE. The new probe explicitly returns INTRABAR_ENTRY_UNKNOWN_PATH rather than scoring it.

The 67 completed trades in the frozen asymmetric report are **not** a verified event execution ledger. Its 22 modeled fixed-cut exits cannot be labeled real stop fills. No same-sample replay can yet establish monthly net equity, mark-to-market DD, fill count, liquidation count, or MFE captured. The M1 archive's 1/1/1/2 non-60s transitions also require classification before calling the timeline gap-free.

## Next evidence gate
1. Locate the immutable 67-row signal/entry/exit ledger in existing research code or Actions artifacts; do not infer it from 71 D250 accepted signals or candidate snapshots.
2. Join each trade to UTC M1 with explicit strict ordering and a coverage map. Preserve unknown intra-minute paths as unknown, not favorable fills.
3. Attach mark/index, Public Trades and L50 where available; mark unavailable evidence as missing, never zero-impute.
4. Replay unchanged 3x/5x baseline alongside 0.25–0.5% risk-budget sizing and 1% aggregate stop-risk cap on identical trades, fees/funding/slippage, with capital reservation and monthly closed + MTM DD.
5. Test LOW/LONG and HIGH/SHORT separately. Keep rejected MFE overlays rejected until independent unseen-forward evidence.

## Reproduce
`python research/hype_terminal_local_strategy/hype_stop_ambiguity_probe.py`
Expected: `8/8 synthetic assertions passed; NO real fills validated`.

**Status:** new executed *synthetic* execution-path regression, not a 67-trade historical replay. No new profit or safety claim.
