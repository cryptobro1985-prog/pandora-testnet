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

from river import compose, drift, linear_model, preprocessing, optim

EPS=1e-12
MAX_ABS_RETURN=0.25
MAX_EXCURSION=0.35


def finite(v: Any) -> bool:
    return isinstance(v,(int,float)) and math.isfinite(v)


# All causal market + quality information remains available to learning.
# Only monotonic/opaque technical identifiers are excluded from directional alpha:
# they identify packet/run chronology rather than market state. Their derived
# quality signals (gaps, freshness, validity, latency, coverage) remain inputs.
TECHNICAL_ID_EXACT={
    "book_update_id_raw","book_sequence_raw","raw_frames_seen",
    "subscription_acks","control_frames","ws_server_ts_ms_mod_day",
}

def quality_gate(x:dict[str,Any])->dict[str,Any]:
    reasons=[]
    gap=x.get("micro_gap_seconds")
    if finite(gap) and float(gap)>10.0:reasons.append("micro_gap")
    raw_age=x.get("raw_age_ms")
    if finite(raw_age) and float(raw_age)>5000.0:reasons.append("raw_stale")
    return {"ok":not reasons,"reasons":reasons}

def clean_features(x: dict[str,Any]) -> dict[str,float]:
    """Return causal market/quality features for learning.

    We keep freshness, latency, validity, gaps and instrument context because
    their interaction with market signals can be informative. Only opaque
    monotonic transport identifiers are removed. Stale OI / invalid book families
    are still masked so stale values cannot masquerade as fresh observations.
    """
    out={}
    oi_age=x.get("oi_age_ms")
    stale_oi=finite(oi_age) and float(oi_age)>120000.0
    book_invalid=("book_valid_micro" in x and float(x.get("book_valid_micro") or 0.0)<0.5)
    for k,v in x.items():
        if k in TECHNICAL_ID_EXACT:
            continue
        if stale_oi and ("oi_" in k or k.startswith("open_interest")):
            continue
        if book_invalid and (k.startswith("l50_") or k.startswith("book_") or "depth_" in k or "absorption" in k or "replenishment" in k):
            continue
        if isinstance(v,bool):
            out[k]=1.0 if v else 0.0
        elif finite(v):
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
        linear_model.LinearRegression(
            optimizer=optim.SGD(0.001),
            intercept_lr=0.001,
            l2=1e-6,
            clip_gradient=1.0,
        )
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
    # p_up is retained as the LONG edge probability for checkpoint compatibility.
    p_up: float
    expected_return: float
    expected_max_up: float
    expected_max_down: float
    p_short: float = 0.5


