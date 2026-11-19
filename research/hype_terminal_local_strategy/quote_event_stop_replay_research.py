"""Research-only quote-event stop replay. No production orders or detector training.
Input events must be chronological and executable bid/ask quotes, not OHLC candles.
No book depth => fills are *top-of-book hypothetical*, NOT verified market fills.
"""
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class Event:
    ts_ms: int
    bid: float
    ask: float
    mark: float
    opposite_available: bool = False

def replay(side, entry_ts_ms, entry_vwap, events, stop_pct=0.01,
           risk_fraction=0.005, equity=100.0, roundtrip_cost_fraction=0.0015):
    if side not in ("LONG", "SHORT") or not (0 < stop_pct < 1):
        raise ValueError("invalid side/stop")
    if not (0 < risk_fraction <= 0.005) or equity <= 0 or entry_vwap <= 0:
        raise ValueError("invalid risk or entry")
    if not events:
        raise ValueError("missing quote events")
    direction = 1 if side == "LONG" else -1
    stop = entry_vwap * (1 - direction * stop_pct)
    # Cost reserve is explicitly charged once, from actual entry VWAP.
    risk_per_notional = stop_pct + roundtrip_cost_fraction
    notional = equity * risk_fraction / risk_per_notional
    quantity = notional / entry_vwap
    prev = entry_ts_ms
    best = entry_vwap
    worst = entry_vwap
    for e in events:
        if e.ts_ms <= prev or not all(isfinite(v) and v > 0 for v in (e.bid,e.ask,e.mark)) or e.bid > e.ask:
            raise ValueError("noncausal/stale/crossed quote")
        prev = e.ts_ms
        executable = e.bid if side == "LONG" else e.ask
        # Quote is observed at timestamp; stop trigger and opposite confirmation
        # at the same timestamp cannot be ordered without additional provenance.
        hit = executable <= stop if side == "LONG" else executable >= stop
        if hit and e.opposite_available:
            return dict(status="ORDER_UNRESOLVED", ts_ms=e.ts_ms)
        best = max(best, executable) if side == "LONG" else min(best, executable)
        worst = min(worst, executable) if side == "LONG" else max(worst, executable)
        if hit or e.opposite_available:
            gross = direction * (executable - entry_vwap) * quantity
            costs = notional * roundtrip_cost_fraction
            pnl = gross - costs
            mfe = max(0, direction * (best-entry_vwap) * quantity)
            mae = min(0, direction * (worst-entry_vwap) * quantity)
            return dict(status="HYPOTHETICAL_TOP_OF_BOOK", reason="STOP" if hit else "OPPOSITE",
                        ts_ms=e.ts_ms, exit_quote=executable, stop=stop, notional=notional,
                        quantity=quantity, net_pnl=pnl, mfe=mfe, mae=mae,
                        mfe_giveback=(mfe-gross)/mfe if mfe>0 else None,
                        mark=e.mark, liquidity_verified=False, liquidation_verified=False)
    return dict(status="OPEN_UNRESOLVED", last_ts_ms=prev)

def _self_test():
    long = [Event(1,100,100.1,100), Event(2,98.5,98.7,98.6)]
    a=replay("LONG",0,100,long)
    assert a["reason"]=="STOP" and a["exit_quote"]==98.5
    # Future candle close is absent by construction.
    short=[Event(1,99.9,100.1,100),Event(2,100.9,101.3,101.2)]
    b=replay("SHORT",0,100,short)
    assert b["reason"]=="STOP" and b["exit_quote"]==101.3
    assert replay("LONG",0,100,[Event(1,98,98.2,98.1,True)])["status"]=="ORDER_UNRESOLVED"
    try:
        replay("LONG",0,100,[Event(1,100,99,100)])
        raise AssertionError("crossed quote accepted")
    except ValueError:
        pass
    print("4 deterministic assertions passed; NOT a historical replay")
if __name__=="__main__":
    _self_test()
