from __future__ import annotations

"""Three-strategy causal PAPER lab for HYPE.

All contours see the same live price/local stream and use the same modeled
round-trip cost and effective exposure. Research only; never places orders.

A) LOCAL_STRAIGHT
   Confirmed H1 LOW -> LONG until confirmed H1 HIGH; confirmed HIGH -> SHORT
   until confirmed LOW. No intra-leg exits/re-entry.

B) CATERPILLAR_SNAKE
   Mirrors the learned Caterpillar ENTER/EXIT/REENTER events.

C) FIBONACCI_ZIGZAG
   Re-anchors a Fibonacci grid on the latest confirmed opposite-local swing.
   Price moves node-to-node. At every crossed Fibonacci node the policy learns
   whether the next node is more likely above or below and may continue or
   flip. This is a zigzag transition strategy, NOT a take-profit ladder.
"""

from pathlib import Path
from typing import Any
import json, math, time

FIB_RATIOS=(0.236,0.382,0.5,0.618,0.786,1.0,1.272,1.618)

def finite(v:Any)->bool:
    return isinstance(v,(int,float)) and math.isfinite(v)

def side_name(side:int)->str:
    return "LONG" if int(side)>0 else "SHORT"

def local_key(local:dict[str,Any]|None)->str|None:
    if not isinstance(local,dict):return None
    hour=local.get("strict_hour_ms")
    price=local.get("price")
    side=local.get("side")
    if hour is None or price is None or side not in ("LOW","HIGH"):return None
    return f"{side}:{int(hour)}:{float(price):.8f}"

