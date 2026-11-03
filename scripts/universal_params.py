from __future__ import annotations
import random
from dataclasses import dataclass
SEED=20261104

@dataclass(frozen=True)
class Params:
    h1_lookback:int
    local_min_retrace:float
    local_atr_mult:float
    entry_flow:float
    consensus:int
    response_tol:float
    min_activity:float
    counter_flow:float
    weak_flow:float
    mfe_arm:float
    mfe_recoil:float
    stop_move:float
    reentry_cooldown:int
    max_reentries:int
    margin_fraction:float
    leverage:float
    pyramid_adds:int
    pyramid_trigger:float
    pyramid_fraction:float

def candidate_space(n=220):
    rng=random.Random(SEED)
    vals={
      "h1_lookback":[3,4,5,6],
      "local_min_retrace":[.004,.006,.008,.010,.012],
      "local_atr_mult":[.50,.75,1.00,1.25],
      "entry_flow":[.05,.08,.10,.12,.15,.18,.22],
      "consensus":[2,3],
      "response_tol":[0.0,.0005,.0010,.0015],
      "min_activity":[.25,.50,.75,1.00],
      "counter_flow":[.03,.05,.08,.10,.12,.15],
      "weak_flow":[-.02,0.0,.03,.05],
      "mfe_arm":[.003,.005,.008,.012,.018],
      "mfe_recoil":[.0015,.0025,.004,.006,.010],
      "stop_move":[.004,.006,.008,.012,.018],
      "reentry_cooldown":[1,2,3,5,8],
      "max_reentries":[2,4,6,10],
      "margin_fraction":[.05,.08,.10,.12,.15,.20],
      "leverage":[5.0,8.0,10.0,12.0,15.0,20.0,25.0],
      "pyramid_adds":[0,1,2],
      "pyramid_trigger":[.004,.007,.010,.015],
      "pyramid_fraction":[.25,.50,.75],
    }
    seeds=[
      Params(4,.008,.75,.12,3,.0005,.50,.08,0.0,.008,.004,.008,3,4,.10,10,1,.010,.50),
      Params(4,.010,.75,.15,3,.0005,.75,.10,0.0,.010,.004,.006,3,4,.10,15,1,.010,.50),
      Params(5,.008,1.0,.10,2,.001,.50,.08,.03,.008,.004,.008,5,6,.08,12,2,.007,.50),
      Params(4,.006,.75,.10,2,.001,.50,.05,.03,.005,.0025,.006,2,6,.12,10,1,.007,.50),
    ]
    seen=set(seeds); out=list(seeds)
    while len(out)<n:
        d={k:rng.choice(v) for k,v in vals.items()}
        if d["stop_move"]>=.75/d["leverage"]: continue
        if d["mfe_recoil"]>max(.012,d["mfe_arm"]*1.5): continue
        p=Params(**d)
        if p in seen: continue
        seen.add(p); out.append(p)
    return out
