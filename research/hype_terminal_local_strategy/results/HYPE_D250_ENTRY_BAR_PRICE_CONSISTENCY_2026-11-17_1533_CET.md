# HYPE D250 M1 entry-bar price consistency — 2026-11-17 15:33 CET

Research-only, no production/orders, no retraining, frozen D250 and rejected MFE overlays unchanged.

## New executed check
Inspected `hype_stop_ambiguity_probe.py`, `m1_stop_order_ambiguity_replay_20261116.py`, `stop_bar_mfe_bounds_research.py`, the frozen 67-trade asymmetric report and the recovered Actions M1 audit. Added `hype_entry_bar_consistency_20261117.py` to this existing branch and ran it locally: **10/10 synthetic tests PASS** (five LONG/SHORT symmetry and boundary categories, including mismatched entry price, entry inside minute, preexisting position, invalid stop side, no-touch).

## Newly identified source of false precision
The previous M1 stop-path probe treats entry exactly at the bar start as sufficient to assess bar-wide stop touch. However it never checks that the assumed entry price matches the opening price, or that any entry fill was possible. Example: LONG entry=102 at 00:00:00 while M1 open=100, high=103, low=98; assigning a filled position at 102 at the bar opening and counting the entire bar as post-entry is unsupported. The mirrored SHORT entry=98 has the same problem. Even entry=open is only a proxy, not a verified executable fill.

The new preflight refuses to call this a verified trade and returns `ENTRY_PRICE_NOT_BAR_OPEN_FILL_UNVERIFIED`. It distinguishes entry within minute, before the bar, after the bar, wrong stop side, stop touched but fill unverified, and no stop touch with fill still unverified. No historical price was invented.

## Implications
The 157,375 recovered M1 rows do not prove executions for the 67 modeled sequential trades. No new monthly net PnL, closed/MTM DD, mark-trigger stop fill, liquidation count, or MFE capture can be claimed. The baseline $100->$531.16 at 3x and $100->$1,308.86 at 5x remains a historical modeling result, not verified fills.

## Reproduction
`python research/hype_terminal_local_strategy/hype_entry_bar_consistency_20261117.py`
Expected: `PASS 10/10 synthetic entry-bar causality cases; zero historical fills validated`.

## Next empirical gate
Recover immutable 67-trade UTC ledger from existing scripts/artifacts; join to M1 and actual Public Trades/mark/L50 if available; require event-level order and plausible entry-side quote for each trade; preserve UNKNOWN when absent. Then compare identical trade sample, original baseline and risk-budget sizing 0.25%-0.5%, max aggregate stop risk 1%, fees/funding/slippage and non-overlapping capital, with separate LOW/LONG and HIGH/SHORT and independent unseen-forward results. Do not promote previously rejected profit-lock overlays without new independent evidence.
