"""Universal PAPER exit policy for PANDORA.

NEWS, PUMP/DUMP and WHALE_LIQUIDATION use exactly the same exit rule:
track the best favorable price, confirm a local extreme, then exit on the first
clear loss of impulse. No fixed TP, no trailing stop, no max-hold timer.
"""
import copy
import math

LOCK_TRIGGER_ROE = 0.08
MIN_EXIT_ROE = 0.0

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

    history=[float(p) for p in pos.get("history",[])[-119:]
             if math.isfinite(float(p)) and float(p)>0]
    series=(history+[price])[-120:]

    prior_peak=float(pos.get("peak",entry))
    peak=better(side,prior_peak,price)
    pos["peak"]=peak

    roe=(price/entry-1)*side*lev
    peak_roe=(peak/entry-1)*side*lev
    giveback=max(0.0,peak_roe-roe)

    # Confirm that the best favorable quote was very recent, then require
    # two independent signs that momentum has turned away from that extreme.
    recent=series[-8:]
    peak_recent=False
    adverse_steps=0
    slope_flip=False
    if len(recent)>=5:
        if side>0:
            local=max(recent)
            peak_recent=abs(local-peak)/peak <= 0.0015
            steps=[recent[i]-recent[i-1] for i in range(1,len(recent))]
            adverse_steps=sum(x<0 for x in steps[-3:])
            slope_flip=(recent[-1]<recent[-3] and recent[-2]<=recent[-3])
        else:
            local=min(recent)
            peak_recent=abs(local-peak)/peak <= 0.0015
            steps=[recent[i]-recent[i-1] for i in range(1,len(recent))]
            adverse_steps=sum(x>0 for x in steps[-3:])
            slope_flip=(recent[-1]>recent[-3] and recent[-2]>=recent[-3])

    # Keep the giveback very tight so exits stay near the confirmed extreme.
    # Thresholds are ROE-based, therefore automatically scale with leverage.
    if peak_roe>=0.50:
        allowed=0.010
    elif peak_roe>=0.30:
        allowed=0.0125
    elif peak_roe>=0.20:
        allowed=0.015
    elif peak_roe>=0.12:
        allowed=0.020
    else:
        allowed=0.025

    weakening=(adverse_steps>=2 and slope_flip)
    local_exit=(peak_roe>=LOCK_TRIGGER_ROE and peak_recent and weakening and giveback>=allowed)

    pos["locked"]=False
    pos["stop"]=None
    pos["trail_armed"]=False
    pos["trail_stop"]=None
    reason="local_extreme_weakening" if local_exit else None

    pos["last_price"]=price
    pos["last_evaluated_at"]=evaluated_at
    pos["last_exit_check"]={
        "roe":roe,
        "peak_roe":peak_roe,
        "giveback":giveback,
        "allowed_giveback_roe":allowed,
        "peak_recent":peak_recent,
        "adverse_steps":adverse_steps,
        "slope_flip":slope_flip,
        "weakening":weakening,
        "local_extreme_exit":local_exit,
        "reason":reason
    }
    pos["history"]=series
    return pos,reason
