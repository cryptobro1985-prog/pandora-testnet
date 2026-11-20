"""Research-only fail-closed entry gate for frozen D250 quote-side stop scenarios.
Does not prove historical fills or authorize trading. Standard-library only.
"""
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class Quote:
    ts: int
    bid: float
    ask: float
    mark: float

def entry_gate(side, signal_ts, quotes, stop_fraction=.01,
               max_entry_delay_ms=5000, max_spread_fraction=.005,
               max_mark_mid_divergence=.01, max_interquote_gap_ms=60000):
    if side not in ("LONG", "SHORT") or not (0 < stop_fraction < 1):
        return {"status":"BLOCKED","reason":"INVALID_INPUT"}
    if not quotes:
        return {"status":"BLOCKED","reason":"NO_QUOTES"}
    for q in quotes:
        if not all(isfinite(x) and x > 0 for x in (q.bid,q.ask,q.mark)) or q.bid>q.ask:
            return {"status":"BLOCKED","reason":"INVALID_QUOTE"}
    if any(b.ts<=a.ts or b.ts-a.ts>max_interquote_gap_ms for a,b in zip(quotes,quotes[1:])):
        return {"status":"BLOCKED","reason":"GAP_OR_ORDER"}
    future=[q for q in quotes if q.ts>signal_ts]
    if len(future)<2:
        return {"status":"BLOCKED","reason":"INSUFFICIENT_FUTURE"}
    q=future[0]
    if q.ts-signal_ts>max_entry_delay_ms:
        return {"status":"BLOCKED","reason":"STALE_ENTRY"}
    mid=(q.bid+q.ask)/2
    if (q.ask-q.bid)/mid>max_spread_fraction:
        return {"status":"BLOCKED","reason":"WIDE_SPREAD"}
    if abs(q.mark-mid)/mid>max_mark_mid_divergence:
        return {"status":"BLOCKED","reason":"MARK_DISLOCATION"}
    entry=q.ask if side=="LONG" else q.bid
    stop=entry*(1-stop_fraction if side=="LONG" else 1+stop_fraction)
    if (q.mark<=stop if side=="LONG" else q.mark>=stop):
        return {"status":"BLOCKED","reason":"STOP_ALREADY_BREACHED"}
    return {"status":"QUOTE_ONLY_ELIGIBLE","entry_ts":q.ts,"entry_quote":entry,
            "stop_trigger":stop,"verified_fill":False,
            "note":"L50 depth, fees, funding, liquidation and D250 signal provenance NOT verified"}

def tests():
    def q(t,b,a,m):return Quote(t,b,a,m)
    cases=[
        ("LONG",0,[q(1000000,99.9,100.1,98),q(1001000,99.8,100,97.9)],"STALE_ENTRY"),
        ("SHORT",0,[q(1000,99.9,100.1,102),q(2000,99.9,100.1,102.1)],"MARK_DISLOCATION"),
        ("LONG",0,[q(1000,99.9,100.1,99),q(2000,99.8,100,98.9)],"STOP_ALREADY_BREACHED"),
        ("SHORT",0,[q(1000,99.9,100.1,101),q(2000,99.8,100,101.1)],"STOP_ALREADY_BREACHED"),
        ("LONG",0,[q(1000,98,102,100),q(2000,98,102,100)],"WIDE_SPREAD"),
        ("LONG",0,[q(1000,99.9,100.1,100),q(2000,99.8,100,99.9)],"QUOTE_ONLY_ELIGIBLE"),
        ("SHORT",0,[q(1000,99.9,100.1,100),q(2000,99.8,100,99.9)],"QUOTE_ONLY_ELIGIBLE"),
    ]
    for side,ts,quotes,expected in cases:
        actual=entry_gate(side,ts,quotes)
        assert (actual["reason"] if actual["status"]=="BLOCKED" else actual["status"])==expected, (expected,actual)
    print("7 synthetic gate cases passed; historical fills verified: 0")

if __name__=="__main__":
    tests()
