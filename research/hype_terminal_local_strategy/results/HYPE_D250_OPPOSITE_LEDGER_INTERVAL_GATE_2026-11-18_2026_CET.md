# HYPE D250 research checkpoint — 2026-11-18 20:26 CET

## Concrete new finding
The previous gate trusted `opposite_ledger_coverage=COMPLETE` and `opposite_ledger_first_utc=NONE` without asserting that the source event ledger spans the **entire position lifetime**. A truncated ledger could therefore silently appear empty and allow a STOP candidate even if an opposite H1 local occurred in the missing interval.

## Change (research only)
Updated `d250_trade_replay_manifest_gate.py` to require `opposite_ledger_start_utc` and `opposite_ledger_end_utc`. Fail closed if ledger start is after entry, ledger end before exit, interval reversed, or earliest event outside the asserted ledger interval. Existing frozen D250 numeric thresholds and side rules unchanged. Code commit: `44aec2a298334d49f7bf388cffde00cc3f66e482`.

Added eight synthetic adversarial tests: full-window candidate, late start, early end, reversed interval, out-of-window event, opposite-before-stop, missing interval field, and SHORT/HIGH symmetry. Test file commit: `115db087a22cade8590dde9163b5366742b21b41`.

Run with `cd research/hype_terminal_local_strategy && python -m unittest -v test_d250_ledger_window.py`. **Tests were added but not executed in this run** (GitHub connector exposes repository file operations but no executable checkout; container cannot resolve github.com). The code is not claimed validated.

## Scope and evidence limits
`COMPLETE` plus bounded interval remains an unverified manifest assertion until matched to independent UTC source events. This gate only decides whether a trade is eligible for subsequent execution replay. No new 67-trade replay, net equity, MTM DD, stop fills, liquidation count, MFE retention, or unseen-forward performance can be claimed. Missing original May-inclusive UTC trade journal and matched Bybit Public Trades/L50/mark/funding remain the principal blockers.

Next: execute adversarial tests in GitHub Actions, reconstruct independently verified opposite-local ledger per trade, recover original trade UTC records and May event tape, then replay same-sample original baseline versus 0.25–0.5% equity stop-risk variants, with max aggregate stop-risk 1%. Do not train detectors, tune D250 thresholds, enable production, or place orders.
