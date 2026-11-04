#!/usr/bin/env python3
"""Online, research-only HYPE Quant Learner.

No order placement. The learner predicts first, waits for future data, labels the
prediction causally, then updates only the challenger. Champion promotion uses
forward labels that were not used to fit the champion.

The aspirational +100%/day target is a benchmark, never a reason to violate the
survival/liquidation constraints in config.json.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import copy
import json
import math
import pickle
import statistics
import time

from river import compose, drift, linear_model, preprocessing

EPS=1e-12


def finite(v: Any) -> bool:
    return isinstance(v,(int,float)) and math.isfinite(v)


def clean_features(x: dict[str,Any]) -> dict[str,float]:
    out={}
    for k,v in x.items():
        if isinstance(v,bool):
            out[k]=1.0 if v else 0.0
        elif finite(v):
            # keep model numerically sane while retaining direction/order
            out[k]=max(-1e9,min(1e9,float(v)))
    return out


def new_classifier():
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        linear_model.LogisticRegression()
    )


def new_regressor():
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        linear_model.LinearRegression()
    )


@dataclass
class Outcome:
    horizon_s: int
    future_return: float
    max_up: float
    max_down: float
    close_price: float
    elapsed_s: float


@dataclass
class Prediction:
    p_up: float
    expected_return: float
    expected_max_up: float
    expected_max_down: float


class HorizonModel:
    def __init__(self):
        self.direction=new_classifier()
        self.ret=new_regressor()
        self.max_up=new_regressor()
        self.max_down=new_regressor()
        try:
            self.drift=drift.ADWIN()
        except Exception:
            self.drift=None
        self.n=0

    def predict(self,x:dict[str,float])->Prediction:
        proba=self.direction.predict_proba_one(x) or {}
        p_up=float(proba.get(True,proba.get(1,0.5)) or 0.5)
        r=self.ret.predict_one(x)
        u=self.max_up.predict_one(x)
        d=self.max_down.predict_one(x)
        return Prediction(
            p_up=max(0.0,min(1.0,p_up)),
            expected_return=float(r or 0.0),
            expected_max_up=max(0.0,float(u or 0.0)),
            expected_max_down=max(0.0,float(d or 0.0)),
        )

    def learn(self,x:dict[str,float],y:Outcome,cost_floor:float)->bool:
        pred=self.predict(x)
        target_up=y.future_return > cost_floor
        self.direction.learn_one(x,target_up)
        self.ret.learn_one(x,y.future_return)
        self.max_up.learn_one(x,y.max_up)
        self.max_down.learn_one(x,y.max_down)
        self.n+=1
        drifted=False
        if self.drift is not None:
            try:
                err=abs(pred.expected_return-y.future_return)
                self.drift.update(err)
                drifted=bool(getattr(self.drift,"drift_detected",False))
            except Exception:
                pass
        return drifted


class PatternMemory:
    """Simple deterministic recent-state memory.

    It stores only matured examples. Similarity uses z-like bounded feature
    transforms already emitted by FeatureState. This is deliberately transparent
    and replayable rather than an opaque vector DB.
    """
    def __init__(self,max_examples:int=20000,neighbors:int=31):
        self.max_examples=int(max_examples)
        self.rows={}
        self.neighbors=max(3,int(neighbors))

    @staticmethod
    def _keys(x):
        preferred=(
            "ret_5s","ret_15s","ret_30s","ret_60s","ret_180s","ret_300s",
            "vol_60s","spread_bps","book_imbalance_5","book_imbalance_25",
            "flow_imbalance_5s","flow_imbalance_15s","flow_imbalance_60s",
            "oi_change_since_prev_poll_pct","liq_imbalance_60s",
            "depth_log_ratio_5","depth_log_ratio_25",
            "dist_60m_high","dist_60m_low","dist_6h_high","dist_6h_low",
            "basis_bps","long_short_holder_ratio"
        )
        return [k for k in preferred if k in x]

    def add(self,x:dict[str,float],y:Outcome):
        q=self.rows.setdefault(y.horizon_s,deque(maxlen=self.max_examples))
        q.append((dict(x),y.future_return,y.max_up,y.max_down))

    def query(self,x:dict[str,float],horizon_s:int)->dict[str,float]|None:
        rows=self.rows.get(horizon_s)
        if not rows or len(rows)<self.neighbors:
            return None
        keys=self._keys(x)
        if len(keys)<4:
            return None
        scored=[]
        # bound CPU: the newest 6000 matured states are enough for v1 pattern memory
        for rx,r,u,d in list(rows)[-6000:]:
            common=[k for k in keys if k in rx]
            if len(common)<4:
                continue
            dist=sum((x[k]-rx[k])**2 for k in common)/len(common)
            scored.append((dist,r,u,d))
        if len(scored)<self.neighbors:
            return None
        scored.sort(key=lambda z:z[0])
        nn=scored[:self.neighbors]
        weights=[1.0/(math.sqrt(max(z[0],0.0))+1e-6) for z in nn]
        den=sum(weights)
        return {
            "return":sum(w*z[1] for w,z in zip(weights,nn))/den,
            "max_up":sum(w*z[2] for w,z in zip(weights,nn))/den,
            "max_down":sum(w*z[3] for w,z in zip(weights,nn))/den,
            "n":len(nn),
        }


class ForwardStats:
    def __init__(self,maxlen=2000):
        self.rows=deque(maxlen=maxlen)

    def add(self,pred:Prediction,y:Outcome,cost_floor:float):
        direction=1 if pred.expected_return>=0 else -1
        gross=direction*y.future_return
        net=gross-cost_floor
        correct=(gross>cost_floor)
        self.rows.append({
            "net":net,
            "correct":1.0 if correct else 0.0,
            "abs_error":abs(pred.expected_return-y.future_return)
        })

    def summary(self):
        if not self.rows:
            return {"n":0,"net_expectancy":0.0,"precision":0.0,"mae":None}
        return {
            "n":len(self.rows),
            "net_expectancy":statistics.fmean(r["net"] for r in self.rows),
            "precision":statistics.fmean(r["correct"] for r in self.rows),
            "mae":statistics.fmean(r["abs_error"] for r in self.rows),
        }


@dataclass
class Pending:
    ts_ms:int
    price:float
    x:dict[str,float]
    champion_pred:dict[int,Prediction]
    challenger_pred:dict[int,Prediction]
    high:float
    low:float
    done:set[int]


class OnlineQuantLearner:
    def __init__(self,config:dict[str,Any]):
        self.config=config
        self.horizons=[int(x) for x in config["horizons_seconds"]]
        self.cost_floor=self._round_trip_cost()
        self.challenger={h:HorizonModel() for h in self.horizons}
        self.champion={h:HorizonModel() for h in self.horizons}
        self.champion_ready=False
        self.memory=PatternMemory(**config.get("pattern_memory",{}))
        self.pending=deque()
        self.champion_stats={h:ForwardStats() for h in self.horizons}
        self.challenger_stats={h:ForwardStats() for h in self.horizons}
        self.labels=0
        self.promotions=0
        self.drift_events=0
        self.created_ts_ms=int(time.time()*1000)
        self.last_action=None

    def _round_trip_cost(self)->float:
        c=self.config.get("modeled_costs",{})
        bps=2*float(c.get("taker_fee_bps_per_side",0))+2*float(c.get("slippage_bps_per_side",0))+float(c.get("latency_bps_per_round_trip",0))
        return bps/10000.0

    def observe(self,ts_ms:int,price:float,features:dict[str,Any])->dict[str,Any]:
        x=clean_features(features)
        if not finite(price) or price<=0 or not x:
            return {"action":"FLAT","reason":"invalid_state"}
        # Causal order: settle old examples first using the new observed price;
        # then make the new prediction. The new sample cannot train itself.
        matured=self._advance_pending(ts_ms,price)
        cp={h:self.champion[h].predict(x) for h in self.horizons}
        qp={h:self.challenger[h].predict(x) for h in self.horizons}
        self.pending.append(Pending(ts_ms,price,x,cp,qp,price,price,set()))
        action=self.choose_action(x, cp if self.champion_ready else qp)
        action["matured_labels"]=matured
        action["champion_ready"]=self.champion_ready
        self.last_action=action
        return action

    def _advance_pending(self,ts_ms:int,price:float)->int:
        matured=0
        keep=deque()
        for p in self.pending:
            p.high=max(p.high,price); p.low=min(p.low,price)
            elapsed=(ts_ms-p.ts_ms)/1000.0
            for h in self.horizons:
                if h in p.done or elapsed<h:
                    continue
                y=Outcome(
                    horizon_s=h,
                    future_return=price/p.price-1.0,
                    max_up=p.high/p.price-1.0,
                    max_down=1.0-p.low/p.price,
                    close_price=price,
                    elapsed_s=elapsed,
                )
                self.champion_stats[h].add(p.champion_pred[h],y,self.cost_floor)
                self.challenger_stats[h].add(p.challenger_pred[h],y,self.cost_floor)
                drifted=self.challenger[h].learn(p.x,y,self.cost_floor)
                if drifted:self.drift_events+=1
                self.memory.add(p.x,y)
                p.done.add(h); self.labels+=1; matured+=1
            if len(p.done)<len(self.horizons):
                keep.append(p)
        self.pending=keep
        self._maybe_promote()
        return matured

    def _maybe_promote(self):
        rule=self.config.get("champion",{})
        minimum=int(rule.get("min_forward_labels_before_promotion",120))
        # First champion is a warm-start snapshot of challenger after enough
        # strictly matured labels. Later promotions require true forward edge.
        shortest=min(self.horizons)
        q=self.challenger_stats[shortest].summary()
        if not self.champion_ready:
            if q["n"]>=minimum:
                self.champion=copy.deepcopy(self.challenger)
                self.champion_ready=True
                self.promotions+=1
                self._reset_forward_stats()
            return
        c=self.champion_stats[shortest].summary()
        if min(c["n"],q["n"])<minimum:
            return
        improvement=float(rule.get("min_relative_net_expectancy_improvement",0.05))
        base=max(abs(c["net_expectancy"]),1e-6)
        better=(q["net_expectancy"]-c["net_expectancy"])/base>=improvement
        mae_ok=(q["mae"] or 0)<=((c["mae"] or 0)+float(rule.get("max_calibration_degradation",0.03)))
        if better and mae_ok and q["net_expectancy"]>0:
            self.champion=copy.deepcopy(self.challenger)
            self.promotions+=1
            self._reset_forward_stats()

    def _reset_forward_stats(self):
        self.champion_stats={h:ForwardStats() for h in self.horizons}
        self.challenger_stats={h:ForwardStats() for h in self.horizons}

    def choose_action(self,x:dict[str,float],preds:dict[int,Prediction])->dict[str,Any]:
        risk=self.config.get("risk",{})
        min_conf=float(risk.get("min_confidence_to_act",0.57))
        best={"score":0.0,"action":"FLAT","leverage":0,"margin_fraction":0.0,"horizon_s":None}
        for h,p0 in preds.items():
            p=copy.copy(p0)
            mem=self.memory.query(x,h)
            if mem:
                # Blend only after enough causal memory exists; model remains primary.
                p.expected_return=.75*p.expected_return+.25*mem["return"]
                p.expected_max_up=.75*p.expected_max_up+.25*mem["max_up"]
                p.expected_max_down=.75*p.expected_max_down+.25*mem["max_down"]
            for side in (1,-1):
                confidence=p.p_up if side==1 else 1.0-p.p_up
                if confidence<min_conf:
                    continue
                expected_gross=side*p.expected_return
                favorable=p.expected_max_up if side==1 else p.expected_max_down
                adverse=p.expected_max_down if side==1 else p.expected_max_up
                if expected_gross<=self.cost_floor:
                    continue
                for lev in self.config["action_space"]["leverage"]:
                    # Approximate isolated liquidation distance for research ranking.
                    # Exact live risk tiers are intentionally not used for trading here.
                    approx_liq_distance=max(0.0,1.0/float(lev)-0.005)
                    if adverse > approx_liq_distance*float(risk.get("liquidation_safety_fraction",0.55)):
                        continue
                    for frac in self.config["action_space"]["margin_fraction"]:
                        net=(expected_gross-self.cost_floor)*lev*frac
                        dd=adverse*lev*frac
                        turnover=lev*frac
                        score=net-float(risk.get("drawdown_penalty",8.0))*dd*dd-float(risk.get("turnover_penalty",0.15))*self.cost_floor*turnover
                        # reward favorable excursion only weakly; do not chase MFE at any risk
                        score+=0.05*favorable*lev*frac
                        if score>best["score"]:
                            best={
                                "score":score,
                                "action":"LONG" if side==1 else "SHORT",
                                "leverage":lev,
                                "margin_fraction":frac,
                                "horizon_s":h,
                                "confidence":confidence,
                                "expected_return":p.expected_return,
                                "expected_favorable":favorable,
                                "expected_adverse":adverse,
                                "round_trip_cost":self.cost_floor,
                                "pattern_neighbors":None if not mem else mem["n"],
                            }
        if best["action"]=="FLAT":
            best["reason"]="no_positive_safe_edge"
        best["aspirational_daily_return_target"]=self.config.get("aspirational_daily_return_target",1.0)
        best["research_only"]=True
        return best

    def report(self)->dict[str,Any]:
        return {
            "version":self.config.get("version"),
            "research_only":True,
            "labels":self.labels,
            "pending":len(self.pending),
            "champion_ready":self.champion_ready,
            "promotions":self.promotions,
            "drift_events":self.drift_events,
            "round_trip_cost":self.cost_floor,
            "champion":{str(h):self.champion_stats[h].summary() for h in self.horizons},
            "challenger":{str(h):self.challenger_stats[h].summary() for h in self.horizons},
            "last_action":self.last_action,
        }

    def save(self,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix(path.suffix+".tmp")
        with tmp.open("wb") as f:
            pickle.dump(self,f,pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
        meta=path.with_suffix(".json")
        meta.write_text(json.dumps(self.report(),indent=2)+"\n",encoding="utf-8")

    @staticmethod
    def load(path:Path):
        with path.open("rb") as f:
            obj=pickle.load(f)
        if not isinstance(obj,OnlineQuantLearner):
            raise TypeError("checkpoint is not OnlineQuantLearner")
        return obj


def load_config(path:Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))
