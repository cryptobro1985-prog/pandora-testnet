"""HYPE D250: executable quote-side stop replay, research-only.
Requires timestamped bid/ask/mark observations; synthetic tests are NOT historical fills.
Conservative market-order model: LONG buys ask/sells bid; SHORT sells bid/buys ask.
No fills are claimed between observations. Stop-market can gap through trigger.
"""
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class Tick:
    ts: int
    bid: float
    ask: float
    mark: float

def replay(side, signal_ts, ticks, stop_fraction=.01, fee_roundtrip=.0015,
           max_gap_ms=60000):
    if side not in ("LONG","SHORT") or not (0<stop_fraction<1 and fee_roundtrip>=0):
        return {"status":"BLOCKED","reason":"INPUT"}
    if not ticks or any(not all(isfinite(v) and v>0 for v in (t.bid,t.ask,t.mark))
                        or t.bid>t.ask for t in ticks):
        return {"status":"BLOCKED","reason":"INVALID_QUOTES"}
    if any(b.ts<=a.ts or b.ts-a.ts>max_gap_ms for a,b in zip(ticks,ticks[1:])):
        return {"status":"BLOCKED","reason":"ORDER_OR_GAP"}
    # Strictly after signal; never execute at a pre-signal snapshot.
    available=[t for t in ticks if t.ts>signal_ts]
    if len(available)<2:
        return {"status":"BLOCKED","reason":"INSUFFICIENT_POST_SIGNAL"}
    entry=available[0]
    price=entry.ask if side=="LONG" else entry.bid
    stop=price*(1-stop_fraction if side=="LONG" else 1+stop_fraction)
    for t in available[1:]:
        triggered=(t.mark<=stop if side=="LONG" else t.mark>=stop)
        if triggered:
            exit_price=t.bid if side=="LONG" else t.ask
            signed=(exit_price/price-1)*(1 if side=="LONG" else -1)
            # Observed quotes do not prove depth, queue priority, or actual fill.
            return {"status":"QUOTE_ONLY_STOP_SCENARIO","entry_ts":entry.ts,
                    "stop_ts":t.ts,"entry_quote":price,"stop_trigger":stop,
                    "exit_quote":exit_price,"net_return_on_notional":signed-fee_roundtrip,
                    "gap_beyond_stop_fraction":max(0,(stop-exit_price)/price if side=="LONG"
                                                    else (exit_price-stop)/price),
                    "verified_fill":False}
    return {"status":"OPEN_UNRESOLVED","entry_ts":entry.ts,
            "entry_quote":price,"verified_fill":False}

def tests():
    long=[Tick(0,99.9,100.1,100),Tick(1000,99.9,100.1,100),
          Tick(2000,98.5,98.7,98.6)]
    r=replay("LONG",0,long)
    assert r["status"]=="QUOTE_ONLY_STOP_SCENARIO"
    assert r["gap_beyond_stop_fraction"]>0 and r["net_return_on_notional"]<-.01
    short=[Tick(0,99.9,100.1,100),Tick(1000,99.9,100.1,100),
           Tick(2000,101.8,102,101.9)]
    s=replay("SHORT",0,short)
    assert s["status"]=="QUOTE_ONLY_STOP_SCENARIO" and s["gap_beyond_stop_fraction"]>0
    assert replay("LONG",0,[Tick(1000,99,100,99),Tick(100000,98,99,98)])["status"]=="BLOCKED"
    assert replay("LONG",0,[Tick(0,99,100,99)])["status"]=="BLOCKED"
    print("4 synthetic quote-side scenarios passed; historical fills verified: 0")

if __name__=="__main__":
    tests()
