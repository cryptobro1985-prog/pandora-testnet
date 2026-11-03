"""Six-hour event-driven Caterpillar research engine. PAPER ONLY: no order API."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from collections import deque
from statistics import median
from typing import Deque, Optional
import json, math, time

SYMBOLS=("ZEC","HYPE","NEAR","SOL","ENA","1000PEPE","DOGE","SUI","AAVE","WLD")
SESSION_SECONDS=6*60*60

@dataclass
class Trade:
    ts: float; price: float; notional: float; side: int  # +1 buyer aggressor, -1 seller aggressor

@dataclass
class Position:
    side:int; entry:float; opened:float; mfe:float=0.; mae:float=0.; current:float=0.

@dataclass
class State:
    symbol:str
    events:Deque[Trade]=field(default_factory=lambda:deque(maxlen=20000))
    clusters:Deque[dict]=field(default_factory=lambda:deque(maxlen=240))
    local_low:Optional[float]=None; local_high:Optional[float]=None
    structure:int=0
    position:Optional[Position]=None
    reentry_side:int=0
    last_price:float=0.; last_eval:float=0.

def mad(xs):
    if not xs:return 0.
    m=median(xs); return median([abs(x-m) for x in xs]) or 1e-12

def robust_z(x,xs):
    if len(xs)<8:return 0.
    m=median(xs); return (x-m)/(1.4826*mad(xs))

def cluster(s:State, n=120):
    ev=list(s.events)[-n:]
    if len(ev)<20:return None
    buy=sum(x.notional for x in ev if x.side==1); sell=sum(x.notional for x in ev if x.side==-1)
    total=buy+sell
    p0,p1=ev[0].price,ev[-1].price
    move=(p1/p0-1.) if p0 else 0.
    imb=(buy-sell)/total if total else 0.
    return {"ts":ev[-1].ts,"buy":buy,"sell":sell,"imb":imb,"move":move,
            "buy_eff":max(move,0)/(buy/total) if total and buy else 0.,
            "sell_eff":max(-move,0)/(sell/total) if total and sell else 0.,
            "high":max(x.price for x in ev),"low":min(x.price for x in ev)}

def flow_score(s:State,c:dict,side:int):
    hist=list(s.clusters)
    totals=[x["buy"]+x["sell"] for x in hist]
    imbs=[x["imb"]*side for x in hist]
    effs=[(x["buy_eff"] if side==1 else x["sell_eff"]) for x in hist]
    intensity=robust_z(c["buy"]+c["sell"],totals)
    imbalance=c["imb"]*side
    acceleration=imbalance-(imbs[-1] if imbs else 0.)
    efficiency=c["buy_eff"] if side==1 else c["sell_eff"]
    effz=robust_z(efficiency,effs)
    return {"intensity_z":intensity,"imbalance":imbalance,"acceleration":acceleration,
            "efficiency_z":effz,"score":intensity+2*imbalance+acceleration+effz}

def update_structure(s:State,c:dict):
    # Event-confirmed extrema: a fresh extreme becomes structural only after flow loses
    # efficiency there and opposite aggressors produce actual price response.
    prev=list(s.clusters)[-8:]
    if len(prev)<4:return
    old_low=min(x["low"] for x in prev); old_high=max(x["high"] for x in prev)
    if c["low"]<=old_low:
        sell=flow_score(s,c,-1); buy=flow_score(s,c,1)
        if sell["efficiency_z"]<=0 and buy["imbalance"]>0 and c["move"]>0:
            s.local_low=c["low"]; s.structure=1
    if c["high"]>=old_high:
        buy=flow_score(s,c,1); sell=flow_score(s,c,-1)
        if buy["efficiency_z"]<=0 and sell["imbalance"]>0 and c["move"]<0:
            s.local_high=c["high"]; s.structure=-1

def signal(s:State,c:dict):
    side=s.structure
    if side not in (-1,1):return None
    own=flow_score(s,c,side); opp=flow_score(s,c,-side)
    price_ok=c["move"]*side>0
    control=own["imbalance"]>0 and own["acceleration"]>0 and price_ok
    absorbed=own["imbalance"]>0 and c["move"]*side<=0
    if not s.position:
        if control and not absorbed and own["score"]>opp["score"]:
            return ("REENTRY" if s.reentry_side==side else "OPEN",side,own,opp)
        return None
    p=s.position
    pnl=(c["move"]*0) # mark PnL below from entry, independent of cluster start
    p.current=(c["high"] if p.side==1 else c["low"])/p.entry-1
    p.current*=p.side
    p.mfe=max(p.mfe,p.current); p.mae=min(p.mae,p.current)
    transfer=(opp["imbalance"]>0 and opp["acceleration"]>0 and c["move"]*p.side<0
              and opp["score"]>own["score"])
    structure_break=s.structure==-p.side
    if structure_break:return ("CLOSE_STRUCTURE",p.side,own,opp)
    if transfer:return ("CLOSE_FLOW",p.side,own,opp)
    return None

class ResearchEngine:
    def __init__(self,log_path="caterpillar_6h_events.jsonl"):
        self.states={x:State(x) for x in SYMBOLS}; self.log_path=log_path; self.started=time.time()
    def log(self,kind,s:State,extra):
        row={"ts":time.time(),"kind":kind,"symbol":s.symbol,"price":s.last_price,
             "structure":s.structure,"local_low":s.local_low,"local_high":s.local_high,
             "position":asdict(s.position) if s.position else None,**extra}
        with open(self.log_path,"a",encoding="utf-8") as f:f.write(json.dumps(row,separators=(",",":"))+"\n")
    def on_trade(self,symbol,price,notional,side,ts=None):
        if symbol not in self.states:return
        ts=float(ts or time.time()); s=self.states[symbol]
        if not all(map(math.isfinite,(price,notional,ts))) or price<=0 or notional<=0 or side not in (-1,1):return
        s.events.append(Trade(ts,price,notional,side)); s.last_price=price
        # Evaluation is event-count driven, never a trading timer.
        if len(s.events)<20 or len(s.events)%20:return
        c=cluster(s)
        if not c:return
        update_structure(s,c); decision=signal(s,c); s.clusters.append(c)
        if not decision:return
        kind,side,own,opp=decision
        if kind in ("OPEN","REENTRY"):
            s.position=Position(side,price,ts); s.reentry_side=0
        else:
            s.reentry_side=s.position.side if kind=="CLOSE_FLOW" else 0; s.position=None
        self.log(kind,s,{"flow":c,"own":own,"opposite":opp})
    def expired(self):return time.time()-self.started>=SESSION_SECONDS

# Adapter contract:
# engine.on_trade("HYPE", price=84.03, notional=2500.0, side=-1, ts=exchange_epoch)
# Feed ONLY Bybit Public Trades. No private API keys and no order endpoint are used.
