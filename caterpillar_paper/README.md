# Caterpillar PAPER runtime

Isolated from `app.py`, Render, Neon and PostgreSQL. Public Bybit data only; no private client or exchange order adapter is imported. Source lives on `caterpillar-paper-runtime-v1`; main and historical code are unchanged.

```bash
cd /workspace/pandora-testnet
python3.12 -m venv .venv
.venv/bin/python -m pip install -r research/caterpillar/requirements-lock.txt
.venv/bin/python -m unittest discover -s tests_caterpillar -v
cd research/caterpillar
../../.venv/bin/python -m unittest discover -s tests -v
cd ../..
.venv/bin/python -m caterpillar_paper --output /workspace/caterpillar-session --minutes 320
```

Set `PAPER_SYMBOLS=BTC,ETH,SOL,NEAR,HYPE` to select five validated instruments manually; otherwise the current liquid Bybit USDT perpetual universe is scanned. Two quote observations are needed to measure recent movement; no fixed historical cohort is substituted. The initial top five are frozen for the session. Ranking continues independently and never removes positions. The scanner uses recent absolute displacement, turnover growth proxy and spread. Turnover delta from a rolling 24h statistic is explicitly a proxy, not exact executed volume or orderbook depth.

Run tests before dispatching **Caterpillar PAPER Runtime**. A push to this branch starts the gated workflow. Dispatch inputs allow 1–330 minutes and an optional completed run to restore. There is no recursive continuation or schedule. A new dispatch restores the latest same-branch checkpoint, including losses and open positions. Concurrent workflows queue behind one repository-wide engine group. A local file lock prevents competing processes on the same output directory. The first complete fresh market snapshot must appear within the startup health deadline (180s by default); otherwise the runtime checkpoints ERROR and exits 2. This is a service readiness check, not a strategy cooldown.

SQLite is the transaction source for state and events. Checkpoints include state, complete history/journal, schema, config digest and checksum. Writes use fsync + atomic replace. Restores fail on corruption/config mismatch; fresh flow and current H1 verification are required. A restored portfolio is unpriced until real new marks arrive. Runtime stops before the hosted runner's 6h execution limit, reserving time for final checkpoint upload. Current official limit verification was blocked by network policy; 330m cap is deliberately below 6h and job timeout is 350m. Artifacts expire after 30 days; download retained checkpoints before expiry for longer storage.

## Trading rules and assumptions

- H1 uses the existing causal research `H1Tracker`: four preceding closed bars, an extreme and a subsequent strictly retreating closed H1. Simultaneous opposite confirmations are ambiguous and block new entry. UTC pivot candle time, confirmation availability and actual observation time are separate. Exact OHLC extreme tick time is unknown and stays null.
- Flow uses research `features` on non-overlapping groups of 32 actual accepted executions; baseline is eight past groups, bounded at 256. These are event evidence, not a 60/180/300-second wait. Reconnect clears decision evidence; no stale/neutral substitution.
- Entry needs matching valid H1, current H1 fetch, fresh tape, price-responsive executed notional control, positive own acceleration, two control observations, and no own absorption. Majority notional without matching price response cannot enter. Minority-efficient flow is observable in response fields, but it is not promoted to an entry rule without artifact evidence.
- Normal exit needs two consecutive price-responsive opposite control observations; own effective control is then absent. A single opposite spike or weakening alone holds. A newly confirmed opposite H1, breached original anchor or modeled maintenance breach exits existing risk on the next available fresh actual mark. MFE is diagnostic, never a trailing stop.
- After a normal flow exit the original local/cycle are retained. Re-entry needs that same intact anchor, an actually observed correction deeper than the larger of estimated round-trip costs and research price scale, recovery from the correction extreme, original effective control, persistence and positive own acceleration. This cost-scaled correction floor is an explicit engineering hypothesis, not an artifact-validated optimum.
- Signals fill only on a strictly later received market execution, rechecking anchor, current history, price and direction. Entry fills are adverse by 2bps; exits likewise. Fees are 4.5bps per side, from research defaults. $500 starts the session; allocation is 20% current equity at up to 25x, limited by instrument metadata, lot sizes and free collateral. Entry fees and estimated exit costs reserve collateral. Defaults are configurable through uppercase config field names; config changes require a new session. Pyramiding is disabled because its exact historical rule is unverified.
- Maintenance is an explicit conservative isolated-margin approximation. Actual gap losses are recorded even beyond margin; no loss cap, deleted trades or fake liquidation fills. Funding/depth/market impact/exchange-specific tiers are not modeled. MFE/MAE use estimated executable net PnL; timestamps, fees and adverse fill slippage are retained.

## GitHub-native monitor

`--publish-repository OWNER/REPO` publishes one atomic snapshot commit each minute to `caterpillar-monitor-data`, containing a read-only mobile `index.html` and `state.json`. It uses `gh`'s existing authentication, never frontend credentials. The first publish creates GitHub Pages only if no site exists; an unrelated Pages source is preserved. Pages must be supported by the repository/account, and unauthenticated raw snapshot access must be possible. A private repository may need a separately authorized public monitor destination; no credentials are put into the browser to work around it.

The static frontend fetches snapshots from GitHub raw, whose CDN can delay visibility. It marks a snapshot older than 90s STALE even if the saved process status says ONLINE, shows actual market ages, and retains the last snapshot with an ERROR indicator on fetch failure. It never claims the static page is a realtime backend. Full trade/event history lives in the checkpoint artifact; the mobile snapshot contains the latest 200 closes and 80 events.

No monitor URL is considered verified until the externally published page and current session have actually been fetched and opened. See `EVIDENCE.md` and `HANDOFF.md` for current verification and blockers.
