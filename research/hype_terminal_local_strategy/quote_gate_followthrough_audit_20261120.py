"""Research-only causal stop follow-through audit. No historical fills claimed.
Usage: python quote_gate_followthrough_audit_20261120.py
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Q:
    ts: int
    bid: float
    ask: float
    mark: float

def audit(side, signal_ts, quotes, stop_fraction=.01, round_trip_fee=.0015):
    """First post-signal quote is a hypothetical immediate taker fill.
    Later quotes can only affect exit, NEVER eligibility of that earlier entry.
    Bid/ask are top-of-book only; depth/queue/actual fill not verified.
    """
    assert side in ("LONG", "SHORT")
    assert 0 < stop_fraction < 1
    assert all(q.ts > signal_ts and q.bid > 0 and q.ask >= q.bid and q.mark > 0 for q in quotes)
    assert all(a.ts < b.ts for a,b in zip(quotes, quotes[1:]))
    if len(quotes) < 2:
        return {"status":"INSUFFICIENT_QUOTES"}
    first=quotes[0]
    entry=first.ask if side=="LONG" else first.bid
    stop=entry*(1-stop_fraction if side=="LONG" else 1+stop_fraction)
    if (first.mark <= stop if side=="LONG" else first.mark >= stop):
        return {"status":"BLOCKED_AT_ENTRY"}
    for q in quotes[1:]:
        triggered=q.mark<=stop if side=="LONG" else q.mark>=stop
        if triggered:
            exit_quote=q.bid if side=="LONG" else q.ask
            gross=(exit_quote-entry)/entry*(1 if side=="LONG" else -1)
            return {"status":"STOP_TRIGGERED","entry":entry,"stop":stop,
                    "first_observed_exit_quote":exit_quote,"gross_return":gross,
                    "net_return_assumed_fee":gross-round_trip_fee,
                    "verified_fill":False,
                    "note":"Not a fill; quote may be stale or insufficient depth"}
    return {"status":"NO_OBSERVED_STOP","verified_fill":False}

def tests():
    # Both first quotes qualify under the previous quote-only gate.
    l=audit("LONG",0,[Q(1000,99.9,100.1,100),Q(2000,98.4,98.6,98.5)])
    s=audit("SHORT",0,[Q(1000,99.9,100.1,100),Q(2000,101.4,101.6,101.5)])
    assert l["status"]=="STOP_TRIGGERED" and l["gross_return"] < -.01
    assert s["status"]=="STOP_TRIGGERED" and s["gross_return"] < -.01
    print("LONG",l)
    print("SHORT",s)
    print("synthetic=2; historical_fills_verified=0")

if __name__=="__main__":
    tests()
