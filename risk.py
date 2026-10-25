"""Universal PAPER local-extreme exit policy.

All strategies use the same market-price logic regardless of leverage:
1) track the best favorable price,
2) require a genuine favorable excursion,
3) confirm the extreme is recent,
4) exit on a small price giveback plus persistent momentum weakening.

No fixed TP, strategy-specific trailing stop, or max-hold timer is used in PAPER.
"""
import copy
import math

MIN_FAVORABLE_PRICE_MOVE = 0.0020  # 20 bps before an extreme can be harvested
MIN_GIVEBACK = 0.0005              # 5 bps minimum confirmation
MAX_GIVEBACK = 0.0025              # never give back more than 25 bps for confirmation

def better(side, old, candidate):
    if old is None:
        return candidate
    return max(old, candidate) if side > 0 else min(old, candidate)

def risk_state(position):
    keys=("peak","history","last_price","last_evaluated_at","last_exit_check")
    return {key:position[key] for key in keys if key in position}

def evaluate_exit(position, price, evaluated_at):
    if not math.isfinite(price) or price <= 0:
        raise ValueError("invalid market price")
    pos=copy.deepcopy(position)
    entry=float(pos["entry"]); side=int(pos["side"]); lev=float(pos["leverage"])
    if entry <= 0 or lev <= 0 or side not in (-1,1):
        raise ValueError("invalid position")

    history=[float(p) for p in pos.get("history",[])[-119:]
             if math.isfinite(float(p)) and float(p)>0]
    series=(history+[price])[-120:]

    prior_peak=float(pos.get("peak",entry))
    peak=better(side,prior_peak,price)
    pos["peak"]=peak

    price_move=(price/entry-1)*side
    peak_price_move=(peak/entry-1)*side
    price_giveback=max(0.0,(peak-price)/peak if side>0 else (price-peak)/peak)
    roe=price_move*lev
    peak_roe=peak_price_move*lev

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

    # Give back only a small fraction of the favorable excursion. This is
    # price-based, not leverage-based, so NEWS/PUMP/WHALE behave identically.
    allowed_giveback=max(MIN_GIVEBACK,min(MAX_GIVEBACK,max(0.0,peak_price_move)*0.15))
    weakening=(adverse_steps>=2 and slope_flip)
    local_exit=(peak_price_move>=MIN_FAVORABLE_PRICE_MOVE and peak_recent and
                weakening and price_giveback>=allowed_giveback)

    pos["locked"]=False
    pos["stop"]=None
    pos["trail_armed"]=False
    pos["trail_stop"]=None
    reason="local_extreme_weakening" if local_exit else None
    pos["last_price"]=price
    pos["last_evaluated_at"]=evaluated_at
    pos["last_exit_check"]={
        "price_move":price_move,
        "peak_price_move":peak_price_move,
        "price_giveback":price_giveback,
        "allowed_giveback_price":allowed_giveback,
        "roe":roe,
        "peak_roe":peak_roe,
        "peak_recent":peak_recent,
        "adverse_steps":adverse_steps,
        "slope_flip":slope_flip,
        "weakening":weakening,
        "local_extreme_exit":local_exit,
        "reason":reason
    }
    pos["history"]=series
    return pos,reason
