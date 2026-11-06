from __future__ import annotations
"""Deterministic causal agent committee for HYPE research.

Each role reads only features available at decision time and emits:
direction in [-1,+1] (SHORT..LONG), confidence in [0,1], and risk in [0,1].
No role places orders. The committee output becomes ordinary Quant features.
"""
import math
from typing import Any

def finite(v): return isinstance(v,(int,float)) and math.isfinite(v)
def val(x,k,default=0.0):
    v=x.get(k)
    return float(v) if finite(v) else float(default)
def clip(v,lo=-1.0,hi=1.0): return max(lo,min(hi,float(v)))
def squash(v,scale=1.0):
    return math.tanh(float(v)/max(float(scale),1e-12))
def mean(xs):
    xs=[float(v) for v in xs if finite(v)]
    return sum(xs)/len(xs) if xs else 0.0
def availability(x,keys):
    return sum(1 for k in keys if finite(x.get(k)))/max(1,len(keys))

def structure_agent(x:dict[str,Any]):
    keys=["m1_close_return_1bar","m3_close_return_1bar","m5_close_return_1bar","h1_close_return_1bar",
          "dist_rolling_60m_high","dist_rolling_60m_low","dist_rolling_6h_high","dist_rolling_6h_low"]
    momentum=mean([
        squash(val(x,"m1_close_return_1bar"),.003),
        squash(val(x,"m3_close_return_1bar"),.006),
        squash(val(x,"m5_close_return_1bar"),.01),
        squash(val(x,"h1_close_return_1bar"),.025),
        squash(val(x,"ret_300s"),.01),
        squash(val(x,"ret_900s"),.02),
    ])
    # Near a rolling low favors reversal LONG only when price has started rebounding;
    # near a high mirrors this. This is context, not a future pivot label.
    low_rebound=max(val(x,"retracement_from_low_900s"),val(x,"retracement_from_low_300s"))
    high_recoil=max(val(x,"retracement_from_high_900s"),val(x,"retracement_from_high_300s"))
    local_bias=clip(low_rebound-high_recoil)
    direction=clip(.70*momentum+.30*local_bias)
    return direction, availability(x,keys), 0.0

def flow_agent(x):
    keys=["flow_imbalance_raw_15s","flow_imbalance_raw_60s","flow_imbalance_raw_300s",
          "buy_efficiency_60s","sell_efficiency_60s","buy_efficiency_300s","sell_efficiency_300s"]
    imb=mean([val(x,"flow_imbalance_raw_15s"),val(x,"flow_imbalance_raw_60s"),val(x,"flow_imbalance_raw_300s")])
    eff60=squash((val(x,"buy_efficiency_60s")-val(x,"sell_efficiency_60s"))*1e8,1.0)
    eff300=squash((val(x,"buy_efficiency_300s")-val(x,"sell_efficiency_300s"))*1e8,1.0)
    response=mean([eff60,eff300])
    direction=clip(.58*imb+.42*response)
    return direction, availability(x,keys), 0.0

def book_agent(x):
    keys=["book_imbalance_5","book_imbalance_25","bid_absorption_proxy_60s","ask_absorption_proxy_60s",
          "book_bid_add_60s","book_ask_add_60s","book_bid_cancel_60s","book_ask_cancel_60s"]
    imb=mean([val(x,"book_imbalance_5"),val(x,"book_imbalance_25")])
    absorb=squash(math.log1p(max(0,val(x,"bid_absorption_proxy_60s")))-
                   math.log1p(max(0,val(x,"ask_absorption_proxy_60s"))),1.0)
    add=val(x,"book_bid_add_60s")-val(x,"book_ask_add_60s")
    cancel=val(x,"book_ask_cancel_60s")-val(x,"book_bid_cancel_60s")
    depth_impulse=squash((add+cancel)/max(1.0,
        abs(val(x,"book_bid_add_60s"))+abs(val(x,"book_ask_add_60s"))+
        abs(val(x,"book_bid_cancel_60s"))+abs(val(x,"book_ask_cancel_60s"))),.5)
    conf=availability(x,keys)*(1.0 if val(x,"book_valid_raw",val(x,"book_valid_micro",0))>0 else .15)
    return clip(.50*imb+.30*absorb+.20*depth_impulse), clip(conf,0,1), 0.0

