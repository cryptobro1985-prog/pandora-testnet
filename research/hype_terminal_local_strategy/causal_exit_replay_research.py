"""PAPER ONLY: causal single-position OHLC replay. No real orders.
Rows: ts_ms,low,high,close,opposite_confirmed,available_ts_ms,side,entry_price.
Input must already contain genuinely causal confirmation timestamps.
"""
import csv,sys

def replay(rows, exposure=.2, stop_pct=.01, cost_pct=.0025):
    if not rows: raise ValueError("empty tape")
    side=rows[0]["side"]; entry=float(rows[0]["entry_price"])
    if side not in ("LONG","SHORT") or entry<=0: raise ValueError("bad entry")
    direction=1 if side=="LONG" else -1
    stop=entry*(1-stop_pct*direction)
    mfe=0.; mae=0.; previous=-1; worst_equity=1.; reason="OPEN"; exit_price=None
    for row in rows:
        ts=int(row["ts_ms"]); available=int(row["available_ts_ms"])
        low=float(row["low"]); high=float(row["high"]); close=float(row["close"])
        if ts<=previous or not (0<low<=high and low<=close<=high):
            raise ValueError("invalid chronology or OHLC")
        previous=ts
        favorable=(high/entry-1) if direction==1 else (1-low/entry)
        adverse=(low/entry-1) if direction==1 else (1-high/entry)
        mfe=max(mfe,favorable);mae=min(mae,adverse)
        worst_equity=min(worst_equity,1+exposure*(adverse-cost_pct))
        hit=low<=stop if direction==1 else high>=stop
        if hit:
            exit_price=min(stop,close) if direction==1 else max(stop,close)
            reason="STOP";break
        if str(row["opposite_confirmed"]).lower() in ("1","true","yes") and available<=ts:
            exit_price=close;reason="OPPOSITE";break
    if exit_price is None: exit_price=close
    gross=direction*(exit_price/entry-1)
    return dict(side=side,exit_reason=reason,net_equity_pct=100*exposure*(gross-cost_pct),
                mfe_pct=100*mfe,mae_pct=100*mae,
                giveback_fraction=(mfe-gross)/mfe if mfe>0 else None,
                worst_intrabar_equity_pct=100*(worst_equity-1))

if __name__=="__main__":
    with open(sys.argv[1],newline="") as f: rows=list(csv.DictReader(f))
    print(replay(rows))
