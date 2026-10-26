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
    # Profit protection is strategy-agnostic durable risk state. Keeping it in
    # the same checkpoint as peak/history means a Render restart cannot silently
    # disarm an already-earned PAPER profit lock.
    keys=("peak","history","last_price","last_evaluated_at","last_exit_check",
          "local_search_min_samples","post_liq_risk_reset_done",
          "profit_lock_armed","profit_lock_stop","profit_peak_move",
          "profit_protect_last","profit_protect_armed_at")
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
    local_peak=None
    local_price_giveback=0.0
    if len(recent)>=5:
        if side>0:
            local=max(recent)
            local_peak=local
            local_price_giveback=max(0.0,(local-price)/local)
            peak_recent=(local/entry-1)>=MIN_FAVORABLE_PRICE_MOVE
            steps=[recent[i]-recent[i-1] for i in range(1,len(recent))]
            adverse_steps=sum(x<0 for x in steps[-3:])
            slope_flip=(recent[-1]<recent[-3] and recent[-2]<=recent[-3])
        else:
            local=min(recent)
            local_peak=local
            local_price_giveback=max(0.0,(price-local)/local)
            peak_recent=(1-local/entry)>=MIN_FAVORABLE_PRICE_MOVE
            steps=[recent[i]-recent[i-1] for i in range(1,len(recent))]
            adverse_steps=sum(x>0 for x in steps[-3:])
            slope_flip=(recent[-1]>recent[-3] and recent[-2]>=recent[-3])

    # Give back only a small fraction of the favorable excursion. This is
    # price-based, not leverage-based, so NEWS/PUMP/WHALE behave identically.
    allowed_giveback=max(MIN_GIVEBACK,min(MAX_GIVEBACK,max(0.0,peak_price_move)*0.15))
    weakening=(adverse_steps>=2 and slope_flip)
    # Confirm the current observed local extreme. Requiring it to sit within
    # 15 bps of the all-time peak could permanently disable local exits after
    # a gap or a later lower high / higher low. Price thresholds are unchanged.
    local_exit=(peak_price_move>=MIN_FAVORABLE_PRICE_MOVE and peak_recent and
                weakening and local_price_giveback>=allowed_giveback)

    # A restored position or a just-triggered liquidation must build a fresh
    # post-event price path before a local extreme can be declared.
    min_local_samples=max(0,int(pos.get("local_search_min_samples",0) or 0))
    if min_local_samples and len(series)<min_local_samples:
        local_exit=False

    # Whale-liquidation PAPER strategy: a local pullback must never harvest the
    # position before the tracked liquidation level has actually been touched.
    # The mark loop latches liquidation_level_reached_at; after that latch the
    # ordinary local-extreme logic is allowed to manage the post-liquidation exit.
    features=pos.get("features") or {}
    liq=float(features.get("liquidation_price",0) or 0)
    victim=str(features.get("victim_side","")).lower()
    engine=str(features.get("engine",""))
    # The first evaluation after the liquidation latch starts a brand-new local
    # search. Pre-liquidation price history must never be reused to manufacture
    # an immediate post-liquidation exit.
    if engine.startswith("whale_liquidation") and features.get("liquidation_level_reached_at") and not pos.get("post_liq_risk_reset_done"):
        peak=price
        series=[price]
        pos["peak"]=price
        pos["history"]=[price]
        pos["local_search_min_samples"]=max(15,int(pos.get("local_search_min_samples",0) or 0))
        pos["post_liq_risk_reset_done"]=True
        local_exit=False
    pre_liq_hold=False
    remaining_liq_pct=None
    hold_limit=max(0.10,min(1.50,float(features.get("pre_liquidation_hold_limit_pct",
                       features.get("dynamic_entry_distance_pct",0.75)) or 0.75)))
    if engine.startswith("whale_liquidation") and liq>0 and victim in ("long","short") and not features.get("liquidation_level_reached_at"):
        reached=(victim=="long" and price<=liq) or (victim=="short" and price>=liq)
        if not reached:
            remaining_liq_pct=((price/liq)-1.0)*100.0 if victim=="long" else ((liq/price)-1.0)*100.0
            pre_liq_hold=True
            local_exit=False

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
        "local_peak":local_peak,
        "local_price_giveback":local_price_giveback,
        "allowed_giveback_price":allowed_giveback,
        "roe":roe,
        "peak_roe":peak_roe,
        "peak_recent":peak_recent,
        "adverse_steps":adverse_steps,
        "slope_flip":slope_flip,
        "weakening":weakening,
        "local_extreme_exit":local_exit,
        "local_search_samples":len(series),
        "local_search_min_samples":min_local_samples,
        "pre_liquidation_hold":pre_liq_hold,
        "remaining_to_liquidation_pct":remaining_liq_pct,
        "pre_liquidation_hold_limit_pct":hold_limit if engine.startswith("whale_liquidation") else None,
        "reason":reason
    }
    pos["history"]=series
    return pos,reason
