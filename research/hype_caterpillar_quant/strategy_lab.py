from __future__ import annotations

"""Three-strategy forward PAPER lab for HYPE.

All three contours consume the same causal live price/local stream and use the
same modeled costs and effective exposure. Research only; never places orders.

A) LOCAL_STRAIGHT: confirmed local -> opposite confirmed local, no re-entry.
B) CATERPILLAR_SNAKE: mirrors the learner's ENTER/EXIT/REENTER timing.
C) FIBONACCI_LADDER: confirmed local entry, ladder exits at Fib fractions of
   the previous opposite-local -> current-local swing; remaining size exits on
   opposite confirmed local.
"""

from pathlib import Path
from typing import Any
import json, math, time

FIB_RATIOS=(0.236,0.382,0.5,0.618,0.786,1.0,1.272,1.618)

def finite(v:Any)->bool:
    return isinstance(v,(int,float)) and math.isfinite(v)

def side_int(side:Any)->int:
    s=str(side or "").upper()
    return 1 if s in ("LOW","LONG","ENTER_LONG","BUY") else -1

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
    VERSION="three-strategy-lab-v1"

    def __init__(self,checkpoint_dir:Path,cost_floor:float,effective_exposure_x:float=5.0):
        self.path=Path(checkpoint_dir)/"three_strategy_lab.json"
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
            "fibonacci_ladder":self._new_book("FIBONACCI_LADDER"),
        }
        self.gaps=0
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
                if isinstance(books.get(name),dict):
                    self.books[name]=books[name]
        except Exception:
            pass

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        obj={"version":self.VERSION,"started_ts_ms":self.started_ts_ms,
             "last_ts_ms":self.last_ts_ms,"last_price":self.last_price,
             "last_local_key":self.last_local_key,"last_local":self.last_local,
             "cost_floor":self.cost_floor,"effective_exposure_x":self.exposure_x,
             "gaps":self.gaps,"books":self.books}
        tmp=self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
        tmp.replace(self.path)

    def _open(self,book,ts_ms,price,side,reason,local=None,targets=None):
        if book.get("position") is not None:return
        equity=float(book.get("equity",100.0))
        book["position"]={
            "side":int(side),"entry_ts_ms":int(ts_ms),"entry_price":float(price),
            "local_key":local_key(local),"local":local,
            "initial_notional":equity*self.exposure_x,
            "remaining_fraction":1.0,"realized_pnl":0.0,
            "mfe":0.0,"mae":0.0,"reason":reason,
            "targets":targets or [],"target_hits":[],
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
            remaining=max(0.0,float(p.get("remaining_fraction",1.0)))
            unrealized=float(p["initial_notional"])*remaining*(gross-self.cost_floor)
            book["mark_equity"]=max(0.0,float(book.get("equity",100.0))+unrealized)
        peak=max(float(book.get("peak_mark_equity",100.0)),float(book["mark_equity"]))
        book["peak_mark_equity"]=peak
        dd=(peak-float(book["mark_equity"]))/max(peak,1e-9)
        book["max_drawdown"]=max(float(book.get("max_drawdown",0.0)),dd)

    def mark(self,ts_ms,price):
        self.last_ts_ms=int(ts_ms);self.last_price=float(price)
        for book in self.books.values():self._mark_book(book,price)
        self._advance_fib_targets(ts_ms,price)

    def _finalize_position(self,book,ts_ms,price,reason):
        p=book.get("position")
        if not isinstance(p,dict):return
        pnl=float(p.get("realized_pnl",0.0))
        row={
            "entry_ts_ms":p.get("entry_ts_ms"),"exit_ts_ms":int(ts_ms),
            "side":side_name(int(p["side"])),"entry_price":p.get("entry_price"),
            "exit_price":float(price),"pnl":pnl,
            "equity_after":float(book.get("equity",100.0)),
            "mfe":p.get("mfe"),"mae":p.get("mae"),"reason":reason,
            "target_hits":list(p.get("target_hits") or []),
            "local_key":p.get("local_key"),
        }
        trades=book.setdefault("trades",[]);trades.append(row);book["trades"]=trades[-500:]
        book["closed_positions"]=int(book.get("closed_positions",0))+1
        if pnl>0:book["wins"]=int(book.get("wins",0))+1
        else:book["losses"]=int(book.get("losses",0))+1
        book["position"]=None
        book["mark_equity"]=float(book.get("equity",100.0))
        book["events"]=int(book.get("events",0))+1

    def _close_fraction(self,book,ts_ms,price,fraction,reason,target=None):
        p=book.get("position")
        if not isinstance(p,dict):return
        remaining=max(0.0,float(p.get("remaining_fraction",1.0)))
        frac=max(0.0,min(remaining,float(fraction)))
        if frac<=1e-12:return
        gross=int(p["side"])*(float(price)/float(p["entry_price"])-1.0)
        pnl=float(p["initial_notional"])*frac*(gross-self.cost_floor)
        book["equity"]=max(0.0,float(book.get("equity",100.0))+pnl)
        p["realized_pnl"]=float(p.get("realized_pnl",0.0))+pnl
        p["remaining_fraction"]=max(0.0,remaining-frac)
        if target is not None:
            p.setdefault("target_hits",[]).append({
                "ratio":float(target["ratio"]),"target_price":float(target["price"]),
                "hit_ts_ms":int(ts_ms),"fill_price":float(price),"pnl":pnl,
            })
            target["hit"]=True
        if p["remaining_fraction"]<=1e-9:
            self._finalize_position(book,ts_ms,price,reason)

    def _close_all(self,book,ts_ms,price,reason):
        p=book.get("position")
        if not isinstance(p,dict):return
        self._close_fraction(book,ts_ms,price,float(p.get("remaining_fraction",1.0)),reason)

    def _fib_targets(self,local,fib_current,entry_price):
        if not isinstance(fib_current,dict) or not fib_current.get("available"):return []
        sf=fib_current.get("swing_from") or {}
        st=fib_current.get("swing_to") or {}
        if not sf or not st:return []
        try:
            current_local=float(local["price"]);previous=float(sf["price"])
        except Exception:
            return []
        side=1 if local.get("side")=="LOW" else -1
        span=abs(previous-current_local)
        if span<=1e-12:return []
        rows=[]
        for ratio in FIB_RATIOS:
            target=current_local+side*ratio*span
            ahead=side*(target-float(entry_price))>max(abs(entry_price)*self.cost_floor,1e-9)
            rows.append({"ratio":ratio,"price":target,"eligible":bool(ahead),"hit":False})
        eligible=[z for z in rows if z["eligible"]]
        frac=1.0/len(eligible) if eligible else 0.0
        for z in rows:z["fraction"]=frac if z["eligible"] else 0.0
        return rows

    def _advance_fib_targets(self,ts_ms,price):
        book=self.books["fibonacci_ladder"];p=book.get("position")
        if not isinstance(p,dict):return
        side=int(p["side"])
        for target in p.get("targets") or []:
            if not target.get("eligible") or target.get("hit"):continue
            crossed=(float(price)>=float(target["price"])) if side>0 else (float(price)<=float(target["price"]))
            if crossed:
                self._close_fraction(book,ts_ms,price,float(target.get("fraction",0.0)),
                                     f"FIB_{float(target['ratio']):.3f}",target=target)
                if book.get("position") is None:break

    def _on_local_change(self,ts_ms,price,local,fib_current):
        key=local_key(local)
        if not key or key==self.last_local_key:return
        side=1 if local.get("side")=="LOW" else -1

        straight=self.books["local_straight"]
        sp=straight.get("position")
        if isinstance(sp,dict) and int(sp["side"])!=side:
            self._close_all(straight,ts_ms,price,"OPPOSITE_CONFIRMED_LOCAL")
        if straight.get("position") is None:
            self._open(straight,ts_ms,price,side,"CONFIRMED_LOCAL",local=local)

        fib=self.books["fibonacci_ladder"]
        fp=fib.get("position")
        if isinstance(fp,dict) and int(fp["side"])!=side:
            self._close_all(fib,ts_ms,price,"OPPOSITE_CONFIRMED_LOCAL")
        if fib.get("position") is None:
            targets=self._fib_targets(local,fib_current,price)
            self._open(fib,ts_ms,price,side,"CONFIRMED_LOCAL_FIB_LADDER",local=local,targets=targets)

        self.last_local_key=key
        self.last_local=dict(local)

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

    def observe(self,ts_ms,price,learner_report,decision):
        self.mark(ts_ms,price)
        local=learner_report.get("active_local") if isinstance(learner_report,dict) else None
        fib=(learner_report.get("fibonacci") or {}).get("current") if isinstance(learner_report,dict) else None
        if isinstance(local,dict):
            self._on_local_change(ts_ms,price,local,fib)
        self._mirror_snake(ts_ms,price,(decision or {}).get("events") or [],local)
        for book in self.books.values():self._mark_book(book,price)
        self.last_ts_ms=int(ts_ms);self.last_price=float(price)

    def on_gap(self,ts_ms,reason):
        self.gaps+=1
        for book in self.books.values():
            if book.get("position") is not None:
                book["censored"]=int(book.get("censored",0))+1
                book["position"]=None
                book["mark_equity"]=float(book.get("equity",100.0))
        self.last_local_key=None;self.last_local=None
        self.last_ts_ms=int(ts_ms)

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
            "closed_trades":closed,"wins":wins,
            "win_rate":wins/closed if closed else None,
            "max_drawdown_pct":100.0*float(b.get("max_drawdown",0.0)),
            "total_realized_pnl":pnl,"censored":int(b.get("censored",0)),
            "mean_mfe":sum(mfes)/len(mfes) if mfes else None,
            "mean_mae":sum(maes)/len(maes) if maes else None,
            "open_position":None if not isinstance(p,dict) else {
                "side":side_name(int(p["side"])),"entry_price":p.get("entry_price"),
                "remaining_fraction":p.get("remaining_fraction"),"mfe":p.get("mfe"),"mae":p.get("mae"),
                "target_hits":p.get("target_hits") or [],
                "targets":p.get("targets") or [] if name=="fibonacci_ladder" else [],
            },
        }

    def report(self,now_ms=None):
        now_ms=int(now_ms or time.time()*1000)
        elapsed_h=max(0.0,(now_ms-self.started_ts_ms)/3_600_000.0)
        strategies={name:self._book_report(name) for name in self.books}
        ranking=sorted(strategies.items(),key=lambda kv:float(kv[1]["return_pct"]),reverse=True)
        leader=ranking[0][0] if ranking else None
        total_closed=sum(int(z["closed_trades"]) for z in strategies.values())
        if elapsed_h>=24 and total_closed>=9:evidence="MEDIUM"
        elif total_closed>=18:evidence="HIGH"
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
            "rules":{
                "local_straight":"confirmed H1 local -> hold same direction until opposite confirmed H1 local; no re-entry",
                "caterpillar_snake":"same local direction; exit/re-entry timing mirrors learned Caterpillar policy",
                "fibonacci_ladder":"confirmed local entry; equal remaining-size ladder across eligible 0.236/0.382/0.5/0.618/0.786/1.0/1.272/1.618 targets; remainder exits on opposite local",
            },
            "gaps":self.gaps,"research_only":True,"real_orders":False,
        }

