# HYPE event/path provenance implementation checkpoint — 2026-11-16 00:27 CET

## Scope and new implementation
Added `research/hype_terminal_local_strategy/event_path_provenance_gate_20261116.py` in the existing branch. This is a **research-only companion**, not a replacement of the production pipeline or a claim of verified fills. It addresses the previous checkpoint's concrete EVENT-vs-PATH defect:
- EVENT evidence is checked at its expected timestamp and requires nonempty event ID, order ID and HYPEUSDT symbol; it no longer must cover the entire holding interval.
- PATH evidence must cover the full holding interval with strictly increasing timestamps and a bounded maximum gap; an interval label alone cannot pass.
- A stop-order ACK later than entry is explicitly classified `UNPROTECTED_ENTRY_TO_ACK`. A private ACK cannot be inferred from public trades.
- All files must exist within the configured root and match SHA256. Success returns **HASHED_METADATA_ONLY_NOT_EXECUTION_VERIFIED**.
- STOP trigger ordering is checked. The code does not pretend a stop trigger is an actual fill.

## Concrete reproducible synthetic analysis
The companion self-test exercises five distinct cases: (1) point-event entry/exit/ACK evidence accepted as *metadata only*; (2) late stop ACK rejected; (3) incorrect event timestamp rejected; (4) gap in the mark path rejected; (5) BTCUSDT evidence rejected for a HYPEUSDT trade. Run:
```bash
python research/hype_terminal_local_strategy/event_path_provenance_gate_20261116.py
```
Expected: `PASS 5 synthetic tests`. The equivalent five-case local implementation was executed successfully before commit; committed file has not yet been run inside GitHub Actions.

## Source inventory relevant to actual replay
Existing recovered Actions artifact 13650399622 was previously audited: four compact M1 periods, 157,375 rows and **five missing minute timestamps**. It is a compact OHLC/flow dataset, **not** tick-level bid/ask, L50 event tape or private exchange fills. Therefore it supports bounded bar-level checks only, not exact stop gap, queue position, liquidation or MFE execution.

## Boundaries and next action
The original 67 completed episodes and four censored episodes have **not** been joined to real timestamped execution evidence. This run contains an executable provenance-gate improvement and five synthetic checks, not a 67-trade market replay. There are no new monthly net equity, MTM/closed drawdown, realized MFE, fills, liquidation counts or independent forward trading results.

Next: recover original trade-ID ledger, map each LOW→LONG and HIGH→SHORT signal availability to the recovered M1 windows, exclude the five gaps and cross-window intervals, then compare unchanged 1% cut baseline to risk-budget 0.25–0.5% and staged entries only where source quality permits. Any unavailable bid/ask, mark, L50, funding or event sequence must be reported as UNKNOWN, never filled with zeros. For independent forward, use only chronologically later unseen data.

Frozen D250 thresholds unchanged (rev_atr > 2.084004943, trade_ratio5 > 0.2727842248, side-normalized flow15 < 0.45047316). No retraining, new branches, production edits, live orders or revival of rejected profit overlays.
