# HYPE post-local causal exit replay scaffold — 2026-11-13
Research only, NO live orders, no retraining local detector, no production edits.

## New concrete reproducible work
Added `research/hype_terminal_local_strategy/causal_exit_replay_research.py` and `tests/test_hype_causal_exit_replay_research.py` to the EXISTING branch. Executed nine deterministic local unit tests successfully after correcting an initial fixture that accidentally hit its stop before the duplicate-timestamp validation. Final: 9/9 passed. Tests cover LONG/SHORT stop-first, no future-confirmation exit, delayed available confirmation, invalid OHLC/time ordering, intrabar adverse equity, and MFE giveback.

This script accepts chronological bar rows with actual causally timestamped opposite-local confirmation and simulates one position only. It gives STOP precedence if stop and opposite confirmation occur in same OHLC bar. Stop fills at the worse of stop level or bar close (pessimistic approximation), with explicit cost fraction. It records side, stop/opposite/open reason, net equity return, MFE/MAE, giveback and conservative worst intrabar equity estimate.

## Exact fixture results (synthetic, NOT historical HYPE)
At $100 entry, 1% price stop, 0.2x equity notional, 0.25% notional costs:
- LONG bar H103/L98/C98, opposite confirmation in same bar: STOP, net -0.45% equity.
- SHORT bar H102/L97/C102, opposite confirmation same bar: STOP, net -0.45% equity.
- LONG H103/L100/C102 with available opposite confirmation: OPPOSITE, net +0.35% equity.
- LONG H104/L100/C102: MFE 4% underlying, gross realized 2%, 50% MFE giveback.
- A confirmation only available AFTER current bar timestamp cannot trigger exit on that bar.

## Critical limits
This is a deterministic **execution-engine** experiment, not a fresh market-data backtest. No actual historical 67-entry event rows were recovered or replayed. Do not present its 9 tests as predictive precision, a historical return, or evidence of no liquidations.
Bar-high/low extrema ordering is unknown; the same bar's maximum favorable excursion may have happened AFTER a stop. Therefore MFE and giveback from OHLC can be noncausal within a stop bar; use tick sequence for exact MFE or mark intrabar MFE ambiguous. Current `worst_intrabar_equity_pct` is a conservative bar-extreme mark, NOT a true account equity path. Flat notional costs are a scenario, not actual fill or funding data.
Input opposite_confirmed must be built strictly from a frozen local detector using available timestamps; passing hindsight strict-H1 labels as this field would leak the future.
The replay currently handles a single trade and not an entire portfolio. It cannot report monthly compound, portfolio DD, liquidation count, or real funding.

## Source status
Checked `research/hype_all_in_one/MANIFEST.json` and `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`: the manifest identifies HYPE-HISTORY-20260712-20261103-MASTER, local116-HYPE, HYPE-RICH-STRONG-* and HYPE-7LAYER-* artifact families, but names do not mean retrieved binary rows. Existing frozen entry is not changed.
Existing historical reports: 71/71 accepted D250 true with 22.4% coverage, but median 61.2% MFE giveback on opposite-local exit; 67 frozen-entry 1% cut trades at 5x exposure show 29.36% closed DD. The latter does not prove low-risk performance.

## Next empirical priority
Locate and retrieve actual timestamped 67 frozen trade entries plus M1/trades/mark/funding tapes. Apply frozen entry and exit unchanged to matched real bars and compare exposure 0.2x, 0.4x, 0.8x, 3x, 5x with exact same fills. Then build a portfolio equity engine (chronological non-overlapping positions, stop-first, per-trade funding), report month-by-month closed and mark-to-market DD, LONG vs SHORT, liquidation buffer, and MFE capture. Do not promote profit-lock overlays without new untouched-period proof.
