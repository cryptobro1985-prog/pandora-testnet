# PANDORA FLOW V2 — PAPER cutover (2026-11-01)

This release changes **directional decision logic**, not transport or money accounting.

## Trading
- Universe: Bybit linear USDT perpetual contracts with positive 24h price change and **at least 1,000,000 USDT turnover24h**; highest 5 selected **once every hour**, fixed until next refresh.
- A held position outside refreshed TOP-5 remains managed until the real executed-flow exit.
- Buy/sell direction: accepted Bybit aggressive executions, rolling flow notional, price response, sustained/context control. No H1/M15 candle gates in FLOW V2 execution.
- LONG and SHORT both hold through non-confirmed micro-pullbacks. Exit requires three **distinct new trade events** with opposing control and a material price response, not polling or a timer.
- Re-enter only on trade events newer than the close. Fees, slippage, dynamic margin, >=10% entry collateral, >=10x leverage and pyramiding remain in the existing risk and ledger modules.
- Market data loss is displayed as DATA_UNCERTAIN and blocks new discretionary entries. Existing fresh-mark maintenance protection remains active. No profit guarantee.

## Infrastructure retained
Existing Bybit WebSocket transport, RollingMarketData normalization/dedup, Render PostgreSQL ledger, account lease, atomic entries/closes, fees, contract leverage constraints, MFE/MAE and mobile monitor remain intact. The old H1/M15 source files remain available for auditing/rollback but are skipped in FLOW V2 runtime decision routes.

## One-time account reset
When `PANDORA_FLOW_V2=1`, the **newly deployed process must first acquire the single-writer lease**, then in one PostgreSQL transaction copy prior `pandora_win_*` tables into distinct `pandora_win_legacy_flow_v2_20261101_*` archive tables, clear the current ledger, set realized=0 and equity=400 and insert immutable `pandora_win_experiment_migrations` marker.

If copying/clearing fails, transaction rolls back and new PAPER executor remains inactive. Later restarts skip reset and restore ongoing FLOW V2 state. No real exchange account or order API is involved.

## Verifying release
1. GitHub Actions `.github/workflows/tests.yml` succeeds at target SHA, including `tests/test_flow_v2_400.py`.
2. Before promoting `main`, set Render environment `PANDORA_FLOW_V2=1`. Verify service is configured for `main` auto deploy.
3. Fast-forward `main` to the reviewed SHA (no force).
4. Check Render latest deployment status=live, SHA exact.
5. Check `pandora_win_experiment_migrations` has marker `PANDORA_FLOW_V2_400`, archived row counts; verify initialized $400 and zero positions/trades if viewed before the first automatic trade. Once trading, compare equity with realized and unrealized PnL; **do not pretend balance remains $400**.
6. Check `pandora_win_runtime_state` scanner selection includes `selected_at`, `next_refresh_at`, `min_turnover_24h_usdt` and 5 eligible symbols, or explicit `missing_candidates`.
7. Monitor `/api/pandora`, `/api/pandora/history`, `/api/pandora/events` for genuine OPEN/CLOSE/WAIT and fresh Bybit tape. An order is not guaranteed if market control isn't confirmed.
8. If deployment or migration fails, investigate logs and fix; do NOT force-reset or fake PnL, and don't claim LIVE unless verified.

Historical trade outcomes, raw exchange events and unrealized PnL from before migration are not added to the new ledger. Flow snapshots contain the latest exchange trade ID/receive timestamp, rolling volume and control; this is **not an immutable complete raw tick archive**.
