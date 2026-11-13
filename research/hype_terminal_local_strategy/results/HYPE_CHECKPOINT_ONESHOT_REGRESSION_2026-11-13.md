# HYPE strict-H1 V1 checkpoint regression — 2026-11-13 (research only)

This is a **code-level causal regression**, not a market-data replay or evidence of trading profitability. Existing frozen report specifies a one-shot checkpoint at age 285 minutes. The checked-in `h1_real_local_detector_v1.py` uses `age_minutes >= 285` and has no consumed flag; it can therefore turn a failed checkpoint into a later TRUE. This mismatch means the report's historical zero-FP statistic cannot be assumed to hold for the current live-shaped `evaluate` implementation.

## Deterministic experiment

Fixture LOW: extreme=100, pre_move_180=150 bps. At minute 285 price=101 (100 bps): frozen rule fails. At minute 286 price=103 (300 bps): existing `evaluate` would return TRUE, although the frozen one-shot rule must reject any late crossing. Fixture HIGH: extreme=100, pre_move_180=150 bps; price=98 at 285 min: valid TRUE (200 bps, 1.33 retrace fraction). Same-side LOW extension from 100 to 99 at minute 180 resets candidate age: old minute-285 checkpoint cannot confirm new hypothesis. One-shot accepted candidate cannot fire twice.

## Regression fixture (self-contained, no real orders)

```python
from dataclasses import dataclass

@dataclass
class Candidate:
    side: str
    extreme_ts: int
    extreme: float
    pre_move_bps: float
    consumed: bool = False
    invalidated: bool = False

RULES = {'LOW': .80, 'HIGH': .75}

def evaluate(c, ts, price):
    if c.invalidated or c.consumed:
        return 'WAIT'
    age = (ts - c.extreme_ts) / 60000
    if age < 285:
        return 'WAIT'
    c.consumed = True
    if age > 285:
        return 'MISSED_CHECKPOINT'
    retr = (price/c.extreme-1)*10000 if c.side=='LOW' else (c.extreme/price-1)*10000
    return 'TRUE' if retr>=130 and retr/max(c.pre_move_bps,1e-12)>=RULES[c.side] else 'WAIT'

def extension(c, ts, price, pre):
    if (c.side=='LOW' and price<c.extreme) or (c.side=='HIGH' and price>c.extreme):
        return Candidate(c.side, ts, price, pre)
    return c

def test():
    c=Candidate('LOW',0,100,150)
    assert evaluate(c,285*60000,101)=='WAIT'
    assert evaluate(c,286*60000,103)=='WAIT'
    c=Candidate('LOW',0,100,150)
    assert evaluate(c,285*60000,102)=='TRUE'
    assert evaluate(c,286*60000,102)=='WAIT'
    c=Candidate('HIGH',0,100,150)
    assert evaluate(c,285*60000,98)=='TRUE'
    c=Candidate('LOW',0,100,150)
    c=extension(c,180*60000,99,140)
    assert evaluate(c,285*60000,102)=='WAIT'
    assert evaluate(c,465*60000,101)=='TRUE'
    c=Candidate('HIGH',0,100,150)
    assert evaluate(c,286*60000,95)=='MISSED_CHECKPOINT'
    print('PASS: 6 causal checkpoint assertions')
if __name__=='__main__': test()
```

Executed fixture locally: `PASS: 6 causal checkpoint assertions`.

## Implementation decision / caveat

**Do not patch production or modify frozen thresholds.** Add a per-candidate one-shot state, reset on more-extreme same-side extension, and evaluate exactly at the scheduled checkpoint using a causally available timestamped snapshot. If no snapshot exists at the checkpoint, mark unavailable/missed; do not quietly use the next later price. For minute-granularity data, define and freeze a maximum tolerance *before* replay; avoid requiring exact millisecond equality on irregular ticks. Candidate IDs must be unique per lineage. In live state, persist consumed/invalidated flags across restarts.

## Next empirical experiment

Run a matched replay on the existing compact M1 history with the frozen checkpoint vs the current late-crossing behavior. Report first-signal TP/FP/FN, coverage and entry-distance by month, including missing checkpoint snapshots. Then materialize `HYPE-HISTORY-20260712-20261103-MASTER` and `HYPE-RICH-STRONG-*` artifacts, check available-time alignment for all 86 causal inputs, and only then test combined liquidation/book/flow interactions. No new precision or PnL is claimed here.