class HorizonModel:
    def __init__(self):
        self.direction=new_classifier()  # legacy alias: LONG-edge classifier
        self.long_edge=self.direction
        self.short_edge=new_classifier()
        self.ret=new_regressor()
        self.max_up=new_regressor()
        self.max_down=new_regressor()
        try:
            self.drift=drift.ADWIN()
        except Exception:
            self.drift=None
        self.n=0

    def _ensure_v2(self):
        if not hasattr(self,"long_edge"):
            self.long_edge=getattr(self,"direction",new_classifier())
        if not hasattr(self,"short_edge"):
            self.short_edge=new_classifier()
        self.direction=self.long_edge

    def predict(self,x:dict[str,float])->Prediction:
        self._ensure_v2()
        lp=self.long_edge.predict_proba_one(x) or {}
        sp=self.short_edge.predict_proba_one(x) or {}
        p_long=float(lp.get(True,lp.get(1,0.5)) or 0.5)
        p_short=float(sp.get(True,sp.get(1,0.5)) or 0.5)
        r=float(self.ret.predict_one(x) or 0.0)
        u=max(0.0,min(MAX_EXCURSION,float(self.max_up.predict_one(x) or 0.0)))
        d=max(0.0,min(MAX_EXCURSION,float(self.max_down.predict_one(x) or 0.0)))
        # A terminal return cannot lie outside the path extrema.
        r=max(-d,min(u,max(-MAX_ABS_RETURN,min(MAX_ABS_RETURN,r))))
        return Prediction(
            p_up=max(0.0,min(1.0,p_long)),
            p_short=max(0.0,min(1.0,p_short)),
            expected_return=r,
            expected_max_up=u,
            expected_max_down=d,
        )

    def learn(self,x:dict[str,float],y:Outcome,cost_floor:float)->bool:
        self._ensure_v2()
        pred=self.predict(x)
        target_long=y.future_return > cost_floor
        target_short=y.future_return < -cost_floor
        self.long_edge.learn_one(x,target_long)
        self.short_edge.learn_one(x,target_short)
        ret_target=max(-MAX_ABS_RETURN,min(MAX_ABS_RETURN,float(y.future_return)))
        up_target=max(0.0,min(MAX_EXCURSION,float(y.max_up)))
        down_target=max(0.0,min(MAX_EXCURSION,float(y.max_down)))
        self.ret.learn_one(x,ret_target)
        self.max_up.learn_one(x,up_target)
        self.max_down.learn_one(x,down_target)
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
        p_long=float(getattr(pred,"p_up",0.5))
        p_short=float(getattr(pred,"p_short",1.0-p_long))
        direction=1 if p_long>=p_short else -1
        gross=direction*y.future_return
        net=gross-cost_floor
        correct=(gross>cost_floor)
        self.rows.append({
            "net":net,
            "correct":1.0 if correct else 0.0,
            "abs_error":abs(pred.expected_return-y.future_return),
            "predicted_side":"LONG" if direction==1 else "SHORT",
            "counterfactual_long_net":y.future_return-cost_floor,
            "counterfactual_short_net":-y.future_return-cost_floor,
        })

    def summary(self):
        if not self.rows:
            return {"n":0,"net_expectancy":0.0,"precision":0.0,"mae":None}
        long_rows=[r for r in self.rows if r.get("predicted_side")=="LONG"]
        short_rows=[r for r in self.rows if r.get("predicted_side")=="SHORT"]
        cf_rows=[r for r in self.rows if "counterfactual_long_net" in r]
        out={
            "n":len(self.rows),
            "net_expectancy":statistics.fmean(r["net"] for r in self.rows),
            "precision":statistics.fmean(r["correct"] for r in self.rows),
            "mae":statistics.fmean(r["abs_error"] for r in self.rows),
            "long_n":len(long_rows),
            "short_n":len(short_rows),
            "long_net_expectancy":statistics.fmean(r["net"] for r in long_rows) if long_rows else None,
            "short_net_expectancy":statistics.fmean(r["net"] for r in short_rows) if short_rows else None,
            "long_precision":statistics.fmean(r["correct"] for r in long_rows) if long_rows else None,
            "short_precision":statistics.fmean(r["correct"] for r in short_rows) if short_rows else None,
            "counterfactual_long_net_expectancy":statistics.fmean(r["counterfactual_long_net"] for r in cf_rows) if cf_rows else None,
            "counterfactual_short_net_expectancy":statistics.fmean(r["counterfactual_short_net"] for r in cf_rows) if cf_rows else None,
        }
        return out


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
        self.feature_names_seen=set()
        self.max_feature_count=0
        self.action_counts={"LONG":0,"SHORT":0,"FLAT":0}
        self.contract_version=2
        self.v2_labels=0
        self.last_enqueued_ts_ms=None

    def _round_trip_cost(self)->float:
        c=self.config.get("modeled_costs",{})
        bps=2*float(c.get("taker_fee_bps_per_side",0))+2*float(c.get("slippage_bps_per_side",0))+float(c.get("latency_bps_per_round_trip",0))
        return bps/10000.0

    def _ensure_v2(self):
        if not hasattr(self,"contract_version") or self.contract_version<2:
            for models in (getattr(self,"challenger",{}),getattr(self,"champion",{})):
                for model in models.values():
                    if hasattr(model,"_ensure_v2"):model._ensure_v2()
            self.pending=deque()
            self.champion_stats={h:ForwardStats() for h in self.horizons}
            self.challenger_stats={h:ForwardStats() for h in self.horizons}
            self.champion_ready=False
            self.contract_version=2
            self.v2_labels=0
            self.last_enqueued_ts_ms=None
        if not hasattr(self,"v2_labels"):self.v2_labels=0
        if not hasattr(self,"last_enqueued_ts_ms"):self.last_enqueued_ts_ms=None

    def observe(self,ts_ms:int,price:float,features:dict[str,Any])->dict[str,Any]:
        self._ensure_v2()
        gate=quality_gate(features)
        x=clean_features(features)
        self.feature_names_seen.update(x)
        self.max_feature_count=max(self.max_feature_count,len(x))
        if not finite(price) or price<=0 or not x:
            return {"action":"FLAT","reason":"invalid_state"}
        # Causal order: settle old examples first using the new observed price;
        # then make the new prediction. The new sample cannot train itself.
        matured=self._advance_pending(ts_ms,price)
        cp={h:self.champion[h].predict(x) for h in self.horizons}
        qp={h:self.challenger[h].predict(x) for h in self.horizons}
        spacing_s=float(self.config.get("training_sample_seconds",15))
        enqueue=(gate["ok"] and (self.last_enqueued_ts_ms is None or ts_ms-self.last_enqueued_ts_ms>=spacing_s*1000))
        if enqueue:
            self.pending.append(Pending(ts_ms,price,x,cp,qp,price,price,set()))
            self.last_enqueued_ts_ms=ts_ms
        action=self.choose_action(x, cp if self.champion_ready else qp)
        action["quality_gate"]=gate
        action["training_sample_enqueued"]=enqueue
        if not hasattr(self,"action_counts"):
            self.action_counts={"LONG":0,"SHORT":0,"FLAT":0}
        chosen=str(action.get("action","FLAT"))
        self.action_counts[chosen]=self.action_counts.get(chosen,0)+1
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
                p.done.add(h); self.labels+=1; self.v2_labels+=1; matured+=1
            if len(p.done)<len(self.horizons):
                keep.append(p)
        self.pending=keep
        self._maybe_promote()
        return matured

    def _maybe_promote(self):
        rule=self.config.get("champion",{})
        minimum=int(rule.get("min_forward_labels_before_promotion",120))
        summaries_q={h:self.challenger_stats[h].summary() for h in self.horizons}
        side_min=int(rule.get("min_side_forward_labels_before_promotion",30))

        # First champion must pass the SAME causal safety gates on ALL horizons.
        if not self.champion_ready:
            ready=True
            for h,s in summaries_q.items():
                if s["n"]<minimum or s.get("net_expectancy",0.0)<=0:
                    ready=False;break
                if min(s.get("long_n",0),s.get("short_n",0))<side_min:
                    ready=False;break
                if s.get("long_net_expectancy") is None or s.get("short_net_expectancy") is None:
                    ready=False;break
            if ready:
                self.champion=copy.deepcopy(self.challenger)
                self.champion_ready=True
                self.promotions+=1
                self._reset_forward_stats()
            return

        summaries_c={h:self.champion_stats[h].summary() for h in self.horizons}
        improvement=float(rule.get("min_relative_net_expectancy_improvement",0.05))
        mae_tol=float(rule.get("max_calibration_degradation",0.03))
        side_tol=float(rule.get("max_side_net_expectancy_degradation",0.0))
        all_horizons_ok=True
        for h in self.horizons:
            cs=summaries_c[h]; qs=summaries_q[h]
            if min(cs["n"],qs["n"])<minimum:
                all_horizons_ok=False;break
            if min(cs.get("long_n",0),cs.get("short_n",0),qs.get("long_n",0),qs.get("short_n",0))<side_min:
                all_horizons_ok=False;break
            base=max(abs(cs["net_expectancy"]),1e-6)
            better=(qs["net_expectancy"]-cs["net_expectancy"])/base>=improvement
            mae_ok=(qs["mae"] or 0)<=((cs["mae"] or 0)+mae_tol)
            side_ok=(
                qs.get("long_net_expectancy") is not None and cs.get("long_net_expectancy") is not None
                and qs.get("short_net_expectancy") is not None and cs.get("short_net_expectancy") is not None
                and qs["long_net_expectancy"]>=cs["long_net_expectancy"]-side_tol
                and qs["short_net_expectancy"]>=cs["short_net_expectancy"]-side_tol
            )
            if not (better and mae_ok and side_ok and qs["net_expectancy"]>0):
                all_horizons_ok=False;break
        if all_horizons_ok:
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
                p.expected_return=.75*p.expected_return+.25*mem["return"]
                p.expected_max_up=.75*p.expected_max_up+.25*mem["max_up"]
                p.expected_max_down=.75*p.expected_max_down+.25*mem["max_down"]
                p.expected_return=max(-p.expected_max_down,min(p.expected_max_up,p.expected_return))
            for side in (1,-1):
                model_confidence=p.p_up if side==1 else float(getattr(p,"p_short",0.5))
                agent_consensus=float(x.get("agent_consensus",0.0) or 0.0)
                agent_conf=float(x.get("agent_confidence",0.0) or 0.0)
                adversary=float(x.get("agent_adversary_risk",0.0) or 0.0)
                committee_side_conf=0.5+0.5*side*agent_consensus
                confidence=(1.0-agent_conf*0.35)*model_confidence+(agent_conf*0.35)*committee_side_conf
                if confidence<min_conf or adversary>=0.85:
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
                        # Committee participates directly: agreement adds a modest
                        # causal bonus, disagreement/adversary risk penalizes exposure.
                        alignment=side*agent_consensus
                        score+=0.05*favorable*lev*frac
                        score+=0.08*agent_conf*alignment*lev*frac
                        score-=0.20*adversary*lev*frac
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
                                "agent_consensus":agent_consensus,
                                "agent_confidence":agent_conf,
                                "agent_adversary_risk":adversary,
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
            "v2_labels":getattr(self,"v2_labels",0),
            "contract_version":getattr(self,"contract_version",1),
            "pending":len(self.pending),
            "champion_ready":self.champion_ready,
            "promotions":self.promotions,
            "drift_events":self.drift_events,
            "round_trip_cost":self.cost_floor,
            "champion":{str(h):self.champion_stats[h].summary() for h in self.horizons},
            "challenger":{str(h):self.challenger_stats[h].summary() for h in self.horizons},
            "last_action":self.last_action,
            "feature_names_seen_count":len(self.feature_names_seen),
            "max_feature_count":self.max_feature_count,
            "feature_names_seen":sorted(self.feature_names_seen),
            "action_counts":getattr(self,"action_counts",{"LONG":0,"SHORT":0,"FLAT":0}),
            "directional_contract":{
                "trained":"independent LONG edge and SHORT edge outside +/- round-trip-cost neutral band",
                "evaluated_sides":["LONG","SHORT"],"flat_baseline":True,
                "short_is_not_one_minus_long":True,
            },
            "numerical_guard":{
                "max_abs_return":MAX_ABS_RETURN,
                "max_excursion":MAX_EXCURSION,
                "regression_lr":0.001,
                "clip_gradient":1.0,
            },
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
