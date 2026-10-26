# LOCAL H1 direction / M15 execution — v5

Requested behavior: HYPE and NEAR trade short after a confirmed H1 local high until the next confirmed H1 local low; trade long after that low until the next high. M15 detects counter-pressure to protect earned profit and confirms resumption for re-entry in the H1 direction.

Previous runtime v4 used M15 pivots as the primary direction and H1 only as context. This was a different strategy. The v3 module in git history contains the earlier H1 approach. This release restores H1 direction while retaining observed-price fills, peak-based protection and continuous entry scanning.

H1 pivots use four preceding H1 candles, the candidate candle and one following closed H1 confirmation. This is causal confirmation, not exact knowledge at the top/bottom. Subsequent candles without a new pivot preserve the last direction. A durable per-symbol anchor survives restarts and history-window roll-off. Unclosed or stale H1 data cannot authorize entries.

M15 opposite pressure may exit a profitable trade but cannot reverse the H1 anchor. Re-entry requires M15 recovery AND observed movement beyond the protective exit price in the H1 direction, so an unchanged pre-exit M15 signal alone cannot reopen. The watch is invalidated by an opposite H1 pivot, not a timer or a four-entry cap. Existing shared margin/freshness checks still apply. Opposite H1 pivots take priority over M15 profit exits.

Protection stays active between H1 pivots. A confirmed opposite H1 pivot closes a position on the old side; the next side needs M15 confirmation before entry. Historical closed rows are preserved. A legacy open position keeps its original strategy label when it later closes.

Historical evidence: the dashboard's old local_h1_m15_swing_v3 HYPE trade opened 2026-10-26 05:00:29 UTC, closed 06:12:50 UTC, records MFE ROE +38.9323% and realized PnL +3.0995 USDT. MFE is the best observed excursion, not booked ROI. A separate +40% result was not verified from the available sample.

Validation: 128 selected regressions, including H1 low/high symmetry, confirmation without future candles, persistent bias between candles, direction reversal only at H1 pivots, rejection of counter-H1 entries, M15 recovery after exit and durable watch behavior. Compilation and diff checks pass. Direct local access to live exchange candles timed out; live deployment diagnostics are verified separately. This is not a comparative backtest or a profitability guarantee. Paper execution still omits funding and actual exchange execution costs beyond the configured fee model.