class ThreeStrategyLab:
    VERSION="three-strategy-lab-v2-fib-zigzag"

    def __init__(self,checkpoint_dir:Path,cost_floor:float,effective_exposure_x:float=5.0):
        # New path deliberately resets the old ladder experiment without deleting it.
        self.path=Path(checkpoint_dir)/"three_strategy_lab_v2_fib_zigzag.json"
        self.cost_floor=float(cost_floor)
        self.exposure_x=max(0.1,float(effective_exposure_x))
        self.started_ts_ms=int(time.time()*1000)
        self.last_ts_ms=None
        self.last_price=None
        self.last_local_key=None
        self.last_local=None
        self.books={
            "local_straight":self._new_book("LOCAL_STRAIGHT"),
            "caterpillar_snake":self._new_book("CATERPILLAR_SNAKE"),
            "fibonacci_zigzag":self._new_book("FIBONACCI_ZIGZAG"),
        }
        self.gaps=0
        self.fib_grid=[]
        self.fib_grid_local_key=None
        self.fib_last_price=None
        self.fib_pending_transition=None
        self.fib_transition_stats={}
        self.fib_decisions=0
        self.fib_skips=0
        self.fib_last_decision=None
        self._load()

    def _new_book(self,label):
        return {
            "label":label,"equity":100.0,"mark_equity":100.0,"peak_mark_equity":100.0,
            "max_drawdown":0.0,"position":None,"trades":[],"closed_positions":0,
            "wins":0,"losses":0,"censored":0,"events":0,
        }

    def _load(self):
        if not self.path.exists():return
        try:
            obj=json.loads(self.path.read_text(encoding="utf-8"))
            if obj.get("version")!=self.VERSION:return
            self.started_ts_ms=int(obj.get("started_ts_ms") or self.started_ts_ms)
            self.last_ts_ms=obj.get("last_ts_ms");self.last_price=obj.get("last_price")
            self.last_local_key=obj.get("last_local_key");self.last_local=obj.get("last_local")
            self.gaps=int(obj.get("gaps",0))
            books=obj.get("books") or {}
            for name in self.books:
                if isinstance(books.get(name),dict):self.books[name]=books[name]
            self.fib_grid=list(obj.get("fib_grid") or [])
            self.fib_grid_local_key=obj.get("fib_grid_local_key")
            self.fib_last_price=obj.get("fib_last_price")
            self.fib_pending_transition=obj.get("fib_pending_transition")
            self.fib_transition_stats=dict(obj.get("fib_transition_stats") or {})
            self.fib_decisions=int(obj.get("fib_decisions",0))
            self.fib_skips=int(obj.get("fib_skips",0))
            self.fib_last_decision=obj.get("fib_last_decision")
        except Exception:
            pass

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        obj={"version":self.VERSION,"started_ts_ms":self.started_ts_ms,
             "last_ts_ms":self.last_ts_ms,"last_price":self.last_price,
             "last_local_key":self.last_local_key,"last_local":self.last_local,
             "cost_floor":self.cost_floor,"effective_exposure_x":self.exposure_x,
             "gaps":self.gaps,"books":self.books,
             "fib_grid":self.fib_grid,"fib_grid_local_key":self.fib_grid_local_key,
             "fib_last_price":self.fib_last_price,
             "fib_pending_transition":self.fib_pending_transition,
             "fib_transition_stats":self.fib_transition_stats,
             "fib_decisions":self.fib_decisions,"fib_skips":self.fib_skips,
             "fib_last_decision":self.fib_last_decision}
        tmp=self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
        tmp.replace(self.path)

    def _open(self,book,ts_ms,price,side,reason,local=None):
        if book.get("position") is not None:return
        equity=float(book.get("equity",100.0))
        book["position"]={
            "side":int(side),"entry_ts_ms":int(ts_ms),"entry_price":float(price),
            "local_key":local_key(local),"local":local,
            "initial_notional":equity*self.exposure_x,
            "mfe":0.0,"mae":0.0,"reason":reason,
        }
        book["events"]=int(book.get("events",0))+1

    def _mark_book(self,book,price):
        p=book.get("position")
        if not isinstance(p,dict):
            book["mark_equity"]=float(book.get("equity",100.0))
        else:
            side=int(p["side"]);entry=float(p["entry_price"])
            gross=side*(float(price)/entry-1.0)
            p["mfe"]=max(float(p.get("mfe",0.0)),gross)
            p["mae"]=min(float(p.get("mae",0.0)),gross)
            unrealized=float(p["initial_notional"])*(gross-self.cost_floor)
            book["mark_equity"]=max(0.0,float(book.get("equity",100.0))+unrealized)
        peak=max(float(book.get("peak_mark_equity",100.0)),float(book["mark_equity"]))
        book["peak_mark_equity"]=peak
        dd=(peak-float(book["mark_equity"]))/max(peak,1e-9)
        book["max_drawdown"]=max(float(book.get("max_drawdown",0.0)),dd)

    def _close_all(self,book,ts_ms,price,reason):
        p=book.get("position")
        if not isinstance(p,dict):return
        gross=int(p["side"])*(float(price)/float(p["entry_price"])-1.0)
        net=gross-self.cost_floor
        pnl=float(p["initial_notional"])*net
        before=float(book.get("equity",100.0))
        book["equity"]=max(0.0,before+pnl)
        row={
            "entry_ts_ms":p.get("entry_ts_ms"),"exit_ts_ms":int(ts_ms),
            "side":side_name(int(p["side"])),"entry_price":p.get("entry_price"),
            "exit_price":float(price),"gross_return":gross,"net_return":net,
            "pnl":pnl,"equity_before":before,"equity_after":book["equity"],
            "mfe":p.get("mfe"),"mae":p.get("mae"),"reason":reason,
            "local_key":p.get("local_key"),
        }
        trades=book.setdefault("trades",[]);trades.append(row);book["trades"]=trades[-500:]
        book["closed_positions"]=int(book.get("closed_positions",0))+1
        if pnl>0:book["wins"]=int(book.get("wins",0))+1
        else:book["losses"]=int(book.get("losses",0))+1
        book["position"]=None;book["mark_equity"]=float(book["equity"])
        book["events"]=int(book.get("events",0))+1

    def _flip(self,book,ts_ms,price,new_side,reason,local=None):
        p=book.get("position")
        if isinstance(p,dict) and int(p["side"])==int(new_side):return False
        if isinstance(p,dict):self._close_all(book,ts_ms,price,reason+"_FLIP_EXIT")
        self._open(book,ts_ms,price,int(new_side),reason+"_FLIP_ENTER",local=local)
        return True

    def mark(self,ts_ms,price):
        self.last_ts_ms=int(ts_ms);self.last_price=float(price)
        for book in self.books.values():self._mark_book(book,price)

    # ------------------------- Fibonacci zigzag -------------------------

    def _build_fib_grid(self,local,fib_current):
        if not isinstance(local,dict) or not isinstance(fib_current,dict) or not fib_current.get("available"):
            return []
        rows=[]
        try:
            rows.append({"name":"R0.000","ratio":0.0,"price":float(local["price"]),"kind":"LOCAL"})
        except Exception:
            return []
        for z in fib_current.get("levels") or []:
            if not isinstance(z,dict) or not finite(z.get("price")):continue
            rows.append({"name":str(z.get("name") or f"FIB_{z.get('ratio')}"),
                         "ratio":float(z.get("ratio") or 0.0),
                         "price":float(z["price"]),"kind":str(z.get("kind") or "FIB")})
        # Unique by practical price, then sort low -> high so "up/down" is objective.
        uniq={}
        for z in rows:uniq[round(float(z["price"]),8)]=z
        return sorted(uniq.values(),key=lambda z:float(z["price"]))

    def _node_index(self,name):
        for i,z in enumerate(self.fib_grid):
            if z.get("name")==name:return i
        return None

    def _crossed_nodes(self,prev_price,price):
        if not self.fib_grid or not finite(prev_price) or not finite(price) or float(prev_price)==float(price):
            return []
        lo=min(float(prev_price),float(price));hi=max(float(prev_price),float(price))
        rows=[z for z in self.fib_grid if lo<=float(z["price"])<=hi]
        rows.sort(key=lambda z:float(z["price"]),reverse=float(price)<float(prev_price))
        return rows

    def _transition_key(self,node_name,trend_side):
        return f"{int(trend_side)}|{node_name}"

    def _resolve_fib_transition(self,node,ts_ms):
        p=self.fib_pending_transition
        if not isinstance(p,dict):return
        origin=p.get("origin_name");up=p.get("up_name");down=p.get("down_name")
        outcome=None
        if node.get("name")==up:outcome="UP"
        elif node.get("name")==down:outcome="DOWN"
        if outcome is None:return
        key=str(p.get("key"))
        z=self.fib_transition_stats.setdefault(key,{"up":0,"down":0,"resolved":0})
        z[outcome.lower()]=int(z.get(outcome.lower(),0))+1
        z["resolved"]=int(z.get("resolved",0))+1
        z["last_outcome"]=outcome;z["last_resolved_ts_ms"]=int(ts_ms)
        self.fib_pending_transition=None

    def _flow_up_probability(self,features):
        if not isinstance(features,dict):return 0.5
        vals=[]
        for key,scale in (("agent_consensus",1.0),("flow_imbalance_raw_60s",1.0),
                          ("flow_imbalance_60s",1.0),("book_imbalance_25",1.0),
                          ("book_imbalance_raw_25",1.0)):
            v=features.get(key)
            if finite(v):vals.append(max(-1.0,min(1.0,float(v)/scale)))
        if not vals:return 0.5
        mean=sum(vals)/len(vals)
        return max(0.0,min(1.0,0.5+0.25*mean))

    def _fib_direction(self,node,trend_side,fib_report,features,current_side):
        name=str(node.get("name"))
        key=self._transition_key(name,trend_side)
        own=self.fib_transition_stats.get(key) or {}
        resolved=int(own.get("resolved",0) or 0)
        own_up=(float(own.get("up",0))/resolved) if resolved else None

        ext=((fib_report or {}).get("levels") or {}).get(name) or {}
        matured=int(ext.get("matured",0) or 0)
        cont=ext.get("continuation_rate");rev=ext.get("reversal_rate")
        ext_up=None
        if matured>=3 and finite(cont):
            # "continuation" is continuation in swing-trend direction.
            ext_up=float(cont) if int(trend_side)>0 else 1.0-float(cont)
            if finite(rev):
                rev_up=(1.0-float(rev)) if int(trend_side)>0 else float(rev)
                ext_up=.7*ext_up+.3*rev_up

        flow_up=self._flow_up_probability(features)
        weights=[];values=[]
        if own_up is not None and resolved>=3:
            weights.append(.50);values.append(own_up)
        if ext_up is not None:
            weights.append(.30);values.append(ext_up)
        weights.append(.20);values.append(flow_up)
        p_up=sum(w*v for w,v in zip(weights,values))/max(sum(weights),1e-9)

        idx=self._node_index(name)
        has_down=idx is not None and idx>0
        has_up=idx is not None and idx<len(self.fib_grid)-1

        if p_up>=.56 and has_up:
            side=1;reason="LEARNED_UP"
        elif p_up<=.44 and has_down:
            side=-1;reason="LEARNED_DOWN"
        else:
            # Insufficient/conflicted evidence: keep current zigzag direction if possible;
            # on first node bootstrap from the structural local direction.
            side=int(current_side or trend_side)
            if side>0 and not has_up:side=-1
            if side<0 and not has_down:side=1
            reason="HOLD_DIRECTION_WHILE_LEARNING"
            self.fib_skips+=1
        confidence=abs(p_up-.5)*2.0
        return side,p_up,confidence,reason,{"own_resolved":resolved,"external_matured":matured,
                                            "flow_up_probability":flow_up}

    def _set_pending_transition(self,node,trend_side):
        idx=self._node_index(str(node.get("name")))
        if idx is None:return
        down=self.fib_grid[idx-1]["name"] if idx>0 else None
        up=self.fib_grid[idx+1]["name"] if idx<len(self.fib_grid)-1 else None
        self.fib_pending_transition={
            "key":self._transition_key(str(node.get("name")),trend_side),
            "origin_name":str(node.get("name")),"origin_price":float(node.get("price")),
            "up_name":up,"down_name":down,"created_ts_ms":self.last_ts_ms,
        }

    def _fib_on_node(self,ts_ms,node,local,fib_report,features):
        self._resolve_fib_transition(node,ts_ms)
        trend_side=int(((fib_report or {}).get("current") or {}).get("trend_side") or
                       (1 if local.get("side")=="LOW" else -1))
        book=self.books["fibonacci_zigzag"]
        current_side=(book.get("position") or {}).get("side") if isinstance(book.get("position"),dict) else None
        side,p_up,conf,reason,meta=self._fib_direction(node,trend_side,fib_report,features,current_side)
        changed=self._flip(book,ts_ms,float(node["price"]),side,"FIB_NODE_"+reason,local=local)
        self.fib_decisions+=1
        self.fib_last_decision={
            "ts_ms":int(ts_ms),"node":node.get("name"),"node_price":node.get("price"),
            "side":side_name(side),"p_up":p_up,"confidence":conf,"reason":reason,
            "changed_position":changed,**meta,
        }
        self._set_pending_transition(node,trend_side)

    def _advance_fib_zigzag(self,ts_ms,price,local,fib_report,features):
        fib_current=(fib_report or {}).get("current") or {}
        key=local_key(local)
        if not key or not fib_current.get("available"):
            self.fib_last_price=float(price);return
        if key!=self.fib_grid_local_key:
            self.fib_grid=self._build_fib_grid(local,fib_current)
            self.fib_grid_local_key=key
            self.fib_pending_transition=None
            self.fib_last_price=float(price)
            book=self.books["fibonacci_zigzag"]
            if isinstance(book.get("position"),dict):
                self._close_all(book,ts_ms,price,"FIB_REANCHOR_LOCAL")
            # Start from structural direction; subsequent Fib nodes decide continue/flip.
            structural_side=1 if local.get("side")=="LOW" else -1
            self._open(book,ts_ms,price,structural_side,"FIB_LOCAL_BOOTSTRAP",local=local)
            if self.fib_grid:
                nearest=min(self.fib_grid,key=lambda z:abs(float(z["price"])-float(price)))
                swing_trend=int(fib_current.get("trend_side") or structural_side)
                self._set_pending_transition(nearest,swing_trend)
            return

        crossed=self._crossed_nodes(self.fib_last_price,price)
        for node in crossed:
            self._fib_on_node(ts_ms,node,local,fib_report,features)
        self.fib_last_price=float(price)

    # ------------------------- other two strategies -------------------------

    def _on_local_change(self,ts_ms,price,local):
        key=local_key(local)
        if not key or key==self.last_local_key:return
        side=1 if local.get("side")=="LOW" else -1
        straight=self.books["local_straight"]
        sp=straight.get("position")
        if isinstance(sp,dict) and int(sp["side"])!=side:
            self._close_all(straight,ts_ms,price,"OPPOSITE_CONFIRMED_LOCAL")
        if straight.get("position") is None:
            self._open(straight,ts_ms,price,side,"CONFIRMED_LOCAL",local=local)
        self.last_local_key=key;self.last_local=dict(local)

    def _mirror_snake(self,ts_ms,price,events,active_local):
        book=self.books["caterpillar_snake"]
        for e in events or []:
            if not isinstance(e,dict):continue
            kind=str(e.get("event") or "")
            if kind in ("ENTER","REENTER"):
                if book.get("position") is None:
                    self._open(book,ts_ms,float(e.get("price") or price),
                               1 if e.get("side")=="LONG" else -1,kind,local=active_local)
            elif kind=="EXIT":
                if book.get("position") is not None:
                    self._close_all(book,ts_ms,float(e.get("exit_price") or e.get("price") or price),
                                    str(e.get("reason") or "SNAKE_EXIT"))

    def observe(self,ts_ms,price,learner_report,decision,features=None):
        self.mark(ts_ms,price)
        local=learner_report.get("active_local") if isinstance(learner_report,dict) else None
        fib_report=learner_report.get("fibonacci") or {} if isinstance(learner_report,dict) else {}
        if isinstance(local,dict):
            self._on_local_change(ts_ms,price,local)
            self._advance_fib_zigzag(ts_ms,price,local,fib_report,features or {})
        else:
            self.fib_last_price=float(price)
        self._mirror_snake(ts_ms,price,(decision or {}).get("events") or [],local)
        for book in self.books.values():self._mark_book(book,price)
        self.last_ts_ms=int(ts_ms);self.last_price=float(price)

    def on_gap(self,ts_ms,reason):
        self.gaps+=1
        for book in self.books.values():
            if book.get("position") is not None:
                book["censored"]=int(book.get("censored",0))+1
                book["position"]=None;book["mark_equity"]=float(book.get("equity",100.0))
        self.last_local_key=None;self.last_local=None
        self.fib_grid=[];self.fib_grid_local_key=None;self.fib_pending_transition=None
        self.fib_last_price=None;self.last_ts_ms=int(ts_ms)

    def _book_report(self,name):
        b=self.books[name];trades=b.get("trades") or []
        wins=int(b.get("wins",0));closed=int(b.get("closed_positions",0))
        pnl=sum(float(t.get("pnl") or 0.0) for t in trades)
        mfes=[float(t["mfe"]) for t in trades if finite(t.get("mfe"))]
        maes=[float(t["mae"]) for t in trades if finite(t.get("mae"))]
        p=b.get("position")
        return {
            "name":b.get("label"),"equity":float(b.get("mark_equity",100.0)),
            "realized_equity":float(b.get("equity",100.0)),
            "return_pct":float(b.get("mark_equity",100.0))-100.0,
            "realized_return_pct":float(b.get("equity",100.0))-100.0,
            "closed_trades":closed,"wins":wins,"win_rate":wins/closed if closed else None,
            "max_drawdown_pct":100.0*float(b.get("max_drawdown",0.0)),
            "total_realized_pnl":pnl,"censored":int(b.get("censored",0)),
            "mean_mfe":sum(mfes)/len(mfes) if mfes else None,
            "mean_mae":sum(maes)/len(maes) if maes else None,
            "open_position":None if not isinstance(p,dict) else {
                "side":side_name(int(p["side"])),"entry_price":p.get("entry_price"),
                "mfe":p.get("mfe"),"mae":p.get("mae"),
            },
        }

    def _fib_learning_report(self):
        stats={}
        for key,z in self.fib_transition_stats.items():
            resolved=int(z.get("resolved",0) or 0)
            stats[key]={
                "resolved":resolved,
                "up_rate":(float(z.get("up",0))/resolved if resolved else None),
                "down_rate":(float(z.get("down",0))/resolved if resolved else None),
                "last_outcome":z.get("last_outcome"),
            }
        resolved=sum(int(z.get("resolved",0) or 0) for z in self.fib_transition_stats.values())
        return {
            "mode":"NODE_TO_NODE_ZIGZAG",
            "decisions":self.fib_decisions,"skips_or_holds":self.fib_skips,
            "resolved_transitions":resolved,
            "training_percent":min(100.0,100.0*resolved/40.0),
            "grid":self.fib_grid,
            "pending_transition":self.fib_pending_transition,
            "last_decision":self.fib_last_decision,
            "transition_stats":stats,
            "decision_logic":"learn node-to-node up/down; combine own transition history + Fib continuation/reversal labels + live flow/book; continue or flip at every crossed Fib node",
        }

    def report(self,now_ms=None):
        now_ms=int(now_ms or time.time()*1000)
        elapsed_h=max(0.0,(now_ms-self.started_ts_ms)/3_600_000.0)
        strategies={name:self._book_report(name) for name in self.books}
        ranking=sorted(strategies.items(),key=lambda kv:float(kv[1]["return_pct"]),reverse=True)
        leader=ranking[0][0] if ranking else None
        total_closed=sum(int(z["closed_trades"]) for z in strategies.values())
        if elapsed_h>=24 and total_closed>=18:evidence="HIGH"
        elif elapsed_h>=24 and total_closed>=9:evidence="MEDIUM"
        elif total_closed>=3:evidence="LOW"
        else:evidence="INSUFFICIENT"
        return {
            "version":self.VERSION,"started_ts_ms":self.started_ts_ms,
            "elapsed_hours":elapsed_h,"target_hours":24.0,
            "progress_percent":min(100.0,100.0*elapsed_h/24.0),
            "verdict_ready":elapsed_h>=24.0,
            "evidence_quality":evidence,
            "effective_exposure_x":self.exposure_x,
            "modeled_round_trip_cost":self.cost_floor,
            "same_risk_for_all":True,
            "leader":leader,
            "ranking":[{"strategy":name,"return_pct":row["return_pct"],
                        "max_drawdown_pct":row["max_drawdown_pct"],
                        "closed_trades":row["closed_trades"]} for name,row in ranking],
            "strategies":strategies,
            "fibonacci_learning":self._fib_learning_report(),
            "rules":{
                "local_straight":"confirmed H1 local -> hold until opposite confirmed H1 local; no intra-leg re-entry",
                "caterpillar_snake":"same H1 local structure; learned Caterpillar exits and re-enters inside the leg",
                "fibonacci_zigzag":"anchor Fib grid to confirmed local swing; at every crossed Fib node learn next-node UP vs DOWN and continue or flip, creating a node-to-node zigzag",
            },
            "gaps":self.gaps,"research_only":True,"real_orders":False,
        }

