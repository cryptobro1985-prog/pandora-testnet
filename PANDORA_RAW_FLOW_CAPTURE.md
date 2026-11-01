# PANDORA Flow V2 — raw executed trade capture

## Scope
Observational release only: keep live trading strategy, hourly TOP-5, $400 PAPER account, positions, PnL, fee model, pyramiding and all risk settings. No reset, no changes to entry/hold/exit/re-entry/reversal.

## Exact capture boundary
After Bybit publicTrade trade events have passed RollingMarketData chronology, freshness and ID dedup, they enter a bounded non-blocking recorder queue. PostgreSQL writes are asynchronous.

Table pandora_flow_raw_trades stores unique (symbol,trade_id), exchange timestamp ms, receive timestamp ms, aggressive side B/A, price, size, USDT notional, optional Bybit sequence, worker, persisted_at. Replay duplicates across reconnect/restart are ignored by PostgreSQL UNIQUE constraint.

IMPORTANT: This is *accepted and delivered market data*, NOT a guarantee of every exchange execution. Invalid, stale, disconnected or dropped executions cannot be reconstructed. Data before this feature is not backfilled.

Table pandora_flow_capture_events contains capture start, stream connected/disconnected, sequence regression, queue overflow and DB errors. A disconnect means completeness is unverified, even if the stream later reconnects. Avoid interpreting a sequence jump alone as a proven missing trade.

## Read-only APIs
- /api/pandora includes pandora.raw_flow_capture and latest per-token accepted/persisted trade epoch
- /api/pandora/flow/status captures counters, DB errors, queue, last persisted time; *process-local counters*, not lifetime totals
- /api/pandora/flow/trades?symbol=INIT&limit=100&before=123456 paginates accepted executions (max 500)
- /api/pandora/flow/events?limit=100&before=1234 paginates stream continuity events (max 200)

The existing pandora_win_audit_journal remains the source of actual OPEN/CLOSE/HOLD/WAIT/re-entry decisions and reasons, MFE/MAE. No old account or history cleanup occurs.

## Resource and completeness limits
Raw records are append-only with NO automatic deletion. Pump tokens can generate substantial PostgreSQL storage. Observe database size, queue, write lag and errors; add explicit cold storage/retention before indefinite operation. A full buffer means lost coverage and is flagged, not covered up. Pending in-memory batches can be lost on hard failure, especially during DB outages.

Batched writing up to 250 trades per INSERT, bounded buffer of 30,000; websocket callbacks do not wait for DB.

## Deploy checks
1. Entire isolated-DB GitHub Actions suite green, including raw recorder tests.
2. Promote reviewed SHA to main without force; Render auto-deploy existing single web service.
3. Do NOT reset PAPER $400 or positions.
4. Confirm tables, capture_started event, rows advancing and queue healthy.
5. Confirm previous PAPER history, trades, positions and money management unaffected.
6. Flag any gaps before drawing conclusions from raw trades.
