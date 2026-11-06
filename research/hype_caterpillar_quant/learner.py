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
    REENTRY_HORIZON_S=300
    POLICY_SAMPLE_S=30
    MIN_HOLD_S=60

    def __init__(self,quant_config:dict[str,Any]):
        self.quant=OnlineQuantLearner(copy.deepcopy(quant_config))
        self.local_models={(side,stage):binary_model() for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.local_labels={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.local_pos={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.bounce_models={(side,stage):binary_model() for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.bounce_labels={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.bounce_pos={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.exit_model=binary_model(); self.reentry_model=binary_model()
        self.exit_labels=0; self.exit_pos=0
        self.reentry_labels=0; self.reentry_pos=0
        self.candidates={"LOW":None,"HIGH":None}
        self.candidate_seq=0
        self.local_pending:list[LocalPending]=[]
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
        self.last_reentry_sample_ms=0
        self.policy_version=2
        self.bootstrap_diagnostic={}
        self.structural_history={}
        self.prediction_checks={"local":0,"bounce":0,"exit":0,"reentry":0}
        self.prediction_errors={"local":0,"bounce":0,"exit":0,"reentry":0}

    def _model_p(self,model,x):
        try:
            p=model.predict_proba_one(clean_features(x))
            return float(p.get(True,p.get(1,0.5)))
        except Exception:
            return 0.5

    def _learn_binary(self,model,x,y):
        model.learn_one(clean_features(x),bool(y))


    def _ensure_v2(self):
        if getattr(self,"policy_version",1)>=2:
            if hasattr(self.quant,"_ensure_v2"):self.quant._ensure_v2()
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
        self.exit_labels=self.exit_pos=self.reentry_labels=self.reentry_pos=0
        self.local_pending=[];self.exit_pending=[];self.reentry_pending=[]
        self.candidates={"LOW":None,"HIGH":None};self.last_confirmed_local=None
        self.last_reentry_sample_ms=0
        self.bootstrap_diagnostic=getattr(self,"bootstrap_diagnostic",{})
        self.censored_positions=getattr(self,"censored_positions",0)
        self.prediction_checks={"local":0,"bounce":0,"exit":0,"reentry":0}
        self.prediction_errors={"local":0,"bounce":0,"exit":0,"reentry":0}
        self.policy_version=2
        if hasattr(self.quant,"_ensure_v2"):self.quant._ensure_v2()

    def _completed_h1(self,state,ts_ms):
        rows=[]
        for start in sorted(state.candles.get("60",{})):
            if start+3_600_000<=ts_ms:
                b=state.candles["60"][start]
                if finite(b.get("high")) and finite(b.get("low")):
                    rows.append({"start_ms":int(start),"high":float(b["high"]),"low":float(b["low"]),
                                 "open":float(b.get("open") or b["low"]),"close":float(b.get("close") or b["high"])})
        return rows

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

    def _advance_exit_labels(self,ts_ms,price):
        keep=[]
        for s in self.exit_pending:
            move=s.side*(price/s.price-1.0)
            s.best_favorable=max(s.best_favorable,move)
            s.worst_adverse=max(s.worst_adverse,-move)
            if ts_ms<s.mature_ts_ms:
                keep.append(s);continue
            # EXIT is correct when the next 5m loses edge or adverse path dominates.
            y=(move < -self.round_trip_cost*0.5) or (s.worst_adverse > max(0.0015,s.best_favorable*1.20))
            pred=self._model_p(self.exit_model,s.x)>=0.5
            self.prediction_checks["exit"]+=1
            self.prediction_errors["exit"]+=int(pred!=bool(y))
            self._learn_binary(self.exit_model,s.x,y)
            self.exit_labels+=1; self.exit_pos+=int(y)
        self.exit_pending=keep

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
        exit_target=300; reentry_target=200
        def pct(v,t):return min(100.0,100.0*float(v)/max(1,float(t)))
        heads={
            "local":{"labels":local_total,"target_labels":local_target,"percent":pct(local_total,local_target)},
            "bounce":{"labels":bounce_total,"target_labels":bounce_target,"percent":pct(bounce_total,bounce_target)},
            "exit":{"labels":self.exit_labels,"target_labels":exit_target,"percent":pct(self.exit_labels,exit_target)},
            "reentry":{"labels":self.reentry_labels,"target_labels":reentry_target,"percent":pct(self.reentry_labels,reentry_target)},
        }
        overall=.40*heads["local"]["percent"]+.10*heads["bounce"]["percent"]+.25*heads["exit"]["percent"]+.25*heads["reentry"]["percent"]
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
            y=s.best_favorable>=max(0.0020,self.round_trip_cost*1.25) and s.best_favorable>1.10*s.worst_adverse
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
        self.local_pending.clear();self.exit_pending.clear();self.reentry_pending.clear()
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
        self._advance_local_labels(ts_ms,price,state)
        self._advance_exit_labels(ts_ms,price)
        self._advance_reentry_labels(ts_ms,price)
        self.structural_history=self._structural_history_report(state,ts_ms)
        qd=self.quant.observe(ts_ms,price,x)
        events.extend(self._sync_strict_local(state,ts_ms,price,x))
        # No recency-window bootstrap participates in trading policy. Candidate
        # discovery below exists only to train earlier local recognition.
        events.extend(self._update_extremes(ts_ms,price,x,state))
        for side in ("LOW","HIGH"):
            events.extend(self._stage_candidate(self.candidates[side],ts_ms,price,x))

        if self.position and self.last_confirmed_local is not None:
            confirmed_side=1 if self.last_confirmed_local.side=="LOW" else -1
            if confirmed_side==-self.position.side:
                events.extend(self._close(ts_ms,price,"OPPOSITE_LOCAL_CONFIRMED"))

        if self.position:
            p=self.position
            cur=p.side*(price/p.entry_price-1.0)
            p.mfe=max(p.mfe,cur);p.mae=min(p.mae,cur)
            px=self._position_x(x,ts_ms,price,qd)
            exit_p=self._model_p(self.exit_model,px)
            agent_same=p.side*float(x.get("agent_consensus",0.0) or 0.0)
            flow_same=p.side*float(x.get("flow_imbalance_raw_60s",x.get("flow_imbalance_60s",0.0)) or 0.0)
            quant_ready=bool(qd.get("champion_ready"))
            quant_same=quant_ready and qd.get("action")==side_name(p.side)
            quant_opp=quant_ready and qd.get("action")==side_name(-p.side)
            give=max(0.0,p.mfe-cur)
            give_ratio=give/max(p.mfe,1e-9) if p.mfe>0 else 0.0
            learned_weight=min(.75,.75*self.exit_labels/300.0)
            heuristic=clip(.45 + .18*(1 if quant_opp else -1 if quant_same else 0) -.22*agent_same -.18*flow_same + .25*give_ratio)
            exit_conf=(1-learned_weight)*heuristic+learned_weight*exit_p
            self._sample_exit(ts_ms,price,x,qd)
            age_s=max(0.0,(ts_ms-p.entry_ts_ms)/1000.0)
            can_policy_exit=age_s>=self.MIN_HOLD_S
            learned_exit_ready=self.exit_labels>=30
            strong_adverse=(flow_same<=-.35 and agent_same<=-.25 and cur<=0.0)
            profit_protection=(p.mfe>=self.round_trip_cost*1.25 and cur>=self.round_trip_cost*.75
                               and give_ratio>=.45 and exit_conf>=.55)
            learned_exit=(learned_exit_ready and exit_conf>=.67)
            if can_policy_exit and (strong_adverse or profit_protection or learned_exit):
                reason=("LEARNED_EXIT" if learned_exit else
                        "BOOTSTRAP_STRONG_ADVERSE" if strong_adverse else
                        "BOOTSTRAP_PROFIT_PROTECTION")
                events.extend(self._close(ts_ms,price,reason))
            else:
                events.append({"event":"HOLD","ts_ms":ts_ms,"side":side_name(p.side),"price":price,
                               "mfe":p.mfe,"mae":p.mae,"current_return":cur,
                               "position_age_s":age_s,"min_hold_s":self.MIN_HOLD_S,
                               "exit_confidence":exit_conf,"quant_action":qd.get("action"),
                               "quant_used_for_exit":quant_ready,
                               "learned_exit_ready":learned_exit_ready,
                               "profit_protection_ready":profit_protection,
                               "strong_adverse":strong_adverse})

        if self.position is None:
            c,local_conf=self._best_local()
            if c is not None:
                side=1 if c.side=="LOW" else -1
                agent_same=side*float(x.get("agent_consensus",0.0) or 0.0)
                flow_same=side*float(x.get("flow_imbalance_raw_60s",x.get("flow_imbalance_60s",0.0)) or 0.0)
                quant_same=qd.get("action")==side_name(side)
                quant_ready=bool(qd.get("champion_ready"))
                cooldown=(self.last_exit is None or ts_ms-int(self.last_exit["exit_ts_ms"])>=60_000)
                same_local_reentry=self._same_local_episode(c)
                if same_local_reentry:
                    self._sample_reentry(ts_ms,price,x,c,qd)
                    rx=self._reentry_x(x,ts_ms,price,c,qd)
                    rp=self._model_p(self.reentry_model,rx)
                    w=min(.80,.80*self.reentry_labels/200.0)
                    heuristic=clip(.50+.22*agent_same+.18*flow_same+.10*(1 if quant_same and quant_ready else 0))
                    re_conf=(1-w)*heuristic+w*rp
                    edge_ok=re_conf>=.60
                else:
                    # Direction comes from the confirmed H1 local, not generic Quant.
                    # A strict already-formed local may start a research episode immediately.
                    edge_ok=(c.source=="STRICT_H1_CONFIRMED")
                    re_conf=None
                if local_conf>=.55 and edge_ok and cooldown:
                    events.extend(self._open(ts_ms,price,side,c,local_conf,qd,reentry=same_local_reentry))
                    if same_local_reentry and events:
                        events[-1]["reentry_confidence"]=re_conf

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
        if self.reentry_labels>=5:
            for feature,w in self._model_weights(self.reentry_model):
                rows.append({"head":"REENTRY","feature":feature,"weight":w})
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
            "version":self.VERSION,"research_only":True,"real_orders":False,
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
            "local_policy":"LOW->LONG until confirmed HIGH; HIGH->SHORT until confirmed LOW; Caterpillar manages HOLD/EXIT/REENTRY inside the leg",
            "bootstrap_diagnostic":{"disabled_for_policy":True,"reason":"recency-window local is training-only"},
            "training_progress":self._training_progress(),
            "structural_history":getattr(self,"structural_history",{}),
            "local_models":{f"{s}_{h}s":{"labels":self.local_labels[(s,h)],"positive":self.local_pos[(s,h)]}
                            for s in ("LOW","HIGH") for h in self.LOCAL_STAGES},
            "bounce_models":{f"{s}_{h}s":{"labels":self.bounce_labels[(s,h)],"positive":self.bounce_pos[(s,h)]}
                            for s in ("LOW","HIGH") for h in self.LOCAL_STAGES},
            "exit_model":{"labels":self.exit_labels,"exit_positive":self.exit_pos},
            "reentry_model":{"labels":self.reentry_labels,"reentry_positive":self.reentry_pos},
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