def self_test():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        lab=ThreeStrategyLab(Path(td),0.0016,5.0)
        low={"side":"LOW","price":100.0,"strict_hour_ms":1}
        fib={"available":True,"trend_side":1,
             "swing_from":{"side":"HIGH","price":110.0},
             "swing_to":{"side":"LOW","price":100.0},
             "levels":[
                {"name":"R0.236","ratio":.236,"price":102.36,"kind":"RETRACEMENT"},
                {"name":"R0.382","ratio":.382,"price":103.82,"kind":"RETRACEMENT"},
                {"name":"R0.500","ratio":.5,"price":105.0,"kind":"RETRACEMENT"},
                {"name":"R0.618","ratio":.618,"price":106.18,"kind":"RETRACEMENT"},
                {"name":"R0.786","ratio":.786,"price":107.86,"kind":"RETRACEMENT"},
                {"name":"R1.000","ratio":1.0,"price":110.0,"kind":"RETRACEMENT"},
            ]}
        report={"active_local":low,"fibonacci":{"current":fib,"levels":{
            "R0.236":{"matured":10,"continuation_rate":.75,"reversal_rate":.15}
        }}}
        lab.observe(1_000,100.5,report,{"events":[]},{"agent_consensus":.4,"flow_imbalance_raw_60s":.3})
        assert lab.books["local_straight"]["position"]["side"]==1
        assert lab.books["fibonacci_zigzag"]["position"]["side"]==1
        lab.observe(61_000,102.5,report,{"events":[{"event":"ENTER","side":"LONG","price":102.5}]},
                    {"agent_consensus":.4,"flow_imbalance_raw_60s":.3})
        assert lab.books["caterpillar_snake"]["position"]["side"]==1
        assert lab.fib_decisions>=1
        high={"side":"HIGH","price":110.0,"strict_hour_ms":2}
        fib2={"available":True,"trend_side":-1,
              "swing_from":{"side":"LOW","price":100.0},"swing_to":{"side":"HIGH","price":110.0},
              "levels":[{"name":"R0.236","ratio":.236,"price":107.64,"kind":"RETRACEMENT"},
                        {"name":"R1.000","ratio":1.0,"price":100.0,"kind":"RETRACEMENT"}]}
        report2={"active_local":high,"fibonacci":{"current":fib2,"levels":{}}}
        lab.observe(121_000,108.0,report2,{"events":[{"event":"EXIT","side":"LONG","price":108.0,"reason":"TEST"}]}, {})
        out=lab.report(121_000)
        assert out["strategies"]["local_straight"]["closed_trades"]==1
        assert out["strategies"]["caterpillar_snake"]["closed_trades"]==1
        assert "fibonacci_zigzag" in out["strategies"]
        assert out["fibonacci_learning"]["mode"]=="NODE_TO_NODE_ZIGZAG"
        assert out["same_risk_for_all"] is True
