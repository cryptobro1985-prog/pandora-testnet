# Dashboard strategy statistics

Each of News, Whale Liquidation, Pump/Dump, and Local H1/M15 has all-time and rolling-eight-hour closed trade counts, wins/losses/breakeven counts, win rate, and realized net PnL. Live open PnL and all-time realized plus open PnL are shown separately. Eight-hour boundaries and refresh time display in Samara time. The window uses closure time, including trades opened before the window and closed within it.

Aggregate queries read the complete shared history with dedicated journals as fallback for missing shared rows. Mirrored trades match symbol, opened timestamp, and side; differing close timestamps do not cause double counting. Today's realized counter now uses this same canonical dataset instead of adding mirrored tables together. No trade rows are deleted or rewritten.

Pump restored baseline has 26 trades and aggregate PnL but lacks individual win/loss outcomes. All-time PnL and trade count include this baseline; full win rate stays unavailable, while known-row win rate and denominator are shown explicitly. The archive is excluded from rolling windows because original close times are unknown.

Statistics run only in the existing history worker. HTTP rendering uses cached aggregates plus current in-memory prices. Existing automatic monitor refresh and trading logic are preserved.

Validation: seven SQL-semantic regressions execute the deduplication/window/grouping query against SQLite with PostgreSQL cast/driver adaptation. Existing live-dashboard (2), accounting (8), and continuous-entry (3) regressions pass, for 20 checks total. Python compilation and diff checks pass. Deployment also verifies the PostgreSQL result and rendered monitor.
