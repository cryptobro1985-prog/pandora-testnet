# 2026-11-05 Options executable-quote checkpoint

Research branch only: research/bybit-options-gamma-burst-20261105.

Implemented:
- executable_quotes.py: walk option ASK depth for paper BUY and BID depth for paper SELL; reject insufficient depth; calculate size-weighted premium, fee-inclusive round-trip estimates; conservative paper action transitions including EMERGENCY_SELL and DATA_RISK_REVIEW.
- test_executable_quotes.py: basic book walking, insufficient depth, fees, and state transitions.

Not yet integrated:
- collector signal pipeline does not call these helpers.
- Telegram transport is not wired or delivery-tested.
- No real-time position tracking loop is deployed.
- Bybit option contract multiplier, fee schedules, quote freshness, and real market validation must be verified before any price/size alerts.
- Existing collector continues to write research-only signals, not executable orders.
- No real order placement is authorized.

Next: inspect config/workflow and integrate safe paper quote checks, then add Telegram delivery with rotated token and verified chat ID. No HYPE or production changes.
