from __future__ import annotations
import copy, json, math, pickle, statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from river import compose, linear_model, preprocessing

from research.hype_quant.learner import OnlineQuantLearner, load_config, clean_features

def finite(v):
    return isinstance(v,(int,float)) and math.isfinite(v)

def clip(v,a=0.0,b=1.0):
    return max(a,min(b,float(v)))

def sigmoid(v):
    if v>=0:
        z=math.exp(-min(v,60)); return 1/(1+z)
    z=math.exp(max(v,-60)); return z/(1+z)

def side_name(side): return "LONG" if side>0 else "SHORT"

def binary_model():
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        linear_model.LogisticRegression(l2=0.001)
    )

def value_model():
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        linear_model.LinearRegression()
    )

@dataclass
class Candidate:
    ident:int
    side:str
    extreme_price:float
    extreme_ts_ms:int
    created_x:dict[str,float]
    invalidated_ts_ms:int|None=None
    stage_done:set[int]=field(default_factory=set)
    stage_conf:dict[int,float]=field(default_factory=dict)
    stage_retrace_bps:dict[int,float]=field(default_factory=dict)
    confirmed_stage:int|None=None
    source:str="LIVE_CANDIDATE"
    strict_hour_ms:int|None=None
    evidence:dict[str,Any]=field(default_factory=dict)

@dataclass
class LocalPending:
    candidate_id:int
    side:str
    stage_s:int
    ts_ms:int
    price:float
    x:dict[str,float]
    candidate_hour_ms:int
    strict_mature_ts_ms:int
    bounce_mature_ts_ms:int
    best_favorable:float=0.0
    worst_adverse:float=0.0
    bounce_done:bool=False

@dataclass
class EntryPending:
    ts_ms:int
    side:int
    price:float
    local_id:int
    x:dict[str,float]
    horizon_s:int
    mature_ts_ms:int
    best_favorable:float=0.0
    worst_adverse:float=0.0

@dataclass
class ExitPending:
    ts_ms:int
    side:int
    price:float
    x:dict[str,float]
    mature_ts_ms:int
    best_favorable:float=0.0
    worst_adverse:float=0.0

@dataclass
class ReentryPending:
    ts_ms:int
    side:int
    price:float
    local_id:int
    x:dict[str,float]
    mature_ts_ms:int
    best_favorable:float=0.0
    worst_adverse:float=0.0

@dataclass
class PolicyPending:
    ts_ms:int
    side:int
    mode:str
    price:float
    x:dict[str,float]
    horizon_s:int
    mature_ts_ms:int
    best_favorable:float=0.0
    worst_adverse:float=0.0

@dataclass
class FibPending:
    ts_ms:int
    key:str
    ratio:float
    kind:str
    level_price:float
    touch_price:float
    trend_side:int
    horizon_s:int
    x:dict[str,float]
    mature_ts_ms:int
    best_trend:float=0.0
    worst_trend:float=0.0

@dataclass
class PaperPosition:
    side:int
    entry_ts_ms:int
    entry_price:float
    leverage:float
    margin_fraction:float
    notional:float
    margin:float
    local_id:int
    reentry_no:int
    local_key:str|None=None
    mfe:float=0.0
    mae:float=0.0
    last_exit_sample_ms:int=0