def self_test():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        lab=ThreeStrategyLab(Path(td),0.0016,5.0)
        low={"side":"LOW","price":100.0,"strict_hour_ms":1}
        fib={"available":True,"swing_from":{"side":"HIGH","price":110.0},"swing_to":{"side":"LOW","price":100.0}}
        report={"active_local":low,"fibonacci":{"current":fib}}
        lab.observe(1_000,101.0,report,{"events":[]})
        assert lab.books["local_straight"]["position"]["side"]==1
        assert lab.books["fibonacci_ladder"]["position"]["side"]==1
        lab.observe(61_000,103.0,report,{"events":[{"event":"ENTER","side":"LONG","price":103.0}]})
        assert lab.books["caterpillar_snake"]["position"]["side"]==1
        high={"side":"HIGH","price":110.0,"strict_hour_ms":2}
        fib2={"available":True,"swing_from":{"side":"LOW","price":100.0},"swing_to":{"side":"HIGH","price":110.0}}
        report2={"active_local":high,"fibonacci":{"current":fib2}}
        lab.observe(121_000,108.0,report2,{"events":[{"event":"EXIT","side":"LONG","price":108.0,"reason":"TEST"}]})
        out=lab.report(121_000)
        assert out["strategies"]["local_straight"]["closed_trades"]==1
        assert out["strategies"]["caterpillar_snake"]["closed_trades"]==1
        assert out["strategies"]["fibonacci_ladder"]["closed_trades"]>=1
        assert out["same_risk_for_all"] is True
