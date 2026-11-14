"""Research-only event-ordered execution guard. Never places orders.
Input events are already normalized exchange observations; NOT OHLC candles.
This module does not infer executable liquidity or actual stop fills.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Event:
    ts_ms: int
    seq: int
    kind: str
    price: float
    available_ts_ms: int

def replay(side, entry_price, entry_ts_ms, events, stop_pct=.01):
    if side not in ("LONG", "SHORT") or entry_price <= 0 or stop_pct <= 0:
        raise ValueError("invalid position")
    direction = 1 if side == "LONG" else -1
    stop = entry_price * (1 - direction * stop_pct)
    mfe = 0.0
    mae = 0.0
    last_key = (entry_ts_ms, -1)
    exit_event = None
    for ev in events:
        key = (ev.ts_ms, ev.seq)
        if key <= last_key or ev.price <= 0 or ev.available_ts_ms > ev.ts_ms:
            raise ValueError("noncausal, invalid, or unordered event")
        last_key = key
        if ev.kind not in ("trade", "opposite_available"):
            raise ValueError("unsupported event type")
        if ev.kind == "opposite_available":
            # This is an availability notification, NOT an oracle extreme.
            exit_event = ("OPPOSITE_SIGNAL", ev.ts_ms)
            break
        favorable = direction * (ev.price / entry_price - 1)
        mfe = max(mfe, favorable)
        mae = min(mae, favorable)
        if (direction == 1 and ev.price <= stop) or (direction == -1 and ev.price >= stop):
            exit_event = ("STOP_TRIGGERED_FILL_UNKNOWN", ev.ts_ms)
            break
    return {"side": side, "stop_trigger": stop, "exit": exit_event,
            "mfe_last_trade_pct": mfe * 100, "mae_last_trade_pct": mae * 100,
            "net_pnl": None, "fill_price": None, "liquidation_count": None,
            "verified_execution": False}

def self_test():
    # Stop-first must not credit a subsequent favorable print.
    a = [Event(101,1,"trade",98,101),Event(102,1,"trade",105,102)]
    b = [Event(101,1,"trade",102,101),Event(102,1,"trade",95,102)]
    x = replay("LONG",100,100,a)
    y = replay("SHORT",100,100,b)
    assert x["mfe_last_trade_pct"] == 0 and x["exit"][0].startswith("STOP")
    assert y["mfe_last_trade_pct"] == 0 and y["exit"][0].startswith("STOP")
    z = replay("LONG",100,100,[Event(101,1,"trade",103,101),Event(102,1,"opposite_available",103,102)])
    assert round(z["mfe_last_trade_pct"],6) == 3 and z["exit"][0]=="OPPOSITE_SIGNAL"
    try:
        replay("LONG",100,100,[Event(101,1,"trade",99,102)])
        raise AssertionError("future availability accepted")
    except ValueError:
        pass
    return "4 deterministic assertions passed; synthetic only"

if __name__ == "__main__":
    print(self_test())
