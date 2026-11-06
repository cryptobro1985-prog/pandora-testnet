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

@dataclass
class LocalPending:
    candidate_id:int
    side:str
    stage_s:int
    ts_ms:int
    price:float
    x:dict[str,float]
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
    mfe:float=0.0
    mae:float=0.0
    last_exit_sample_ms:int=0

class CaterpillarQuantLearner:
    VERSION="caterpillar-quant-v1"
    LOCAL_STAGES=(300,600,900)
    LOCAL_FUTURE_S=1800
    EXIT_HORIZON_S=300
    EXIT_SAMPLE_S=30

    def __init__(self,quant_config:dict[str,Any]):
        self.quant=OnlineQuantLearner(copy.deepcopy(quant_config))
        self.local_models={(side,stage):binary_model() for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.local_labels={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.local_pos={(side,stage):0 for side in ("LOW","HIGH") for stage in self.LOCAL_STAGES}
        self.exit_model=binary_model()
        self.exit_labels=0; self.exit_pos=0
        self.candidates={"LOW":None,"HIGH":None}
        self.candidate_seq=0
        self.local_pending:list[LocalPending]=[]
        self.exit_pending:list[ExitPending]=[]
        self.last_confirmed_local:Candidate|None=None
        self.position:PaperPosition|None=None
        self.equity=100.0
        self.peak_equity=100.0
        self.max_drawdown=0.0
        self.round_trip_cost=self.quant.cost_floor
        self.trades=[]
        self.actions=[]
        self.reentries=0
        self.last_exit=None
        self.last_ts_ms=None
        self.last_price=None
        self.censored=0

    def _model_p(self,model,x):
        try:
            p=model.predict_proba_one(clean_features(x))
            return float(p.get(True,p.get(1,0.5)))
        except Exception:
            return 0.5

    def _learn_binary(self,model,x,y):
        model.learn_one(clean_features(x),bool(y))

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
            if self.position and self.position.side>0:
                # A fresh lower low invalidates the previous long-local thesis.
                events.extend(self._close(ts_ms,price,"NEW_LOWER_LOW_INVALIDATES_LONG"))
        if price>=high6 and (high is None or price>high.extreme_price+1e-12):
            c=self._new_candidate("HIGH",price,ts_ms,x)
            events.append({"event":"NEW_LOCAL_CANDIDATE","side":"HIGH","candidate_id":c.ident,"price":price})
            if self.position and self.position.side<0:
                events.extend(self._close(ts_ms,price,"NEW_HIGHER_HIGH_INVALIDATES_SHORT"))
        return events

    def _advance_local_labels(self,ts_ms,price):
        keep=[]
        for s in self.local_pending:
            sign=1.0 if s.side=="LOW" else -1.0
            move=sign*(price/s.price-1.0)
            s.best_favorable=max(s.best_favorable,move)
            s.worst_adverse=max(s.worst_adverse,-move)
            if ts_ms<s.mature_ts_ms:
                keep.append(s);continue
            c=self.candidates.get(s.side)
            invalid=(c is None or c.ident!=s.candidate_id or (c.invalidated_ts_ms is not None and c.invalidated_ts_ms<=s.mature_ts_ms))
            y=(not invalid) and s.best_favorable>=0.0035
            self._learn_binary(self.local_models[(s.side,s.stage_s)],s.x,y)
            self.local_labels[(s.side,s.stage_s)]+=1
            self.local_pos[(s.side,s.stage_s)]+=int(y)
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
            labels=self.local_labels[(c.side,stage)]
            sign=1.0 if c.side=="LOW" else -1.0
            retr=sx["cq_retrace_bps"]
            heuristic=sigmoid((retr-35.0)/22.0 + 1.2*sx["cq_agent_alignment"] + .8*sx["cq_flow_alignment"])
            model_weight=min(.75,.75*labels/200.0)
            conf=(1-model_weight)*heuristic+model_weight*p
            c.stage_done.add(stage);c.stage_conf[stage]=conf;c.stage_retrace_bps[stage]=retr
            self.local_pending.append(LocalPending(
                candidate_id=c.ident,side=c.side,stage_s=stage,ts_ms=ts_ms,price=price,x=sx,
                mature_ts_ms=ts_ms+self.LOCAL_FUTURE_S*1000))
            accepted=conf>=({300:.57,600:.60,900:.62}[stage]) and retr>0
            if accepted:
                c.confirmed_stage=stage
                self.last_confirmed_local=c
            events.append({"event":"LOCAL_STAGE","side":c.side,"candidate_id":c.ident,"stage_s":stage,
                           "confidence":conf,"model_p":p,"heuristic":heuristic,"retrace_bps":retr,
                           "accepted":accepted,"labels_seen":labels})
        return events

    def _best_local(self):
        c=self.last_confirmed_local
        if c is None or c.invalidated_ts_ms is not None or c.confirmed_stage is None:return None,None
        return c,c.stage_conf.get(c.confirmed_stage,0.0)

    def _sample_exit(self,ts_ms,price,x,qd):
        p=self.position
        if p is None:return
        if ts_ms-p.last_exit_sample_ms<self.EXIT_SAMPLE_S*1000:return
        px=self._position_x(x,ts_ms,price,qd)
        self.exit_pending.append(ExitPending(ts_ms,p.side,price,px,ts_ms+self.EXIT_HORIZON_S*1000))
        p.last_exit_sample_ms=ts_ms

    def _open(self,ts_ms,price,side,c,local_conf,qd,reentry=False):
        lev=float(qd.get("leverage") or 5)
        frac=float(qd.get("margin_fraction") or .05)
        lev=max(1.0,min(25.0,lev));frac=max(.02,min(.20,frac))
        margin=self.equity*frac;notional=margin*lev
        re_no=(self.last_exit.get("reentry_no",0)+1 if reentry and self.last_exit else 0)
        self.position=PaperPosition(side,ts_ms,price,lev,frac,notional,margin,c.ident,re_no)
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
             "local_id":p.local_id,"reentry_no":p.reentry_no,
             "leverage":p.leverage,"margin_fraction":p.margin_fraction}
        self.trades.append(row);self.last_exit=row;self.position=None
        return [{"event":"EXIT","ts_ms":ts_ms,**row}]

    def on_gap(self,ts_ms,reason):
        self.censored+=1
        self.local_pending.clear();self.exit_pending.clear()
        for c in self.candidates.values():
            if c:self._invalidate_candidate(c,ts_ms)
        self.candidates={"LOW":None,"HIGH":None};self.last_confirmed_local=None
        if self.position:
            self.position=None
        self.actions.append({"event":"CENSORED","ts_ms":ts_ms,"reason":reason})

    def observe(self,ts_ms,price,x,state):
        events=[]
        self._advance_local_labels(ts_ms,price)
        self._advance_exit_labels(ts_ms,price)
        qd=self.quant.observe(ts_ms,price,x)
        events.extend(self._update_extremes(ts_ms,price,x,state))
        for side in ("LOW","HIGH"):
            events.extend(self._stage_candidate(self.candidates[side],ts_ms,price,x))

        if self.position:
            p=self.position
            cur=p.side*(price/p.entry_price-1.0)
            p.mfe=max(p.mfe,cur);p.mae=min(p.mae,cur)
            px=self._position_x(x,ts_ms,price,qd)
            exit_p=self._model_p(self.exit_model,px)
            agent_same=p.side*float(x.get("agent_consensus",0.0) or 0.0)
            quant_same=qd.get("action")==side_name(p.side)
            quant_opp=qd.get("action")==side_name(-p.side)
            give=max(0.0,p.mfe-cur)
            give_ratio=give/max(p.mfe,1e-9) if p.mfe>0 else 0.0
            learned_weight=min(.75,.75*self.exit_labels/300.0)
            heuristic=clip(.50 + .22*(1 if quant_opp else -1 if quant_same else 0) -.20*agent_same + .25*give_ratio)
            exit_conf=(1-learned_weight)*heuristic+learned_weight*exit_p
            self._sample_exit(ts_ms,price,x,qd)
            if exit_conf>=.67 or (p.mfe>self.round_trip_cost and give_ratio>=.45 and exit_conf>=.52):
                events.extend(self._close(ts_ms,price,"LEARNED_EXIT_MFE_FLOW"))
            else:
                events.append({"event":"HOLD","ts_ms":ts_ms,"side":side_name(p.side),"price":price,
                               "mfe":p.mfe,"mae":p.mae,"current_return":cur,
                               "exit_confidence":exit_conf,"quant_action":qd.get("action")})

        if self.position is None:
            c,local_conf=self._best_local()
            if c is not None:
                side=1 if c.side=="LOW" else -1
                agent_same=side*float(x.get("agent_consensus",0.0) or 0.0)
                quant_same=qd.get("action")==side_name(side)
                edge_ok=quant_same or (agent_same>=.20 and float(qd.get("score",0.0) or 0.0)>=0)
                cooldown=(self.last_exit is None or ts_ms-int(self.last_exit["exit_ts_ms"])>=60_000)
                same_local_reentry=bool(self.last_exit and self.last_exit["local_id"]==c.ident and self.last_exit["side"]==side_name(side))
                if local_conf>=.57 and edge_ok and cooldown:
                    events.extend(self._open(ts_ms,price,side,c,local_conf,qd,reentry=same_local_reentry))

        self.last_ts_ms=ts_ms;self.last_price=price
        for e in events:self.actions.append(e)
        return {"quant":qd,"events":events,"paper":self.paper_snapshot()}

    def paper_snapshot(self):
        p=self.position
        return {"equity":self.equity,"peak_equity":self.peak_equity,"max_drawdown":self.max_drawdown,
                "open_position":None if p is None else {
                    "side":side_name(p.side),"entry_ts_ms":p.entry_ts_ms,"entry_price":p.entry_price,
                    "mfe":p.mfe,"mae":p.mae,"leverage":p.leverage,"margin_fraction":p.margin_fraction,
                    "local_id":p.local_id,"reentry_no":p.reentry_no},
                "closed_trades":len(self.trades),"reentries":self.reentries}

    def report(self):
        captures=[t["mfe_capture_ratio"] for t in self.trades if finite(t.get("mfe_capture_ratio"))]
        wins=sum(t["pnl"]>0 for t in self.trades)
        gp=sum(max(0.0,t["pnl"]) for t in self.trades);gl=-sum(min(0.0,t["pnl"]) for t in self.trades)
        return {
            "version":self.VERSION,"research_only":True,"real_orders":False,
            "equity":self.equity,"return_pct":(self.equity/100.0-1.0)*100.0,
            "max_drawdown_pct":self.max_drawdown*100.0,
            "closed_trades":len(self.trades),"wins":wins,
            "win_rate":wins/len(self.trades) if self.trades else None,
            "profit_factor":gp/gl if gl>0 else (None if gp==0 else 99.0),
            "reentries":self.reentries,
            "mean_mfe_capture_ratio":statistics.fmean(captures) if captures else None,
            "median_mfe_capture_ratio":statistics.median(captures) if captures else None,
            "local_models":{f"{s}_{h}s":{"labels":self.local_labels[(s,h)],"positive":self.local_pos[(s,h)]}
                            for s in ("LOW","HIGH") for h in self.LOCAL_STAGES},
            "exit_model":{"labels":self.exit_labels,"exit_positive":self.exit_pos},
            "active_local":None if self.last_confirmed_local is None else {
                "id":self.last_confirmed_local.ident,"side":self.last_confirmed_local.side,
                "price":self.last_confirmed_local.extreme_price,
                "stage":self.last_confirmed_local.confirmed_stage,
                "confidence":self.last_confirmed_local.stage_conf.get(self.last_confirmed_local.confirmed_stage or 0)},
            "quant":self.quant.report(),
            "censored":self.censored,
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
        return obj

def new_from_config(path:Path):
    return CaterpillarQuantLearner(load_config(path))
