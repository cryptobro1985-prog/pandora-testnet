# HYPE fill-boundary fail-closed patch — 2026-11-14 03:35 UTC

Research only. Existing frozen D250, 1% adverse cut and original strategy unchanged; no retraining, production modifications, or orders.

## Concrete change
Updated `causal_event_tape_guard_research.py` on the existing research branch. Previously `ts_ms >= fill_ms` admitted market prints sharing the fill timestamp. Now any event at exactly `fill_ms` returns `UNRESOLVED_FILL_TIMESTAMP_ORDER`, unless future work supplies a trustworthy exchange sequence/order key. Only events with `ts_ms > fill_ms` enter the replay.

Four new deterministic regression fixtures cover LONG and SHORT exact-fill-time stop prints, pre-fill prints, and post-fill stop prints. Existing eight fixtures remain, for twelve total. Tests have been added but were NOT executed by a Python runtime in this checkpoint; passing status is not claimed.

## Interpretation and limits
This is deliberately conservative: even a harmless same-millisecond print yields unresolved rather than inferred order. It prevents a false stop attribution but may reduce usable replay coverage. A trade print triggers a candidate stop, not an executable stop fill; bid/ask, order latency, gap, mark/liquidation price, fees and funding still need event-aligned data.

No matched historical replay of the 67 sequential model trades has yet been completed. Therefore monthly net equity, MTM DD, fills, liquidations and MFE captured/given back are NOT VERIFIED. The published $100->$531.16 at 3x and $100->$1308.86 at 5x remain simulation, not live evidence.

## Next data gate
Locate timestamped 67-trade ledger and per-trade matching Bybit Public Trades, L50 bid/ask, mark, funding, OI and liquidation events. Preserve missing coverage as unknown; split LOW->LONG vs HIGH->SHORT; freeze original entries and compare original versus risk 0.25%-0.5% equity/trade, total stop-risk <=1%, identical costs and no overlapping capital. Keep rejected profit overlays rejected until independent forward evidence.