class CaterpillarQuantLearner:
    VERSION="caterpillar-quant-v2"
    LOCAL_STAGES=(60,180,300)
    BOUNCE_FUTURE_S=1800
    EXIT_HORIZON_S=300
    ENTRY_HORIZONS=(60,180,300)
    ENTRY_SAMPLE_S=30
    REENTRY_HORIZON_S=300
    POLICY_SAMPLE_S=30
    DIRECT_POLICY_HORIZONS=(60,180,300)
    MIN_HOLD_S=60
    FIB_RETRACE_RATIOS=(0.236,0.382,0.5,0.618,0.786,1.0)
    FIB_EXTENSION_RATIOS=(1.272,1.618)
    FIB_HORIZONS=(60,180,300)
    FIB_TOUCH_BPS=7.5
    FIB_TOUCH_COOLDOWN_S=120

    def __init__(self,quant_config:dict[str,Any]):
        self.quant=OnlineQuantLearner(copy.deepcopy(quant_config))
        self.local_models={(side,stage):binary_model() for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.local_labels={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.local_pos={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.bounce_models={(side,stage):binary_model() for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.bounce_labels={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.bounce_pos={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.exit_model=binary_model(); self.reentry_model=binary_model()
        self.entry_models={h:binary_model() for h in self.ENTRY_HORIZONS}
        self.entry_labels={h:0 for h in self.ENTRY_HORIZONS}
        self.entry_pos={h:0 for h in self.ENTRY_HORIZONS}
        self.exit_labels=0; self.exit_pos=0
        self.reentry_labels=0; self.reentry_pos=0
        self.candidates={"LOW":None,"HIGH":None}
        self.candidate_seq=0
        self.local_pending:list[LocalPending]=[]
        self.entry_pending:list[EntryPending]=[]
        self.exit_pending:list[ExitPending]=[]
        self.reentry_pending:list[ReentryPending]=[]
        self.last_confirmed_local:Candidate|None=None
        self.position:PaperPosition|None=None
        self.equity=100.0
        self.peak_equity=100.0
        self.max_drawdown=0.0
        self.round_trip_cost=self.quant.cost_floor
        self.trades=[]
        self.path_equity=100.0
        self.baseline_equity=100.0
        self.baseline_position=None
        self.baseline_trades=[]
        self.actions=[]
        self.reentries=0
        self.last_exit=None
        self.last_ts_ms=None
        self.last_price=None
        self.censored=0
        self.censored_positions=0
        self.last_entry_sample_ms=0
        self.last_reentry_sample_ms=0
        self.policy_models={(mode,h):value_model() for mode in ("FLAT","POSITION") for h in self.DIRECT_POLICY_HORIZONS}
        self.policy_labels={(mode,h):0 for mode in ("FLAT","POSITION") for h in self.DIRECT_POLICY_HORIZONS}
        self.policy_target_sum={(mode,h):0.0 for mode in ("FLAT","POSITION") for h in self.DIRECT_POLICY_HORIZONS}
        self.policy_pending:list[PolicyPending]=[]
        self.last_policy_sample_ms=0
        self.last_policy_decision={}
        self.policy_version=2
        self.bootstrap_diagnostic={}
        self.structural_history={}
        self.early_local_models={"LOW":binary_model(),"HIGH":binary_model()}
        self.early_local_last_trained_hour_ms=None
        self.early_local_stats={side:{"examples":0,"positives":0,"tp":0,"fp":0,"fn":0,"tn":0,"brier_sum":0.0}
                                for side in ("LOW","HIGH")}
        self.early_local_shadow={}
        self.prediction_checks={"local":0,"bounce":0,"entry":0,"exit":0,"reentry":0,"fib":0}
        self.prediction_errors={"local":0,"bounce":0,"entry":0,"exit":0,"reentry":0,"fib":0}
        self._ensure_fib()

    def _ensure_early_local(self):
        if not hasattr(self,"early_local_models"):
            self.early_local_models={"LOW":binary_model(),"HIGH":binary_model()}
        if not hasattr(self,"early_local_last_trained_hour_ms"):
            self.early_local_last_trained_hour_ms=None
        if not hasattr(self,"early_local_stats") or not isinstance(self.early_local_stats,dict):
            self.early_local_stats={side:{"examples":0,"positives":0,"tp":0,"fp":0,"fn":0,"tn":0,"brier_sum":0.0}
                                    for side in ("LOW","HIGH")}
        for side in ("LOW","HIGH"):
            z=self.early_local_stats.setdefault(side,{})
            for k in ("examples","positives","tp","fp","fn","tn"):z.setdefault(k,0)
            z.setdefault("brier_sum",0.0)
        if not hasattr(self,"early_local_shadow"):self.early_local_shadow={}
        if not hasattr(self,"local_watch_current"):self.local_watch_current={}

    def _ensure_fib(self):
        if not hasattr(self,"prediction_checks") or not isinstance(self.prediction_checks,dict):
            self.prediction_checks={}
        if not hasattr(self,"prediction_errors") or not isinstance(self.prediction_errors,dict):
            self.prediction_errors={}
        if not hasattr(self,"fib_models"):
            self.fib_models={}
        if not hasattr(self,"fib_labels"):
            self.fib_labels={}
        if not hasattr(self,"fib_pos"):
            self.fib_pos={}
        if not hasattr(self,"fib_pending"):
            self.fib_pending=[]
        if not hasattr(self,"fib_last_touch_ms"):
            self.fib_last_touch_ms={}
        if not hasattr(self,"fib_touch_counts"):
            self.fib_touch_counts={}
        if not hasattr(self,"fib_outcomes"):
            self.fib_outcomes={}
        for kind,ratios in (("R",self.FIB_RETRACE_RATIOS),("E",self.FIB_EXTENSION_RATIOS)):
            for ratio in ratios:
                for horizon in self.FIB_HORIZONS:
                    key=f"{kind}{ratio:.3f}_{horizon}s"
                    if key not in self.fib_models:self.fib_models[key]=binary_model()
                    if key not in self.fib_labels:self.fib_labels[key]=0
                    if key not in self.fib_pos:self.fib_pos[key]=0
        self.prediction_checks.setdefault("fib",0)
        self.prediction_errors.setdefault("fib",0)

    @staticmethod
    def _fib_name(kind,ratio):
        return f"{kind}{ratio:.3f}"

    def _fib_snapshot(self,state,ts_ms,price):
        pivots=self._strict_pivots(state,ts_ms)
        if len(pivots)<2:return {"available":False,"features":{},"levels":[]}
        a,b=pivots[-2],pivots[-1]
        if a["side"]==b["side"]:return {"available":False,"features":{},"levels":[]}
        trend=1 if a["side"]=="LOW" and b["side"]=="HIGH" else -1
        start=float(a["price"]);end=float(b["price"]);span=abs(end-start)
        if span<=1e-12:return {"available":False,"features":{},"levels":[]}
        retrace=trend*(end-float(price))/span
        extension=trend*(float(price)-end)/span
        levels=[]
        distances={}
        for ratio in self.FIB_RETRACE_RATIOS:
            level=end-trend*ratio*span
            dist_bps=(float(price)/level-1.0)*10000.0 if level>0 else 0.0
            name=self._fib_name("R",ratio)
            levels.append({"kind":"RETRACEMENT","ratio":ratio,"name":name,"price":level,"distance_bps":dist_bps})
            distances[f"fib_dist_{name}_bps"]=dist_bps
            distances[f"fib_abs_dist_{name}_bps"]=abs(dist_bps)
        for ratio in self.FIB_EXTENSION_RATIOS:
            level=start+trend*ratio*span
            dist_bps=(float(price)/level-1.0)*10000.0 if level>0 else 0.0
            name=self._fib_name("E",ratio)
            levels.append({"kind":"EXTENSION","ratio":ratio,"name":name,"price":level,"distance_bps":dist_bps})
            distances[f"fib_dist_{name}_bps"]=dist_bps
            distances[f"fib_abs_dist_{name}_bps"]=abs(dist_bps)
        closest=min(levels,key=lambda z:abs(z["distance_bps"]))
        features={
            "fib_available":1.0,
            "fib_trend_side":float(trend),
            "fib_swing_span_pct":span/max(abs(start),1e-9),
            "fib_retrace_fraction":retrace,
            "fib_extension_fraction":extension,
            "fib_closest_ratio":float(closest["ratio"]),
            "fib_closest_kind":1.0 if closest["kind"]=="RETRACEMENT" else 2.0,
            "fib_closest_distance_bps":float(closest["distance_bps"]),
            "fib_closest_abs_distance_bps":abs(float(closest["distance_bps"])),
            **distances,
        }
        return {
            "available":True,"trend_side":trend,
            "swing_from":{"side":a["side"],"price":start,"hour_ms":a["hour_ms"]},
            "swing_to":{"side":b["side"],"price":end,"hour_ms":b["hour_ms"]},
            "swing_span":span,"retrace_fraction":retrace,"extension_fraction":extension,
            "closest":closest,"levels":levels,"features":features,
        }

    def _sample_fib_touches(self,ts_ms,price,x,fib):
        if not fib.get("available"):return []
        events=[]
        trend=int(fib["trend_side"])
        for level in fib.get("levels") or []:
            if abs(float(level["distance_bps"]))>self.FIB_TOUCH_BPS:continue
            base=level["name"]
            last=int(self.fib_last_touch_ms.get(base,0) or 0)
            if ts_ms-last<self.FIB_TOUCH_COOLDOWN_S*1000:continue
            self.fib_last_touch_ms[base]=int(ts_ms)
            self.fib_touch_counts[base]=int(self.fib_touch_counts.get(base,0))+1
            kind="R" if level["kind"]=="RETRACEMENT" else "E"
            for horizon in self.FIB_HORIZONS:
                key=f"{kind}{float(level['ratio']):.3f}_{horizon}s"
                fx=dict(x)
                fx.update({
                    "fib_touch":1.0,"fib_touch_ratio":float(level["ratio"]),
                    "fib_touch_kind":1.0 if kind=="R" else 2.0,
                    "fib_touch_distance_bps":float(level["distance_bps"]),
                    "fib_touch_trend_side":float(trend),
                })
                self.fib_pending.append(FibPending(
                    ts_ms=int(ts_ms),key=key,ratio=float(level["ratio"]),kind=kind,
                    level_price=float(level["price"]),touch_price=float(price),
                    trend_side=trend,horizon_s=horizon,x=clean_features(fx),
                    mature_ts_ms=int(ts_ms+horizon*1000)))
            events.append({"event":"FIB_TOUCH","ts_ms":ts_ms,"name":base,
                           "kind":level["kind"],"ratio":level["ratio"],
                           "level_price":level["price"],"touch_price":price,
                           "distance_bps":level["distance_bps"],"trend_side":side_name(trend)})
        return events

    def _advance_fib_labels(self,ts_ms,price):
        self._ensure_fib()
        keep=[]
        for p in self.fib_pending:
            move=p.trend_side*(float(price)/p.touch_price-1.0)
            p.best_trend=max(p.best_trend,move)
            p.worst_trend=max(p.worst_trend,-move)
            if ts_ms<p.mature_ts_ms:
                keep.append(p);continue
            y=move>self.round_trip_cost
            pred=self._model_p(self.fib_models[p.key],p.x)>=0.5
            self.prediction_checks["fib"]+=1
            self.prediction_errors["fib"]+=int(pred!=bool(y))
            self._learn_binary(self.fib_models[p.key],p.x,y)
            self.fib_labels[p.key]+=1;self.fib_pos[p.key]+=int(y)
            base=self._fib_name(p.kind,p.ratio)
            z=self.fib_outcomes.setdefault(base,{"matured":0,"continuation":0,"reversal":0,
                                                   "net_sum":0.0,"mfe_sum":0.0,"mae_sum":0.0})
            z["matured"]+=1;z["continuation"]+=int(y)
            z["reversal"]+=int(move<-self.round_trip_cost)
            z["net_sum"]+=move-self.round_trip_cost
            z["mfe_sum"]+=p.best_trend;z["mae_sum"]+=p.worst_trend
        self.fib_pending=keep

    def _fib_report(self):
        self._ensure_fib()
        levels={}
        names=[self._fib_name("R",r) for r in self.FIB_RETRACE_RATIOS]+[self._fib_name("E",r) for r in self.FIB_EXTENSION_RATIOS]
        for name in names:
            z=self.fib_outcomes.get(name) or {}
            n=int(z.get("matured",0) or 0)
            labels=sum(v for k,v in self.fib_labels.items() if k.startswith(name+"_"))
            pos=sum(v for k,v in self.fib_pos.items() if k.startswith(name+"_"))
            levels[name]={
                "touches":int(self.fib_touch_counts.get(name,0) or 0),
                "matured":n,"labels":labels,"continuation_positive":pos,
                "continuation_rate":(float(z.get("continuation",0))/n if n else None),
                "reversal_rate":(float(z.get("reversal",0))/n if n else None),
                "mean_net":(float(z.get("net_sum",0.0))/n if n else None),
                "mean_mfe":(float(z.get("mfe_sum",0.0))/n if n else None),
                "mean_mae":(float(z.get("mae_sum",0.0))/n if n else None),
            }
        total_labels=sum(self.fib_labels.values())
        target=len(self.fib_models)*40
        return {"enabled":True,"touch_radius_bps":self.FIB_TOUCH_BPS,
                "pending":len(self.fib_pending),"labels":total_labels,
                "training_percent":min(100.0,100.0*total_labels/max(1,target)),
                "levels":levels}

    def _model_p(self,model,x):
        try:
            p=model.predict_proba_one(clean_features(x))
            return float(p.get(True,p.get(1,0.5)))
        except Exception:
            return 0.5

    def _learn_binary(self,model,x,y):
        model.learn_one(clean_features(x),bool(y))


    def _ensure_v2(self):
        self._ensure_fib()
        self._ensure_early_local()
        if getattr(self,"policy_version",1)>=2:
            if hasattr(self.quant,"_ensure_v2"):self.quant._ensure_v2()
            self._ensure_full_graph_policy()
            self._ensure_entry_learning_policy()
            self._ensure_direct_policy()
            return
        # Local v1 labels described a 30m tradeable bounce, not a strict H1 pivot.
        # Preserve generic Quant history, but reset policy heads to the corrected contract.
        self.LOCAL_STAGES=(60,180,300)
        self.local_models={(side,stage):binary_model() for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.local_labels={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.local_pos={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.bounce_models={(side,stage):binary_model() for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.bounce_labels={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.bounce_pos={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.exit_model=binary_model();self.reentry_model=binary_model()
        self.entry_models={h:binary_model() for h in self.ENTRY_HORIZONS}
        self.entry_labels={h:0 for h in self.ENTRY_HORIZONS}
        self.entry_pos={h:0 for h in self.ENTRY_HORIZONS}
        self.exit_labels=self.exit_pos=self.reentry_labels=self.reentry_pos=0
        self.local_pending=[];self.entry_pending=[];self.exit_pending=[];self.reentry_pending=[]
        self.candidates={"LOW":None,"HIGH":None};self.last_confirmed_local=None
        self.last_entry_sample_ms=0
        self.last_reentry_sample_ms=0
        self.bootstrap_diagnostic=getattr(self,"bootstrap_diagnostic",{})
        self.censored_positions=getattr(self,"censored_positions",0)
        self.prediction_checks={"local":0,"bounce":0,"entry":0,"exit":0,"reentry":0,"fib":0}
        self.prediction_errors={"local":0,"bounce":0,"entry":0,"exit":0,"reentry":0,"fib":0}
        self._ensure_fib()
        self.policy_version=2
        if hasattr(self.quant,"_ensure_v2"):self.quant._ensure_v2()
        self._ensure_full_graph_policy()
        self._ensure_entry_learning_policy()
        self._ensure_direct_policy()

    def _ensure_direct_policy(self):
        if getattr(self,"policy_contract_version",0)>=6:
            if not hasattr(self,"policy_models"):
                self.policy_models={(mode,h):value_model() for mode in ("FLAT","POSITION") for h in self.DIRECT_POLICY_HORIZONS}
            if not hasattr(self,"policy_labels"):
                self.policy_labels={(mode,h):0 for mode in ("FLAT","POSITION") for h in self.DIRECT_POLICY_HORIZONS}
            if not hasattr(self,"policy_target_sum"):
                self.policy_target_sum={(mode,h):0.0 for mode in ("FLAT","POSITION") for h in self.DIRECT_POLICY_HORIZONS}
            if not hasattr(self,"policy_pending"):self.policy_pending=[]
            if not hasattr(self,"last_policy_sample_ms"):self.last_policy_sample_ms=0
            if not hasattr(self,"last_policy_decision"):self.last_policy_decision={}
            return
        old_trades=list(getattr(self,"trades",[]) or [])
        old_equity=float(getattr(self,"equity",100.0) or 100.0)
        gp=sum(max(0.0,float(t.get("pnl") or 0.0)) for t in old_trades)
        gl=-sum(min(0.0,float(t.get("pnl") or 0.0)) for t in old_trades)
        caps=[float(t["mfe_capture_ratio"]) for t in old_trades if finite(t.get("mfe_capture_ratio"))]
        archive={
            "policy_contract_version":getattr(self,"policy_contract_version",0),
            "equity":old_equity,
            "return_pct":(old_equity/100.0-1.0)*100.0,
            "closed_trades":len(old_trades),
            "reentries":int(getattr(self,"reentries",0) or 0),
            "win_rate":(sum(float(t.get("pnl") or 0.0)>0 for t in old_trades)/len(old_trades) if old_trades else None),
            "profit_factor":(gp/gl if gl>0 else None),
            "mean_mfe_capture_ratio":(statistics.fmean(caps) if caps else None),
            "reason":"manual-gated Entry/Exit/Re-entry contract retired; direct causal policy v6 now learns actions",
        }
        archives=list(getattr(self,"legacy_paper_archives",[]) or [])
        prev=getattr(self,"legacy_paper_archive",None)
        if isinstance(prev,dict) and prev not in archives:archives.append(prev)
        archives.append(archive)
        self.legacy_paper_archives=archives[-8:]
        self.legacy_paper_archive=archive

        self.policy_models={(mode,h):value_model() for mode in ("FLAT","POSITION") for h in self.DIRECT_POLICY_HORIZONS}
        self.policy_labels={(mode,h):0 for mode in ("FLAT","POSITION") for h in self.DIRECT_POLICY_HORIZONS}
        self.policy_target_sum={(mode,h):0.0 for mode in ("FLAT","POSITION") for h in self.DIRECT_POLICY_HORIZONS}
        self.policy_pending=[];self.last_policy_sample_ms=0;self.last_policy_decision={}
        self.position=None;self.last_exit=None
        self.equity=100.0;self.peak_equity=100.0;self.max_drawdown=0.0
        self.trades=[];self.path_equity=100.0;self.reentries=0
        self.baseline_equity=100.0;self.baseline_position=None;self.baseline_trades=[]
        self.policy_contract_version=6

    def _ensure_mfe_caterpillar_policy(self):
        if getattr(self,"policy_contract_version",0)>=5:
            if not hasattr(self,"legacy_paper_archives"):self.legacy_paper_archives=[]
            return
        old_trades=list(getattr(self,"trades",[]) or [])
        old_equity=float(getattr(self,"equity",100.0) or 100.0)
        gp=sum(max(0.0,float(t.get("pnl") or 0.0)) for t in old_trades)
        gl=-sum(min(0.0,float(t.get("pnl") or 0.0)) for t in old_trades)
        caps=[float(t["mfe_capture_ratio"]) for t in old_trades if finite(t.get("mfe_capture_ratio"))]
        archive={
            "policy_contract_version":getattr(self,"policy_contract_version",0),
            "equity":old_equity,
            "return_pct":(old_equity/100.0-1.0)*100.0,
            "closed_trades":len(old_trades),
            "reentries":int(getattr(self,"reentries",0) or 0),
            "win_rate":(sum(float(t.get("pnl") or 0.0)>0 for t in old_trades)/len(old_trades) if old_trades else None),
            "profit_factor":(gp/gl if gl>0 else None),
            "mean_mfe_capture_ratio":(statistics.fmean(caps) if caps else None),
            "reason":"v4 terminal-return entry / generic 5m exit contract retired; retained for audit only",
        }
        archives=list(getattr(self,"legacy_paper_archives",[]) or [])
        prev=getattr(self,"legacy_paper_archive",None)
        if isinstance(prev,dict) and prev not in archives:archives.append(prev)
        archives.append(archive)
        self.legacy_paper_archives=archives[-8:]
        self.legacy_paper_archive=archive

        # New Caterpillar contract learns the actual objective:
        # entry -> usable favorable excursion, exit -> preserve accumulated MFE,
        # re-entry -> renewed same-leg impulse after a pause.
        self.entry_models={h:binary_model() for h in self.ENTRY_HORIZONS}
        self.entry_labels={h:0 for h in self.ENTRY_HORIZONS}
        self.entry_pos={h:0 for h in self.ENTRY_HORIZONS}
        self.exit_model=binary_model();self.reentry_model=binary_model()
        self.exit_labels=self.exit_pos=self.reentry_labels=self.reentry_pos=0
        self.entry_pending=[];self.exit_pending=[];self.reentry_pending=[]
        self.last_entry_sample_ms=0;self.last_reentry_sample_ms=0
        self.position=None;self.last_exit=None
        self.equity=100.0;self.peak_equity=100.0;self.max_drawdown=0.0
        self.trades=[];self.path_equity=100.0;self.reentries=0
        self.baseline_equity=100.0;self.baseline_position=None;self.baseline_trades=[]
        for k in ("entry","exit","reentry"):
            self.prediction_checks[k]=0;self.prediction_errors[k]=0
        self.policy_contract_version=5

    def _ensure_entry_learning_policy(self):
        if getattr(self,"policy_contract_version",0)>=4:
            if not hasattr(self,"legacy_paper_archive"):self.legacy_paper_archive=None
            if not hasattr(self,"entry_models"):
                self.entry_models={h:binary_model() for h in self.ENTRY_HORIZONS}
                self.entry_labels={h:0 for h in self.ENTRY_HORIZONS}
                self.entry_pos={h:0 for h in self.ENTRY_HORIZONS}
                self.entry_pending=[];self.last_entry_sample_ms=0
            self.prediction_checks.setdefault("entry",0)
            self.prediction_errors.setdefault("entry",0)
            return
        old_trades=list(getattr(self,"trades",[]) or [])
        old_equity=float(getattr(self,"equity",100.0) or 100.0)
        self.legacy_paper_archive={
            "policy_contract_version":getattr(self,"policy_contract_version",0),
            "equity":old_equity,
            "return_pct":(old_equity/100.0-1.0)*100.0,
            "closed_trades":len(old_trades),
            "reentries":int(getattr(self,"reentries",0) or 0),
            "reason":"blind strict-local entry/re-entry policy retired; retained for audit only",
        }
        self.entry_models={h:binary_model() for h in self.ENTRY_HORIZONS}
        self.entry_labels={h:0 for h in self.ENTRY_HORIZONS}
        self.entry_pos={h:0 for h in self.ENTRY_HORIZONS}
        self.entry_pending=[];self.last_entry_sample_ms=0
        self.position=None;self.last_exit=None
        self.equity=100.0;self.peak_equity=100.0;self.max_drawdown=0.0
        self.trades=[];self.path_equity=100.0;self.reentries=0
        self.baseline_equity=100.0;self.baseline_position=None;self.baseline_trades=[]
        self.prediction_checks.setdefault("entry",0)
        self.prediction_errors.setdefault("entry",0)
        self.policy_contract_version=4

    def _ensure_full_graph_policy(self):
        if getattr(self,"policy_contract_version",0)>=3:
            if not hasattr(self,"structural_history"):self.structural_history={}
            return
        # Contract changed materially: old provisional-window policy labels/PAPER
        # are not comparable. Preserve generic Quant learning and all raw files,
        # but restart Local/Caterpillar policy heads on the full-graph target.
        self.local_models={(side,stage):binary_model() for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.local_labels={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.local_pos={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.bounce_models={(side,stage):binary_model() for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.bounce_labels={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.bounce_pos={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.exit_model=binary_model();self.reentry_model=binary_model()
        self.entry_models={h:binary_model() for h in self.ENTRY_HORIZONS}
        self.entry_labels={h:0 for h in self.ENTRY_HORIZONS}
        self.entry_pos={h:0 for h in self.ENTRY_HORIZONS}
        self.exit_labels=self.exit_pos=self.reentry_labels=self.reentry_pos=0
        self.local_pending=[];self.entry_pending=[];self.exit_pending=[];self.reentry_pending=[]
        self.candidates={"LOW":None,"HIGH":None};self.last_confirmed_local=None
        self.position=None;self.last_exit=None;self.last_entry_sample_ms=0;self.last_reentry_sample_ms=0
        self.equity=100.0;self.peak_equity=100.0;self.max_drawdown=0.0
        self.trades=[];self.path_equity=100.0;self.reentries=0
        self.baseline_equity=100.0;self.baseline_position=None;self.baseline_trades=[]
        self.actions=[];self.structural_history={}
        self.prediction_checks={"local":0,"bounce":0,"entry":0,"exit":0,"reentry":0,"fib":0}
        self.prediction_errors={"local":0,"bounce":0,"entry":0,"exit":0,"reentry":0,"fib":0}
        self._ensure_fib()
        self.policy_contract_version=3

    def _completed_h1(self,state,ts_ms):
        rows=[]
        for start in sorted(state.candles.get("60",{})):
            if start+3_600_000<=ts_ms:
                b=state.candles["60"][start]
                if finite(b.get("high")) and finite(b.get("low")):
                    rows.append({"start_ms":int(start),"high":float(b["high"]),"low":float(b["low"]),
                                 "open":float(b.get("open") or b["low"]),"close":float(b.get("close") or b["high"])})
        return rows

    @staticmethod
    def _h1_early_features(rows,i):
        if i<6 or i>=len(rows):return None
        cur=rows[i];past=rows[i-6:i]
        win=past+[cur]
        if any(b["start_ms"]!=a["start_ms"]+3_600_000 for a,b in zip(win,win[1:])):return None
        past_hi=max(z["high"] for z in past);past_lo=min(z["low"] for z in past)
        span=max(past_hi-past_lo,1e-9);rng=max(cur["high"]-cur["low"],1e-9)
        closes=[z["close"] for z in past];ranges=[max(z["high"]-z["low"],1e-9) for z in past]
        return {
            "h1_high_break_bps":(cur["high"]/max(past_hi,1e-9)-1.0)*10000.0,
            "h1_low_break_bps":(past_lo/max(cur["low"],1e-9)-1.0)*10000.0,
            "h1_high_position":(cur["high"]-past_lo)/span,
            "h1_low_position":(cur["low"]-past_lo)/span,
            "h1_close_position":(cur["close"]-cur["low"])/rng,
            "h1_body_bps":(cur["close"]/max(cur["open"],1e-9)-1.0)*10000.0,
            "h1_range_bps":(cur["high"]/max(cur["low"],1e-9)-1.0)*10000.0,
            "h1_upper_wick_share":max(0.0,cur["high"]-max(cur["open"],cur["close"]))/rng,
            "h1_lower_wick_share":max(0.0,min(cur["open"],cur["close"])-cur["low"])/rng,
            "h1_close_trend_6_bps":(cur["close"]/max(closes[0],1e-9)-1.0)*10000.0,
            "h1_close_trend_3_bps":(cur["close"]/max(closes[-3],1e-9)-1.0)*10000.0,
            "h1_prev_range_mean_bps":statistics.mean(ranges)/max(statistics.mean(closes),1e-9)*10000.0,
            "h1_range_vs_prev_mean":rng/max(statistics.mean(ranges),1e-9),
            "h1_prev_close_to_high_bps":(past_hi/max(cur["close"],1e-9)-1.0)*10000.0,
            "h1_prev_low_to_close_bps":(cur["close"]/max(past_lo,1e-9)-1.0)*10000.0,
        }

    def _train_early_local_history(self,state,ts_ms):
        self._ensure_early_local()
        rows=self._completed_h1(state,ts_ms)
        if len(rows)<9:return
        last=self.early_local_last_trained_hour_ms
        for i in range(6,len(rows)-2):
            row=rows[i]
            if last is not None and row["start_ms"]<=int(last):continue
            win=rows[i-6:i+3]
            if len(win)!=9 or any(b["start_ms"]!=a["start_ms"]+3_600_000 for a,b in zip(win,win[1:])):continue
            x=self._h1_early_features(rows,i)
            if not x:continue
            past=rows[i-6:i];future=rows[i+1:i+3]
            hi=row["high"]>max(z["high"] for z in past) and row["high"]>=max(z["high"] for z in future)
            lo=row["low"]<min(z["low"] for z in past) and row["low"]<=min(z["low"] for z in future)
            if hi and lo:hi=lo=False
            for side,y in (("HIGH",hi),("LOW",lo)):
                model=self.early_local_models[side];p=self._model_p(model,x);pred=p>=0.5
                st=self.early_local_stats[side]
                st["examples"]+=1;st["positives"]+=int(y);st["brier_sum"]+=(p-float(y))**2
                if pred and y:st["tp"]+=1
                elif pred and not y:st["fp"]+=1
                elif not pred and y:st["fn"]+=1
                else:st["tn"]+=1
                self._learn_binary(model,x,y)
            self.early_local_last_trained_hour_ms=int(row["start_ms"])
        i=len(rows)-1;x=self._h1_early_features(rows,i)
        if x:
            low_p=self._model_p(self.early_local_models["LOW"],x)
            high_p=self._model_p(self.early_local_models["HIGH"],x)
            side="LOW" if low_p>high_p else "HIGH"
            self.early_local_shadow={
                "hour_ms":int(rows[i]["start_ms"]),
                "price":float(rows[i]["low"] if side=="LOW" else rows[i]["high"]),
                "side":side,"low_probability":low_p,"high_probability":high_p,
                "confidence":max(low_p,high_p),"research_only":True,"trading_enabled":False,
                "note":"causal H1 shadow forecast before K2 confirmation; not used for PAPER entries until validated",
            }

    def _early_local_report(self):
        self._ensure_early_local();metrics={}
        for side in ("LOW","HIGH"):
            z=self.early_local_stats[side];n=max(1,int(z["examples"]))
            tp=int(z["tp"]);fp=int(z["fp"]);fn=int(z["fn"])
            metrics[side]={"examples":int(z["examples"]),"positives":int(z["positives"]),
                           "precision":tp/max(1,tp+fp),"recall":tp/max(1,tp+fn),
                           "brier":float(z["brier_sum"])/n,
                           "tp":tp,"fp":fp,"fn":fn,"tn":int(z["tn"])}
        return {"last_trained_hour_ms":self.early_local_last_trained_hour_ms,
                "metrics":metrics,"shadow":self.early_local_shadow,
                "trading_enabled":False,
                "leakage_guard":"features use only current/past H1; K2 future is used only for matured labels"}

    def _strict_pivots(self,state,ts_ms):
        rows=self._completed_h1(state,ts_ms)
        raw=[]
        for i in range(6,len(rows)-2):
            row=rows[i];past=rows[i-6:i];future=rows[i+1:i+3]
            # Missing completed hours break the reference label.
            win=rows[i-6:i+3]
            if any(b["start_ms"]!=a["start_ms"]+3_600_000 for a,b in zip(win,win[1:])):
                continue
            hi=row["high"]>max(x["high"] for x in past) and row["high"]>=max(x["high"] for x in future)
            lo=row["low"]<min(x["low"] for x in past) and row["low"]<=min(x["low"] for x in future)
            if hi==lo:continue
            side="HIGH" if hi else "LOW"
            price=row["high"] if hi else row["low"]
            item={"side":side,"price":price,"hour_ms":row["start_ms"],
                  "available_ms":row["start_ms"]+3*3_600_000,
                  "confirm_price":future[-1]["close"],
                  "evidence":{
                      "rule":"H1_L6_K2_STRICT",
                      "left_hours":6,"right_hours":2,
                      "past_high_max":max(x["high"] for x in past),
                      "past_low_min":min(x["low"] for x in past),
                      "future_high_max":max(x["high"] for x in future),
                      "future_low_min":min(x["low"] for x in future),
                      "pivot_high":row["high"],"pivot_low":row["low"],
                      "pivot_open":row["open"],"pivot_close":row["close"],
                  }}
            if raw and raw[-1]["side"]==side:
                better=price>raw[-1]["price"] if side=="HIGH" else price<raw[-1]["price"]
                if better:raw[-1]=item
            else:raw.append(item)
        return raw

    def _strict_candidate_outcome(self,state,pending,ts_ms):
        if ts_ms<pending.strict_mature_ts_ms:return None
        rows={r["start_ms"]:r for r in self._completed_h1(state,ts_ms)}
        h=pending.candidate_hour_ms
        needed=[h-6*3_600_000,h-5*3_600_000,h-4*3_600_000,h-3*3_600_000,
                h-2*3_600_000,h-1*3_600_000,h,h+3_600_000,h+2*3_600_000]
        if any(k not in rows for k in needed):return False
        row=rows[h];past=[rows[h-j*3_600_000] for j in range(6,0,-1)]
        future=[rows[h+3_600_000],rows[h+2*3_600_000]]
        hi=row["high"]>max(z["high"] for z in past) and row["high"]>=max(z["high"] for z in future)
        lo=row["low"]<min(z["low"] for z in past) and row["low"]<=min(z["low"] for z in future)
        if hi and lo:return False
        return bool(lo if pending.side=="LOW" else hi)

    def _sync_strict_local(self,state,ts_ms,price,x):
        pivots=self._strict_pivots(state,ts_ms)
        if not pivots:return []
        latest=pivots[-1]
        current=self.last_confirmed_local
        cur_hour=getattr(current,"strict_hour_ms",None) if current is not None else None
        if current is not None and getattr(current,"source",None)=="STRICT_H1_CONFIRMED" and cur_hour==latest["hour_ms"]:
            current.extreme_price=float(latest["price"])
            current.evidence=dict(latest.get("evidence") or {})
            current.stage_conf[0]=0.99
            return []
        self.candidate_seq+=1
        c=Candidate(self.candidate_seq,latest["side"],latest["price"],latest["available_ms"],clean_features(x),
                    confirmed_stage=0,source="STRICT_H1_CONFIRMED",strict_hour_ms=latest["hour_ms"],
                    evidence=dict(latest.get("evidence") or {}))
        c.stage_conf[0]=0.99
        self.candidates[latest["side"]]=c
        self.last_confirmed_local=c
        self._baseline_on_local(c,ts_ms,price)
        # If PAPER is already aligned with the same direction, re-anchor it to the
        # actual structural local rather than closing/reopening due to a restart.
        if self.position is not None:
            side=1 if c.side=="LOW" else -1
            if self.position.side==side:
                self.position.local_id=c.ident
                self.position.local_key=self._local_key(c)
        return [{"event":"STRICT_H1_LOCAL_SYNC","ts_ms":ts_ms,"side":latest["side"],
                 "price":latest["price"],"hour_ms":latest["hour_ms"],"available_ms":latest["available_ms"],
                 "confirm_price":latest.get("confirm_price"),"candidate_id":c.ident,
                 "evidence":latest.get("evidence") or {}}]


    def _m1_extreme_order(self,state,hour_ms,low_price,high_price):
        rows=[]
        for start in sorted(state.candles.get("1",{})):
            if hour_ms<=start<hour_ms+3_600_000:
                b=state.candles["1"][start]
                if finite(b.get("low")) and finite(b.get("high")):
                    rows.append((int(start),float(b["low"]),float(b["high"])))
        if not rows:return None
        low_row=min(rows,key=lambda z:z[1]);high_row=max(rows,key=lambda z:z[2])
        # Do not require exact equality: REST/WS normalization can differ by one tick.
        low_tol=max(1e-9,abs(low_price)*2e-6); high_tol=max(1e-9,abs(high_price)*2e-6)
        if abs(low_row[1]-low_price)>low_tol or abs(high_row[2]-high_price)>high_tol:
            return None
        if low_row[0]==high_row[0]:return None
        return "LOW" if low_row[0]>high_row[0] else "HIGH"

    def _bootstrap_provisional_local(self,state,ts_ms,price,x):
        """Recover the newest already-observed H1 extreme when the daemon starts late.

        This is NOT a strict label. It is a causal candidate used immediately by
        Caterpillar; the strict L6/K2 teacher settles it only after K2 becomes
        available. That lets policy learning start now without future leakage.
        """
        rows=self._completed_h1(state,ts_ms)
        if len(rows)<6:return []
        use=rows[-6:]
        low_row=min(use,key=lambda z:z["low"]); high_row=max(use,key=lambda z:z["high"])
        self.bootstrap_diagnostic={
            "completed_h1":len(rows),
            "low_hour_ms":low_row["start_ms"],"low_price":low_row["low"],
            "high_hour_ms":high_row["start_ms"],"high_price":high_row["high"],
            "resolution":"H1_RECENCY",
        }
        if low_row["start_ms"]==high_row["start_ms"]:
            side=self._m1_extreme_order(state,low_row["start_ms"],low_row["low"],high_row["high"])
            self.bootstrap_diagnostic["resolution"]="M1_INTRAHOUR_ORDER"
            self.bootstrap_diagnostic["m1_resolved_side"]=side
            if side is None:
                self.bootstrap_diagnostic["reason"]="AMBIGUOUS_SAME_H1_NO_M1_ORDER"
                return []
        else:
            side="LOW" if low_row["start_ms"]>high_row["start_ms"] else "HIGH"
        row=low_row if side=="LOW" else high_row
        self.bootstrap_diagnostic["selected_side"]=side
        extreme=row["low"] if side=="LOW" else row["high"]
        hour=row["start_ms"]
        existing=self.candidates.get(side)
        if existing is not None and getattr(existing,"strict_hour_ms",None)==hour:
            return []
        current=self.last_confirmed_local
        cur_hour=getattr(current,"strict_hour_ms",None) if current is not None else None
        if cur_hour is not None and cur_hour>=hour:return []
        self.candidate_seq+=1
        # We know the completed H1 extreme only at the bar close.
        c=Candidate(self.candidate_seq,side,float(extreme),hour+3_600_000,clean_features(x),
                    source="PROVISIONAL_H1_EXTREME",strict_hour_ms=hour)
        self.candidates[side]=c
        return [{"event":"PROVISIONAL_H1_LOCAL_BOOTSTRAP","ts_ms":ts_ms,"side":side,
                 "price":extreme,"hour_ms":hour,"candidate_id":c.ident}]

    def _h1_extremes(self,state,ts_ms):
        rows=[]
        for start in sorted(state.candles.get("60",{})):
            if start+3_600_000<=ts_ms:
                b=state.candles["60"][start]
                if finite(b.get("high")) and finite(b.get("low")):
                    rows.append(b)
        if len(rows)<6:return None
        use=rows[-6:]
        return min(float(b["low"]) for b in use),max(float(b["high"]) for b in use)

    def _candidate_x(self,x,c,ts_ms,price):
        sign=1.0 if c.side=="LOW" else -1.0
        out=dict(x)
        out["cq_candidate_side"]=sign
        out["cq_candidate_age_s"]=max(0.0,(ts_ms-c.extreme_ts_ms)/1000.0)
        out["cq_retrace_bps"]=(price/c.extreme_price-1.0)*sign*10000.0
        out["cq_agent_alignment"]=sign*float(x.get("agent_consensus",0.0) or 0.0)
        out["cq_flow_alignment"]=sign*float(x.get("flow_imbalance_raw_60s",x.get("flow_imbalance_60s",0.0)) or 0.0)
        out["cq_book_alignment"]=sign*float(x.get("book_imbalance_25",x.get("book_imbalance_raw_25",0.0)) or 0.0)
        oi=x.get("price_oi_interaction_60s",x.get("oi_change_since_prev_poll_pct"))
        if finite(oi):out["cq_oi_context"]=sign*float(oi)
        return out

    def _position_x(self,x,ts_ms,price,quant_decision):
        p=self.position
        out=dict(x)
        if p is None:return out
        cur=p.side*(price/p.entry_price-1.0)
        give=max(0.0,p.mfe-cur)
        out.update({
            "cq_position_side":float(p.side),
            "cq_position_return":cur,
            "cq_position_mfe":p.mfe,
            "cq_position_mae":p.mae,
            "cq_mfe_giveback":give,
            "cq_mfe_giveback_ratio":give/max(p.mfe,1e-9) if p.mfe>0 else 0.0,
            "cq_position_age_s":(ts_ms-p.entry_ts_ms)/1000.0,
            "cq_quant_same_side":1.0 if quant_decision.get("action")==side_name(p.side) else 0.0,
            "cq_quant_opposite":1.0 if quant_decision.get("action")==side_name(-p.side) else 0.0,
            "cq_quant_score":float(quant_decision.get("score",0.0) or 0.0),
            "cq_agent_same_side":p.side*float(x.get("agent_consensus",0.0) or 0.0),
        })
        return out

    def _invalidate_candidate(self,c,ts_ms):
        if c is None or c.invalidated_ts_ms is not None:return
        c.invalidated_ts_ms=ts_ms
        keep=[]
        for s in self.local_pending:
            if s.candidate_id==c.ident:
                self._learn_binary(self.local_models[(s.side,s.stage_s)],s.x,False)
                self.local_labels[(s.side,s.stage_s)]+=1
                if not getattr(s,"bounce_done",False):
                    self._learn_binary(self.bounce_models[(s.side,s.stage_s)],s.x,False)
                    self.bounce_labels[(s.side,s.stage_s)]+=1
            else:keep.append(s)
        self.local_pending=keep
        if self.last_confirmed_local and self.last_confirmed_local.ident==c.ident:
            self.last_confirmed_local=None

    def _new_candidate(self,side,price,ts_ms,x):
        old=self.candidates.get(side)
        if old is not None:self._invalidate_candidate(old,ts_ms)
        self.candidate_seq+=1
        c=Candidate(self.candidate_seq,side,float(price),int(ts_ms),clean_features(x))
        self.candidates[side]=c
        return c

    def _update_extremes(self,ts_ms,price,x,state):
        h=self._h1_extremes(state,ts_ms)
        events=[]
        if not h:return events
        low6,high6=h
        low=self.candidates["LOW"];high=self.candidates["HIGH"]
        if price<=low6 and (low is None or price<low.extreme_price-1e-12):
            c=self._new_candidate("LOW",price,ts_ms,x)
            events.append({"event":"NEW_LOCAL_CANDIDATE","side":"LOW","candidate_id":c.ident,"price":price})
        if price>=high6 and (high is None or price>high.extreme_price+1e-12):
            c=self._new_candidate("HIGH",price,ts_ms,x)
            events.append({"event":"NEW_LOCAL_CANDIDATE","side":"HIGH","candidate_id":c.ident,"price":price})
        return events

    def _advance_local_labels(self,ts_ms,price,state):
        keep=[]
        for s in self.local_pending:
            sign=1.0 if s.side=="LOW" else -1.0
            move=sign*(price/s.price-1.0)
            s.best_favorable=max(s.best_favorable,move)
            s.worst_adverse=max(s.worst_adverse,-move)
            c=self.candidates.get(s.side)
            invalid=(c is None or c.ident!=s.candidate_id or c.invalidated_ts_ms is not None)
            if not s.bounce_done and ts_ms>=s.bounce_mature_ts_ms:
                by=(not invalid) and s.best_favorable>=0.0035
                bp=self._model_p(self.bounce_models[(s.side,s.stage_s)],s.x)>=0.5
                self.prediction_checks["bounce"]+=1;self.prediction_errors["bounce"]+=int(bp!=bool(by))
                self._learn_binary(self.bounce_models[(s.side,s.stage_s)],s.x,by)
                self.bounce_labels[(s.side,s.stage_s)]+=1;self.bounce_pos[(s.side,s.stage_s)]+=int(by)
                s.bounce_done=True
            sy=self._strict_candidate_outcome(state,s,ts_ms)
            if sy is None:
                keep.append(s);continue
            sy=bool(sy and not invalid)
            model=self.local_models[(s.side,s.stage_s)]
            pred=self._model_p(model,s.x)>=0.5
            self.prediction_checks["local"]+=1;self.prediction_errors["local"]+=int(pred!=sy)
            self._learn_binary(model,s.x,sy)
            self.local_labels[(s.side,s.stage_s)]+=1;self.local_pos[(s.side,s.stage_s)]+=int(sy)
        self.local_pending=keep

    def _entry_x(self,x,ts_ms,price,c,qd):
        side=1 if c.side=="LOW" else -1
        out=dict(x)
        out.update({
            "cq_entry_side":float(side),
            "cq_entry_local_conf":float(c.stage_conf.get(c.confirmed_stage or 0,0.0)),
            "cq_entry_local_age_s":max(0.0,(ts_ms-c.extreme_ts_ms)/1000.0),
            "cq_entry_from_local_pct":side*(float(price)/float(c.extreme_price)-1.0),
            "cq_entry_agent_same":side*float(x.get("agent_consensus",0.0) or 0.0),
            "cq_entry_flow_same":side*float(x.get("flow_imbalance_raw_60s",x.get("flow_imbalance_60s",0.0)) or 0.0),
            "cq_entry_quant_same":1.0 if qd.get("action")==side_name(side) else 0.0,
            "cq_entry_quant_opposite":1.0 if qd.get("action")==side_name(-side) else 0.0,
            "cq_entry_quant_score":float(qd.get("score",0.0) or 0.0),
        })
        return out

    def _sample_entry(self,ts_ms,price,x,c,qd):
        if c is None or c.source!="STRICT_H1_CONFIRMED":return
        if ts_ms-self.last_entry_sample_ms<self.ENTRY_SAMPLE_S*1000:return
        ex=self._entry_x(x,ts_ms,price,c,qd)
        side=1 if c.side=="LOW" else -1
        for horizon in self.ENTRY_HORIZONS:
            self.entry_pending.append(EntryPending(
                ts_ms=int(ts_ms),side=side,price=float(price),local_id=c.ident,x=clean_features(ex),
                horizon_s=int(horizon),mature_ts_ms=int(ts_ms+horizon*1000)))
        self.last_entry_sample_ms=int(ts_ms)

    def _advance_entry_labels(self,ts_ms,price):
        keep=[]
        for p in self.entry_pending:
            move=p.side*(float(price)/p.price-1.0)
            p.best_favorable=max(p.best_favorable,move)
            p.worst_adverse=max(p.worst_adverse,-move)
            if ts_ms<p.mature_ts_ms:
                keep.append(p);continue
            # A good Caterpillar entry is one that offered a usable favorable excursion,
            # even if the terminal price later retraced. Exit learning is responsible
            # for capturing that excursion.
            min_mfe=self.round_trip_cost*1.50
            y=(p.best_favorable>=min_mfe and
               p.best_favorable>=1.25*max(p.worst_adverse,1e-9))
            model=self.entry_models[p.horizon_s]
            pred=self._model_p(model,p.x)>=0.5
            self.prediction_checks["entry"]+=1
            self.prediction_errors["entry"]+=int(pred!=bool(y))
            self._learn_binary(model,p.x,y)
            self.entry_labels[p.horizon_s]+=1
            self.entry_pos[p.horizon_s]+=int(y)
        self.entry_pending=keep

    def _entry_confidence(self,x,ts_ms,price,c,qd):
        ex=self._entry_x(x,ts_ms,price,c,qd)
        ps={h:self._model_p(self.entry_models[h],ex) for h in self.ENTRY_HORIZONS}
        weights={60:0.20,180:0.30,300:0.50}
        conf=sum(weights[h]*ps[h] for h in self.ENTRY_HORIZONS)
        ready=min(self.entry_labels.values())>=30
        return conf,ps,ready

    def _advance_exit_labels(self,ts_ms,price):
        keep=[]
        for s in self.exit_pending:
            move=s.side*(price/s.price-1.0)
            s.best_favorable=max(s.best_favorable,move)
            s.worst_adverse=max(s.worst_adverse,-move)
            if ts_ms<s.mature_ts_ms:
                keep.append(s);continue
            # EXIT is correct only as MFE/profit preservation. Normal Caterpillar
            # exit learning must not learn "close a loser"; emergency structural/risk
            # exits remain a separate execution path.
            cur=float(s.x.get("cq_position_return",0.0) or 0.0)
            mfe=float(s.x.get("cq_position_mfe",0.0) or 0.0)
            give_ratio=float(s.x.get("cq_mfe_giveback_ratio",0.0) or 0.0)
            profitable=cur>self.round_trip_cost
            future_deteriorates=(s.worst_adverse>=max(self.round_trip_cost*0.50,
                                                      s.best_favorable*1.10))
            already_giving_back=(mfe>self.round_trip_cost*1.25 and give_ratio>=0.30
                                 and s.best_favorable<s.worst_adverse)
            y=bool(profitable and (future_deteriorates or already_giving_back))
            pred=self._model_p(self.exit_model,s.x)>=0.5
            self.prediction_checks["exit"]+=1
            self.prediction_errors["exit"]+=int(pred!=bool(y))
            self._learn_binary(self.exit_model,s.x,y)
            self.exit_labels+=1; self.exit_pos+=int(y)
        self.exit_pending=keep

    def _model_value(self,model,x):
        try:
            v=model.predict_one(clean_features(x))
            return float(v or 0.0)
        except Exception:
            return 0.0

    def _learn_value(self,model,x,y):
        model.learn_one(clean_features(x),float(y))

    def _direct_policy_x(self,x,ts_ms,price,c,qd):
        side=1 if c.side=="LOW" else -1
        out=dict(x)
        out.update({
            "cp_structural_side":float(side),
            "cp_from_local_pct":side*(float(price)/max(float(c.extreme_price),1e-9)-1.0),
            "cp_local_confidence":float(c.stage_conf.get(c.confirmed_stage or 0,0.0)),
            "cp_is_position":1.0 if self.position is not None else 0.0,
            "cp_is_reentry_state":1.0 if self.position is None and self._same_local_episode(c) else 0.0,
            "cp_seconds_since_exit":0.0 if not self.last_exit else max(0.0,(ts_ms-int(self.last_exit.get("exit_ts_ms",ts_ms)))/1000.0),
            "cp_quant_same":1.0 if qd.get("action")==side_name(side) else 0.0,
            "cp_quant_opposite":1.0 if qd.get("action")==side_name(-side) else 0.0,
            "cp_quant_score":float(qd.get("score",0.0) or 0.0),
        })
        if self.position is not None:
            p=self.position
            cur=p.side*(float(price)/max(p.entry_price,1e-9)-1.0)
            give=max(0.0,p.mfe-cur)
            out.update({
                "cp_position_return":cur,
                "cp_position_mfe":p.mfe,
                "cp_position_mae":p.mae,
                "cp_mfe_giveback":give,
                "cp_mfe_giveback_ratio":give/max(p.mfe,1e-9) if p.mfe>0 else 0.0,
                "cp_position_age_s":max(0.0,(ts_ms-p.entry_ts_ms)/1000.0),
            })
        return clean_features(out)

    def _sample_direct_policy(self,ts_ms,price,x,c,qd):
        if c is None or getattr(c,"source",None)!="STRICT_H1_CONFIRMED":return
        if ts_ms-self.last_policy_sample_ms<self.POLICY_SAMPLE_S*1000:return
        mode="POSITION" if self.position is not None else "FLAT"
        side=(self.position.side if self.position is not None else (1 if c.side=="LOW" else -1))
        px=self._direct_policy_x(x,ts_ms,price,c,qd)
        for horizon in self.DIRECT_POLICY_HORIZONS:
            self.policy_pending.append(PolicyPending(
                ts_ms=int(ts_ms),side=int(side),mode=mode,price=float(price),x=px,
                horizon_s=int(horizon),mature_ts_ms=int(ts_ms+horizon*1000)))
        self.last_policy_sample_ms=int(ts_ms)

    def _advance_direct_policy_labels(self,ts_ms,price):
        keep=[]
        for p in self.policy_pending:
            move=p.side*(float(price)/max(p.price,1e-9)-1.0)
            p.best_favorable=max(p.best_favorable,move)
            p.worst_adverse=max(p.worst_adverse,-move)
            if ts_ms<p.mature_ts_ms:
                keep.append(p);continue
            # Economic advantage, not a hand-written action threshold:
            # FLAT: entering now must earn favorable excursion net of adverse path and round-trip cost.
            # POSITION: holding must add more favorable path than adverse path versus exiting now.
            advantage=p.best_favorable-p.worst_adverse
            if p.mode=="FLAT":advantage-=self.round_trip_cost
            model=self.policy_models[(p.mode,p.horizon_s)]
            self._learn_value(model,p.x,advantage)
            self.policy_labels[(p.mode,p.horizon_s)]+=1
            self.policy_target_sum[(p.mode,p.horizon_s)]+=float(advantage)
        self.policy_pending=keep

    def _direct_policy_values(self,x,ts_ms,price,c,qd):
        mode="POSITION" if self.position is not None else "FLAT"
        px=self._direct_policy_x(x,ts_ms,price,c,qd)
        per_h={h:self._model_value(self.policy_models[(mode,h)],px) for h in self.DIRECT_POLICY_HORIZONS}
        value=statistics.fmean(per_h.values()) if per_h else 0.0
        labels={h:int(self.policy_labels[(mode,h)]) for h in self.DIRECT_POLICY_HORIZONS}
        ready=any(v>0 for v in labels.values())
        return mode,value,per_h,labels,ready

    def _execute_direct_policy(self,ts_ms,price,x,c,qd):
        events=[]
        if c is None:return events
        structural_side=1 if c.side=="LOW" else -1
        mode,value,per_h,labels,ready=self._direct_policy_values(x,ts_ms,price,c,qd)
        same_reentry=(self.position is None and self._same_local_episode(c))
        if self.position is not None and self.position.side!=structural_side:
            events.extend(self._close(ts_ms,price,"OPPOSITE_LOCAL_CONFIRMED"))
            mode,value,per_h,labels,ready=self._direct_policy_values(x,ts_ms,price,c,qd)
        if self.position is None:
            action=("REENTER" if same_reentry else "ENTER") if ready and value>0.0 else "WAIT"
            if action in ("ENTER","REENTER"):
                events.extend(self._open(ts_ms,price,structural_side,c,
                                         float(c.stage_conf.get(c.confirmed_stage or 0,0.0)),qd,
                                         reentry=(action=="REENTER")))
        else:
            action="HOLD" if (not ready or value>=0.0) else "EXIT"
            if action=="EXIT":
                events.extend(self._close(ts_ms,price,"DIRECT_POLICY_EXIT"))
            else:
                p=self.position
                cur=p.side*(float(price)/max(p.entry_price,1e-9)-1.0)
                p.mfe=max(p.mfe,cur);p.mae=min(p.mae,cur)
                events.append({"event":"HOLD","ts_ms":ts_ms,"side":side_name(p.side),"price":price,
                               "mfe":p.mfe,"mae":p.mae,"current_return":cur})
        self.last_policy_decision={
            "ts_ms":int(ts_ms),"mode":mode,"action":action,
            "structural_side":side_name(structural_side),"advantage":value,
            "horizon_advantage":per_h,"labels":labels,"ready":ready,
            "objective":"maximize favorable path minus adverse path and trading cost inside the confirmed Local-to-Local leg",
        }
        for e in events:
            e["direct_policy_action"]=action
            e["direct_policy_advantage"]=value
            e["direct_policy_horizon_advantage"]=per_h
        return events

    def _direct_policy_report(self):
        labels={mode:{str(h):int(self.policy_labels[(mode,h)]) for h in self.DIRECT_POLICY_HORIZONS}
                for mode in ("FLAT","POSITION")}
        means={mode:{str(h):(self.policy_target_sum[(mode,h)]/self.policy_labels[(mode,h)]
                             if self.policy_labels[(mode,h)] else None)
                     for h in self.DIRECT_POLICY_HORIZONS}
               for mode in ("FLAT","POSITION")}
        total=sum(sum(v.values()) for v in labels.values())
        return {
            "contract_version":6,
            "actions":{"flat":["WAIT","ENTER_OR_REENTER"],"position":["HOLD","EXIT"]},
            "hard_constraints":["LOCAL_LOW_LONG_ONLY","LOCAL_HIGH_SHORT_ONLY"],
            "labels":labels,"mean_realized_advantage":means,
            "pending":len(self.policy_pending),
            "training_percent":min(100.0,100.0*total/1200.0),
            "last_decision":self.last_policy_decision,
            "manual_action_thresholds":False,
            "causal_state_note":"policy consumes the complete cleaned causal feature state; future target/evaluation fields are never inputs",
        }

    def _stage_candidate(self,c,ts_ms,price,x):
        events=[]
        if c is None or c.invalidated_ts_ms is not None:return events
        age=(ts_ms-c.extreme_ts_ms)/1000.0
        for stage in self.LOCAL_STAGES:
            if age<stage or stage in c.stage_done:continue
            sx=self._candidate_x(x,c,ts_ms,price)
            p=self._model_p(self.local_models[(c.side,stage)],sx)
            bp=self._model_p(self.bounce_models[(c.side,stage)],sx)
            labels=self.local_labels[(c.side,stage)]
            sign=1.0 if c.side=="LOW" else -1.0
            retr=sx["cq_retrace_bps"]
            heuristic=sigmoid((retr-18.0)/18.0 + 1.2*sx["cq_agent_alignment"] + .8*sx["cq_flow_alignment"])
            model_weight=min(.80,.80*labels/120.0)
            conf=(1-model_weight)*heuristic+model_weight*p
            c.stage_done.add(stage);c.stage_conf[stage]=conf;c.stage_retrace_bps[stage]=retr
            hour=(c.extreme_ts_ms//3_600_000)*3_600_000
            self.local_pending.append(LocalPending(
                candidate_id=c.ident,side=c.side,stage_s=stage,ts_ms=ts_ms,price=price,x=sx,
                candidate_hour_ms=hour,strict_mature_ts_ms=hour+3*3_600_000,
                bounce_mature_ts_ms=ts_ms+self.BOUNCE_FUTURE_S*1000))
            accepted=conf>=({60:.55,180:.58,300:.60}[stage]) and retr>0
            policy_promoted=False
            if accepted:
                c.confirmed_stage=stage
                # Candidate heads continue learning, but trading direction is anchored
                # only by the full-history structural H1 sequence.
                policy_promoted=(c.source=="STRICT_H1_CONFIRMED")
            events.append({"event":"LOCAL_STAGE","side":c.side,"candidate_id":c.ident,"stage_s":stage,
                           "confidence":conf,"strict_model_p":p,"bounce_model_p":bp,
                           "heuristic":heuristic,"retrace_bps":retr,
                           "accepted":accepted,"policy_promoted":policy_promoted,
                           "strict_labels_seen":labels,
                           "bounce_labels_seen":self.bounce_labels[(c.side,stage)]})
        return events

    def _opposite_local_watch(self,ts_ms,price,x):
        c=self.last_confirmed_local
        if c is None or getattr(c,"source",None)!="STRICT_H1_CONFIRMED":
            return {"structural_leg":"UNKNOWN","target_local":None,"score":0.0,"status":"WAIT_LOCAL",
                    "structural_bias":"FLAT","components":{}}
        leg_side=1 if c.side=="LOW" else -1
        target="HIGH" if c.side=="LOW" else "LOW"
        structural_leg="UP_LEG_LOW_TO_HIGH" if leg_side>0 else "DOWN_LEG_HIGH_TO_LOW"
        structural_bias="LONG" if leg_side>0 else "SHORT"
        early=self._early_local_report().get("shadow") or {}
        early_p=float(early.get("high_probability" if target=="HIGH" else "low_probability") or 0.0)

        cand=self.candidates.get(target)
        cand_conf=0.0; retrace_bps=0.0; cand_stage=None; cand_price=None
        if cand is not None and cand.invalidated_ts_ms is None:
            cand_conf=max([float(v) for v in cand.stage_conf.values() if finite(v)] or [0.0])
            cand_stage=max(cand.stage_done) if cand.stage_done else None
            cand_price=float(cand.extreme_price)
            if target=="HIGH":
                retrace_bps=max(0.0,(cand.extreme_price-float(price))/max(cand.extreme_price,1e-9)*10000.0)
            else:
                retrace_bps=max(0.0,(float(price)-cand.extreme_price)/max(cand.extreme_price,1e-9)*10000.0)

        agent=float(x.get("agent_consensus",0.0) or 0.0)
        struct=float(x.get("agent_structure_direction",0.0) or 0.0)
        flow=float(x.get("agent_flow_direction",x.get("flow_imbalance_raw_60s",0.0)) or 0.0)
        book=float(x.get("agent_book_direction",0.0) or 0.0)
        opposite_sign=-1.0 if target=="HIGH" else 1.0
        reversal_pressure=clip(
            0.35*max(0.0,opposite_sign*agent)+
            0.30*max(0.0,opposite_sign*struct)+
            0.20*max(0.0,opposite_sign*flow)+
            0.15*max(0.0,opposite_sign*book)
        )
        retrace_score=clip(retrace_bps/60.0)
        score=clip(.32*early_p+.28*cand_conf+.22*retrace_score+.18*reversal_pressure)

        if cand is not None and cand.confirmed_stage is not None and cand.source=="STRICT_H1_CONFIRMED":
            status="CONFIRMED_"+target
        elif score>=.70:
            status=target+"_CANDIDATE_STRONG"
        elif score>=.50:
            status=target+"_WATCH_HIGH"
        elif score>=.30:
            status=target+"_WATCH"
        else:
            status="LEG_CONTINUES"

        move_from_local=leg_side*(float(price)/max(float(c.extreme_price),1e-9)-1.0)
        return {
            "structural_leg":structural_leg,"structural_bias":structural_bias,
            "target_local":target,"status":status,"score":score,
            "price":float(price),"move_from_confirmed_local_pct":move_from_local*100.0,
            "confirmed_local":{"side":c.side,"price":float(c.extreme_price),
                               "strict_hour_ms":getattr(c,"strict_hour_ms",None)},
            "candidate":{"present":cand is not None,"stage":cand_stage,"confidence":cand_conf,
                         "extreme_price":cand_price,"retrace_bps":retrace_bps},
            "early_probability":early_p,
            "components":{"early_probability":early_p,"candidate_confidence":cand_conf,
                          "retrace_score":retrace_score,"reversal_pressure":reversal_pressure,
                          "agent_consensus":agent,"agent_structure_direction":struct,
                          "agent_flow_direction":flow,"agent_book_direction":book},
            "interpretation":"structural leg remains active until opposite confirmed H1 local; watch score is research/shadow evidence, not a confirmed pivot",
        }

    def _best_local(self):
        c=self.last_confirmed_local
        if c is None or c.invalidated_ts_ms is not None or c.confirmed_stage is None:return None,None
        if getattr(c,"source",None)!="STRICT_H1_CONFIRMED":return None,None
        return c,c.stage_conf.get(c.confirmed_stage,0.0)

    def _structural_history_report(self,state,ts_ms):
        pivots=self._strict_pivots(state,ts_ms)
        legs=[]
        eq1=100.0
        eq_cfg=100.0
        exposure=5.0  # research reference: 20% margin * 25x
        for a,b in zip(pivots,pivots[1:]):
            if a["side"]==b["side"]:continue
            side=1 if a["side"]=="LOW" else -1
            entry=float(a.get("confirm_price") or a["price"])
            exitp=float(b.get("confirm_price") or b["price"])
            gross=side*(exitp/entry-1.0)
            net=gross-self.round_trip_cost
            before1=eq1; before_cfg=eq_cfg
            eq1*=max(0.0,1.0+net)
            eq_cfg*=max(0.0,1.0+exposure*net)
            legs.append({
                "side":side_name(side),"local_from":a["price"],"local_to":b["price"],
                "entry_confirm_price":entry,"exit_confirm_price":exitp,
                "entry_available_ms":a["available_ms"],"exit_available_ms":b["available_ms"],
                "gross_return":gross,"net_return":net,
                "equity_1x_before":before1,"equity_1x_after":eq1,
                "equity_configured_before":before_cfg,"equity_configured_after":eq_cfg,
            })
        wins=sum(z["net_return"]>0 for z in legs)
        return {
            "bars_loaded":len(self._completed_h1(state,ts_ms)),
            "strict_pivots":len(pivots),
            "closed_legs":len(legs),
            "wins":wins,
            "win_rate":wins/len(legs) if legs else None,
            "equity_1x":eq1,
            "return_1x_pct":eq1-100.0,
            "configured_exposure_x":exposure,
            "equity_configured_reference":eq_cfg,
            "return_configured_reference_pct":eq_cfg-100.0,
            "reference_note":"causal H1 confirmation reference; ignores liquidation/slippage and is not a profit forecast",
            "latest_pivots":pivots[-8:],
            "latest_legs":legs[-8:],
        }

    def _training_progress(self):
        local_total=sum(self.local_labels.values()); bounce_total=sum(self.bounce_labels.values())
        local_target=len(self.local_labels)*120
        bounce_target=len(self.bounce_labels)*120
        entry_total=sum(self.entry_labels.values());entry_target=len(self.entry_models)*120
        exit_target=300; reentry_target=200
        def pct(v,t):return min(100.0,100.0*float(v)/max(1,float(t)))
        fib_labels=sum(self.fib_labels.values());fib_target=len(self.fib_models)*40
        policy_total=sum(self.policy_labels.values()) if hasattr(self,"policy_labels") else 0
        heads={
            "local":{"labels":local_total,"target_labels":local_target,"percent":pct(local_total,local_target)},
            "bounce":{"labels":bounce_total,"target_labels":bounce_target,"percent":pct(bounce_total,bounce_target)},
            "direct_policy":{"labels":policy_total,"target_labels":1200,"percent":pct(policy_total,1200)},
            "fibonacci":{"labels":fib_labels,"target_labels":fib_target,"percent":pct(fib_labels,fib_target)},
            "legacy_entry":{"labels":entry_total,"target_labels":entry_target,"percent":pct(entry_total,entry_target),"execution":False},
            "legacy_exit":{"labels":self.exit_labels,"target_labels":exit_target,"percent":pct(self.exit_labels,exit_target),"execution":False},
            "legacy_reentry":{"labels":self.reentry_labels,"target_labels":reentry_target,"percent":pct(self.reentry_labels,reentry_target),"execution":False},
        }
        overall=.38*heads["local"]["percent"]+.07*heads["bounce"]["percent"]+.45*heads["direct_policy"]["percent"]+.10*heads["fibonacci"]["percent"]
        if overall>=100:status="MODEL_MATURE"
        elif overall>=60:status="VALIDATING"
        elif overall>=10:status="LEARNING"
        else:status="COLLECTING_LABELS"
        return {"overall_percent":overall,"status":status,"heads":heads,
                "meaning":"label-maturity progress, not guaranteed accuracy or profitability"}

    def _baseline_on_local(self,c,ts_ms,price):
        side=1 if c.side=="LOW" else -1
        if self.baseline_position is not None and self.baseline_position["side"]!=side:
            p=self.baseline_position
            gross=p["side"]*(price/p["entry_price"]-1.0)
            net=gross-self.round_trip_cost
            before=self.baseline_equity
            self.baseline_equity*=max(0.0,1.0+net)
            self.baseline_trades.append({
                "entry_ts_ms":p["entry_ts_ms"],"exit_ts_ms":ts_ms,
                "side":side_name(p["side"]),"entry_price":p["entry_price"],"exit_price":price,
                "gross_return":gross,"net_return":net,"equity_before":before,
                "equity_after":self.baseline_equity,"reason":"OPPOSITE_CONFIRMED_LOCAL"
            })
            self.baseline_position=None
        if self.baseline_position is None:
            self.baseline_position={"side":side,"entry_ts_ms":ts_ms,"entry_price":price,"local_id":c.ident}

    def _sample_exit(self,ts_ms,price,x,qd):
        p=self.position
        if p is None:return
        if ts_ms-p.last_exit_sample_ms<self.POLICY_SAMPLE_S*1000:return
        px=self._position_x(x,ts_ms,price,qd)
        self.exit_pending.append(ExitPending(ts_ms,p.side,price,px,ts_ms+self.EXIT_HORIZON_S*1000))
        p.last_exit_sample_ms=ts_ms

    def _reentry_x(self,x,ts_ms,price,c,qd):
        side=1 if c.side=="LOW" else -1
        out=dict(x)
        out.update({
            "cq_reentry_side":float(side),
            "cq_reentry_local_conf":float(c.stage_conf.get(c.confirmed_stage or 0,0.0)),
            "cq_reentry_local_age_s":max(0.0,(ts_ms-c.extreme_ts_ms)/1000.0),
            "cq_reentry_agent_same":side*float(x.get("agent_consensus",0.0) or 0.0),
            "cq_reentry_flow_same":side*float(x.get("flow_imbalance_raw_60s",x.get("flow_imbalance_60s",0.0)) or 0.0),
            "cq_reentry_quant_same":1.0 if qd.get("action")==side_name(side) else 0.0,
            "cq_reentry_quant_opposite":1.0 if qd.get("action")==side_name(-side) else 0.0,
            "cq_reentry_seconds_since_exit":0.0 if not self.last_exit else max(0.0,(ts_ms-int(self.last_exit["exit_ts_ms"]))/1000.0),
        })
        return out

    def _sample_reentry(self,ts_ms,price,x,c,qd):
        if not self._same_local_episode(c):return
        if ts_ms-self.last_reentry_sample_ms<self.POLICY_SAMPLE_S*1000:return
        side=1 if c.side=="LOW" else -1
        rx=self._reentry_x(x,ts_ms,price,c,qd)
        self.reentry_pending.append(ReentryPending(ts_ms,side,price,c.ident,rx,ts_ms+self.REENTRY_HORIZON_S*1000))
        self.last_reentry_sample_ms=ts_ms

    def _advance_reentry_labels(self,ts_ms,price):
        keep=[]
        for s in self.reentry_pending:
            move=s.side*(price/s.price-1.0)
            s.best_favorable=max(s.best_favorable,move);s.worst_adverse=max(s.worst_adverse,-move)
            if ts_ms<s.mature_ts_ms:
                keep.append(s);continue
            # Re-entry is positive only when the same structural leg genuinely
            # resumes: a fresh favorable excursion must dominate adverse noise.
            y=(s.best_favorable>=self.round_trip_cost*1.50 and
               s.best_favorable>=1.35*max(s.worst_adverse,1e-9))
            pred=self._model_p(self.reentry_model,s.x)>=0.5
            self.prediction_checks["reentry"]+=1;self.prediction_errors["reentry"]+=int(pred!=bool(y))
            self._learn_binary(self.reentry_model,s.x,y)
            self.reentry_labels+=1;self.reentry_pos+=int(y)
        self.reentry_pending=keep

    def _local_key(self,c):
        if c is None:return None
        hour=getattr(c,"strict_hour_ms",None)
        if hour is None:
            hour=(int(c.extreme_ts_ms)//3_600_000)*3_600_000
        return f"{c.side}:{int(hour)}:{float(c.extreme_price):.8f}"

    def _same_local_episode(self,c):
        if c is None or not self.last_exit:return False
        side=1 if c.side=="LOW" else -1
        if self.last_exit.get("side")!=side_name(side):return False
        key=self.last_exit.get("local_key")
        if key:return key==self._local_key(c)
        # Migration fallback for old checkpoints that predate stable local keys.
        if self.last_exit.get("local_id")==c.ident:return True
        anchor=getattr(c,"strict_hour_ms",None)
        return anchor is not None and int(self.last_exit.get("exit_ts_ms",0))>=int(anchor)+3_600_000

    def _open(self,ts_ms,price,side,c,local_conf,qd,reentry=False):
        lev=float(qd.get("leverage") or 5)
        frac=float(qd.get("margin_fraction") or .05)
        lev=max(1.0,min(25.0,lev));frac=max(.02,min(.20,frac))
        margin=self.equity*frac;notional=margin*lev
        re_no=(self.last_exit.get("reentry_no",0)+1 if reentry and self.last_exit else 0)
        self.position=PaperPosition(side,ts_ms,price,lev,frac,notional,margin,c.ident,re_no,self._local_key(c))
        if reentry:self.reentries+=1
        return [{"event":"REENTER" if reentry else "ENTER","ts_ms":ts_ms,"side":side_name(side),
                 "price":price,"local_id":c.ident,"local_confidence":local_conf,
                 "leverage":lev,"margin_fraction":frac,"equity":self.equity}]

    def _close(self,ts_ms,price,reason):
        p=self.position
        if p is None:return []
        gross=p.side*(price/p.entry_price-1.0)
        net=gross-self.round_trip_cost
        pnl=p.notional*net
        before=self.equity;self.equity=max(0.0,self.equity+pnl)
        self.peak_equity=max(self.peak_equity,self.equity)
        self.max_drawdown=max(self.max_drawdown,(self.peak_equity-self.equity)/max(self.peak_equity,1e-9))
        capture=(max(0.0,net)/max(p.mfe,1e-9)) if p.mfe>0 else None
        row={"entry_ts_ms":p.entry_ts_ms,"exit_ts_ms":ts_ms,"side":side_name(p.side),
             "entry_price":p.entry_price,"exit_price":price,"gross_return":gross,"net_return":net,
             "pnl":pnl,"equity_before":before,"equity_after":self.equity,
             "mfe":p.mfe,"mae":p.mae,"mfe_capture_ratio":capture,
             "mfe_giveback":max(0.0,p.mfe-gross),"reason":reason,
             "local_id":p.local_id,"local_key":getattr(p,"local_key",None),"reentry_no":p.reentry_no,
             "leverage":p.leverage,"margin_fraction":p.margin_fraction}
        self.trades.append(row)
        self.path_equity*=max(0.0,1.0+net)
        self.last_exit=row;self.position=None
        return [{"event":"EXIT","ts_ms":ts_ms,**row}]

    def on_gap(self,ts_ms,reason):
        self._ensure_v2()
        self.censored+=1
        self.local_pending.clear();self.entry_pending.clear();self.exit_pending.clear();self.reentry_pending.clear();self.policy_pending.clear()
        if self.position:
            self.censored_positions+=1
            self.actions.append({"event":"CENSORED_POSITION","ts_ms":ts_ms,"reason":reason,
                                 "side":side_name(self.position.side),"entry_ts_ms":self.position.entry_ts_ms,
                                 "entry_price":self.position.entry_price,"local_id":self.position.local_id})
            self.position=None
        self.baseline_position=None
        for c in self.candidates.values():
            if c:self._invalidate_candidate(c,ts_ms)
        self.candidates={"LOW":None,"HIGH":None};self.last_confirmed_local=None
        self.quant.pending.clear()
        self.actions.append({"event":"CENSORED","ts_ms":ts_ms,"reason":reason})

    def observe(self,ts_ms,price,x,state):
        self._ensure_v2()
        events=[]
        self._train_early_local_history(state,ts_ms)
        self._advance_local_labels(ts_ms,price,state)
        self._advance_direct_policy_labels(ts_ms,price)
        self._advance_fib_labels(ts_ms,price)
        self.structural_history=self._structural_history_report(state,ts_ms)
        fib=self._fib_snapshot(state,ts_ms,price)
        self.current_fib={
            "available":bool(fib.get("available")),
            "trend_side":fib.get("trend_side"),
            "swing_from":fib.get("swing_from"),"swing_to":fib.get("swing_to"),
            "retrace_fraction":fib.get("retrace_fraction"),
            "extension_fraction":fib.get("extension_fraction"),
            "closest":fib.get("closest"),
            "levels":fib.get("levels") or [],
        }
        if fib.get("available"):
            x=dict(x);x.update(fib.get("features") or {})
        qd=self.quant.observe(ts_ms,price,x)
        events.extend(self._sync_strict_local(state,ts_ms,price,x))
        events.extend(self._sample_fib_touches(ts_ms,price,x,fib))
        # No recency-window bootstrap participates in trading policy. Candidate
        # discovery below exists only to train earlier local recognition.
        events.extend(self._update_extremes(ts_ms,price,x,state))
        for side in ("LOW","HIGH"):
            events.extend(self._stage_candidate(self.candidates[side],ts_ms,price,x))
        self.local_watch_current=self._opposite_local_watch(ts_ms,price,x)

        c,local_conf=self._best_local()
        if self.position and c is not None:
            structural_side=1 if c.side=="LOW" else -1
            if self.position.side!=structural_side:
                events.extend(self._close(ts_ms,price,"OPPOSITE_LOCAL_CONFIRMED"))

        if c is not None:
            self._sample_direct_policy(ts_ms,price,x,c,qd)
            events.extend(self._execute_direct_policy(ts_ms,price,x,c,qd))
        else:
            self.last_policy_decision={"ts_ms":int(ts_ms),"action":"WAIT_LOCAL","ready":False}

        self.last_ts_ms=ts_ms;self.last_price=price
        for e in events:self.actions.append(e)
        return {"quant":qd,"events":events,"paper":self.paper_snapshot()}

    def paper_snapshot(self):
        p=self.position
        current_return=None
        if p is not None and finite(self.last_price) and p.entry_price>0:
            current_return=p.side*(float(self.last_price)/p.entry_price-1.0)
        return {"equity":self.equity,"peak_equity":self.peak_equity,"max_drawdown":self.max_drawdown,
                "open_position":None if p is None else {
                    "side":side_name(p.side),"entry_ts_ms":p.entry_ts_ms,"entry_price":p.entry_price,
                    "mark_price":self.last_price,"current_return":current_return,
                    "mfe":p.mfe,"mae":p.mae,"leverage":p.leverage,"margin_fraction":p.margin_fraction,
                    "local_id":p.local_id,"local_key":getattr(p,"local_key",None),"reentry_no":p.reentry_no},
                "closed_trades":len(self.trades),"reentries":self.reentries}

    @staticmethod
    def _model_weights(model):
        rows=[]
        try:
            steps=getattr(model,"steps",None)
            vals=list(steps.values()) if hasattr(steps,"values") else []
            if not vals:
                try: vals=[model[-1]]
                except Exception: vals=[]
            for step in vals:
                weights=getattr(step,"weights",None)
                if weights is None:continue
                for k,v in dict(weights).items():
                    if finite(v) and abs(float(v))>=1e-5:
                        rows.append((str(k),float(v)))
        except Exception:
            pass
        return rows

    def _relationships_report(self):
        rows=[]
        for (side,stage),model in self.local_models.items():
            if self.local_labels[(side,stage)]<5:continue
            for feature,w in self._model_weights(model):
                rows.append({"head":f"LOCAL_{side}_{stage}s","feature":feature,"weight":w})
        for (side,stage),model in self.bounce_models.items():
            if self.bounce_labels[(side,stage)]<5:continue
            for feature,w in self._model_weights(model):
                rows.append({"head":f"BOUNCE_{side}_{stage}s","feature":feature,"weight":w})
        if self.exit_labels>=5:
            for feature,w in self._model_weights(self.exit_model):
                rows.append({"head":"EXIT","feature":feature,"weight":w})
        for h,model in self.entry_models.items():
            if self.entry_labels.get(h,0)<5:continue
            for feature,w in self._model_weights(model):
                rows.append({"head":f"ENTRY_{h}s","feature":feature,"weight":w})
        if self.reentry_labels>=5:
            for feature,w in self._model_weights(self.reentry_model):
                rows.append({"head":"REENTRY","feature":feature,"weight":w})
        for key,model in self.fib_models.items():
            if self.fib_labels.get(key,0)<5:continue
            for feature,w in self._model_weights(model):
                rows.append({"head":"FIB_"+key,"feature":feature,"weight":w})
        rows.sort(key=lambda z:abs(z["weight"]),reverse=True)
        return {"total":len(rows),"positive":sum(r["weight"]>0 for r in rows),
                "negative":sum(r["weight"]<0 for r in rows),"top":rows[:40]}

    def report(self):
        self._ensure_v2()
        captures=[t["mfe_capture_ratio"] for t in self.trades if finite(t.get("mfe_capture_ratio"))]
        wins=sum(t["pnl"]>0 for t in self.trades)
        gp=sum(max(0.0,t["pnl"]) for t in self.trades);gl=-sum(min(0.0,t["pnl"]) for t in self.trades)
        relationships=self._relationships_report()
        checks=sum(self.prediction_checks.values())
        errors=sum(self.prediction_errors.values())
        paper=self.paper_snapshot()
        return {
            "version":self.VERSION,"policy_contract_version":getattr(self,"policy_contract_version",0),
            "legacy_paper_archive":getattr(self,"legacy_paper_archive",None),
            "legacy_paper_archives":getattr(self,"legacy_paper_archives",[]),
            "research_only":True,"real_orders":False,
            "learning_status":"LEARNING",
            "relationships":relationships,
            "relationships_total":relationships["total"],
            "positive_relationships":relationships["positive"],
            "negative_relationships":relationships["negative"],
            "prediction_checks":checks,"errors_total":errors,
            "error_rate":errors/checks if checks else None,
            "prediction_errors":dict(self.prediction_errors),
            "prediction_checks_by_head":dict(self.prediction_checks),
            "equity":self.equity,"return_pct":(self.equity/100.0-1.0)*100.0,
            "open_position":paper["open_position"],
            "paper_snapshot":paper,
            "path_equity_1x":self.path_equity,
            "caterpillar_path_return_pct":(self.path_equity/100.0-1.0)*100.0,
            "straight_local_equity_1x":self.baseline_equity,
            "straight_local_path_return_pct":(self.baseline_equity/100.0-1.0)*100.0,
            "caterpillar_vs_straight_delta_pct":((self.path_equity-self.baseline_equity)/100.0)*100.0,
            "straight_local_closed_legs":len(self.baseline_trades),
            "max_drawdown_pct":self.max_drawdown*100.0,
            "open_position":paper["open_position"],
            "closed_trades":len(self.trades),"wins":wins,
            "win_rate":wins/len(self.trades) if self.trades else None,
            "profit_factor":gp/gl if gl>0 else (None if gp==0 else 99.0),
            "reentries":self.reentries,
            "mean_mfe_capture_ratio":statistics.fmean(captures) if captures else None,
            "median_mfe_capture_ratio":statistics.median(captures) if captures else None,
            "local_target":"FULL_HISTORY_STRICT_H1_L6_K2",
            "local_policy":"Direct policy v6: H1 local hard-defines direction only. The learned causal policy alone chooses WAIT/ENTER/HOLD/EXIT/RE-ENTER from the full current state; no manual confidence/action thresholds participate in execution.",
            "bootstrap_diagnostic":{"disabled_for_policy":True,"reason":"recency-window local is training-only"},
            "training_progress":self._training_progress(),
            "structural_history":getattr(self,"structural_history",{}),
            "early_local":self._early_local_report(),
            "local_watch":getattr(self,"local_watch_current",{}),
            "local_models":{f"{s}_{h}s":{"labels":self.local_labels[(s,h)],"positive":self.local_pos[(s,h)]}
                            for s in ("LOW","HIGH") for h in self.LOCAL_STAGES},
            "bounce_models":{f"{s}_{h}s":{"labels":self.bounce_labels[(s,h)],"positive":self.bounce_pos[(s,h)]}
                            for s in ("LOW","HIGH") for h in self.LOCAL_STAGES},
            "direct_policy":self._direct_policy_report(),
            "entry_model":{"labels":dict(self.entry_labels),"positive":dict(self.entry_pos),
                           "ready":False,"execution":False,"legacy":True},
            "exit_model":{"labels":self.exit_labels,"exit_positive":self.exit_pos,
                          "execution":False,"legacy":True},
            "reentry_model":{"labels":self.reentry_labels,"reentry_positive":self.reentry_pos,
                             "ready":False,"execution":False,"legacy":True},
            "fibonacci":{**self._fib_report(),"current":getattr(self,"current_fib",None)},
            "active_local":None if self.last_confirmed_local is None else {
                "id":self.last_confirmed_local.ident,"side":self.last_confirmed_local.side,
                "price":self.last_confirmed_local.extreme_price,
                "stage":self.last_confirmed_local.confirmed_stage,
                "source":getattr(self.last_confirmed_local,"source","LIVE_CANDIDATE"),
                "strict_hour_ms":getattr(self.last_confirmed_local,"strict_hour_ms",None),
                "confidence":self.last_confirmed_local.stage_conf.get(self.last_confirmed_local.confirmed_stage or 0),
                "evidence":getattr(self.last_confirmed_local,"evidence",{})},
            "quant":self.quant.report(),
            "policy_state":"IN_POSITION" if self.position else ("WAIT_REENTRY" if self.last_exit and self.last_confirmed_local and self.last_exit.get("local_id")==self.last_confirmed_local.ident else "WAIT_ENTRY"),
            "censored":self.censored,"censored_positions":self.censored_positions,
        }

    def save(self,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix(path.suffix+".tmp")
        with tmp.open("wb") as f:pickle.dump(self,f,pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
        path.with_suffix(".json").write_text(json.dumps(self.report(),indent=2)+"\n")

    @staticmethod
    def load(path:Path):
        with path.open("rb") as f:obj=pickle.load(f)
        if not isinstance(obj,CaterpillarQuantLearner):raise TypeError("not CaterpillarQuantLearner")
        obj._ensure_v2()
        return obj

def new_from_config(path:Path):
    return CaterpillarQuantLearner(load_config(path))