def oi_liq_agent(x):
    keys=["oi_delta_60s","oi_delta_300s","price_oi_interaction_60s","price_oi_interaction_300s",
          "liq_long_notional_raw_60s","liq_short_notional_raw_60s"]
    # Positive price with OI expansion is directional confirmation; liquidation
    # imbalance is interpreted as forced-flow exhaustion evidence with lower weight.
    oi=mean([squash(val(x,"price_oi_interaction_60s"),.00002),
             squash(val(x,"price_oi_interaction_300s"),.00005)])
    lng=val(x,"liq_long_notional_raw_60s"); sht=val(x,"liq_short_notional_raw_60s")
    liq=(sht-lng)/max(1.0,lng+sht)
    return clip(.72*oi+.28*liq), availability(x,keys), 0.0

def local_agent(x):
    keys=["survival_since_low_300s","survival_since_high_300s",
          "retracement_from_low_300s","retracement_from_high_300s",
          "survival_since_low_900s","survival_since_high_900s",
          "retracement_from_low_900s","retracement_from_high_900s"]
    low_surv=max(val(x,"survival_since_low_300s"),val(x,"survival_since_low_900s"))
    high_surv=max(val(x,"survival_since_high_300s"),val(x,"survival_since_high_900s"))
    low_ret=max(val(x,"retracement_from_low_300s"),val(x,"retracement_from_low_900s"))
    high_ret=max(val(x,"retracement_from_high_300s"),val(x,"retracement_from_high_900s"))
    long_score=squash(low_surv,300)*clip(low_ret,0,1)
    short_score=squash(high_surv,300)*clip(high_ret,0,1)
    return clip(long_score-short_score), availability(x,keys), 0.0

def timing_agent(x):
    keys=["positive_persistence_60s","negative_persistence_60s","positive_persistence_300s",
          "negative_persistence_300s","current_reversal_attempt_active","dominance_transitions_300s"]
    persist=mean([
        val(x,"positive_persistence_60s")-val(x,"negative_persistence_60s"),
        val(x,"positive_persistence_300s")-val(x,"negative_persistence_300s")])
    reversal=val(x,"current_reversal_attempt_active")
    # Reversal event lowers conviction, rather than forcing a direction.
    conf=availability(x,keys)*(1.0-.35*clip(reversal,0,1))
    return clip(persist), clip(conf,0,1), 0.0

def adversary_agent(x):
    gap=clip(val(x,"micro_gap_seconds")/10.0,0,1)
    seq=clip(val(x,"receipt_sequence_gaps")/3.0,0,1)
    invalid=clip(val(x,"book_invalidations_raw",val(x,"book_invalidations",0))/5.0,0,1)
    spread=clip(abs(val(x,"spread_bps"))/20.0,0,1)
    raw_age=clip(val(x,"raw_age_ms")/5000.0,0,1)
    risk=clip(mean([gap,seq,invalid,spread,raw_age]),0,1)
    return 0.0, 1.0, risk

ROLES={
    "structure":structure_agent,
    "flow":flow_agent,
    "book":book_agent,
    "oi_liq":oi_liq_agent,
    "local":local_agent,
    "timing":timing_agent,
    "adversary":adversary_agent,
}

def evaluate_agents(x:dict[str,Any])->dict[str,float]:
    rows={}
    for name,fn in ROLES.items():
        d,c,r=fn(x)
        rows[name]=(clip(d),clip(c,0,1),clip(r,0,1))
    directional=[(d,c) for name,(d,c,r) in rows.items() if name!="adversary" and c>0]
    den=sum(c for _,c in directional)
    consensus=sum(d*c for d,c in directional)/den if den else 0.0
    if directional:
        disagreement=sum(c*abs(d-consensus) for d,c in directional)/den
    else:
        disagreement=1.0
    coverage=mean([c for name,(d,c,r) in rows.items() if name!="adversary"])
    adversary=rows["adversary"][2]
    confidence=clip(coverage*(1-disagreement)*(1-adversary),0,1)
    out={
        "agent_consensus":clip(consensus),
        "agent_disagreement":clip(disagreement,0,1),
        "agent_coverage":clip(coverage,0,1),
        "agent_adversary_risk":clip(adversary,0,1),
        "agent_confidence":confidence,
    }
    for name,(d,c,r) in rows.items():
        out[f"agent_{name}_direction"]=d
        out[f"agent_{name}_confidence"]=c
        out[f"agent_{name}_risk"]=r
    return out

def augment_with_agents(x:dict[str,Any])->dict[str,float]:
    out=dict(x)
    out.update(evaluate_agents(out))
    return out
