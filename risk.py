"""Restart-safe NEWS_ENGINE exits: local extreme + weakening only.

No trailing stop and no fixed profit-protection stop. A profitable news position
exits only after a meaningful favorable extreme has formed, price has given back
part of that move, and short-term momentum confirms weakening.
"""
import copy
import math

LOCK_TRIGGER_ROE = 0.10
MIN_EXIT_ROE = 0.075

def better(side, old, candidate):
    if old is None:
        return candidate
    return max(old, candidate) if side > 0 else min(old, candidate)

def risk_state(position):
    keys=("peak","history","last_price","last_evaluated_at","last_exit_check")
    return {key:position[key] for key in keys if key in position}

def evaluate_exit(position, price, evaluated_at):
    if not math.isfinite(price) or price<=0:
        raise ValueError("invalid market price")
    pos=copy.deepcopy(position)
    entry=float(pos["entry"]);side=int(pos["side"]);lev=float(pos["leverage"])
    if entry<=0 or lev<=0 or side not in (-1,1):
        raise ValueError("invalid position")

    history=[float(p) for p in pos.get("history",[])[-120:]
             if math.isfinite(float(p)) and float(p)>0]
    pos["peak"]=better(side,float(pos.get("peak",entry)),price)

    roe=(price/entry-1)*side*lev
    peak_roe=(float(pos["peak"])/entry-1)*side*lev

    # Original PANDORA local-extreme weakening logic.
    # Long: current quote has retreated from recent local high and recent slope is down.
    # Short: current quote has bounced from recent local low and recent slope is up.
    weak=False
    if len(history)>=6:
        recent=history[-6:]
        if side>0:
            weak=(price<max(recent) and history[-1]<history[-3])
        else:
            weak=(price>min(recent) and history[-1]>history[-3])

    giveback=max(0.0,peak_roe-roe)
    allowed=0.025 if peak_roe>=0.50 else 0.035 if peak_roe>=0.30 else 0.045 if peak_roe>=0.20 else 0.055
    profit_floor=max(MIN_EXIT_ROE,peak_roe-allowed)
    local_exit=(peak_roe>=LOCK_TRIGGER_ROE and roe<=profit_floor and weak)

    # Legacy trailing/protection state is explicitly disabled for NEWS_ENGINE.
    pos["locked"]=False
    pos["stop"]=None
    pos["trail_armed"]=False
    pos["trail_stop"]=None
    reason="local_extreme_weakening" if local_exit else None

    pos["last_price"]=price
    pos["last_evaluated_at"]=evaluated_at
    pos["last_exit_check"]={
        "roe":roe,"peak_roe":peak_roe,"giveback":giveback,
        "allowed_giveback_roe":allowed,"profit_floor_roe":profit_floor,
        "weakening":weak,"local_extreme_exit":local_exit,
        "stop":None,"trail_stop":None,"reason":reason
    }
    pos["history"]=(history+[price])[-120:]
    return pos,reason
