#!/usr/bin/env python3
"""Deterministic research/paper-only HYPE decision engine.

Consumes causal, calibrated numerical scores from external experts.
No market connector, account key, position execution or live order placement.
This is a testable policy PROTOTYPE; no proven PnL or OOS edge is claimed.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import math

STATES={"FLAT","LONG","SHORT","HOLD","CLOSE","FLIP"}
SIDES={"LONG","SHORT"}

def valid(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

def getf(d,k,default=0.0):
    v=d.get(k,default)
    return float(v) if valid(v) else float(default)

@dataclass
class PaperPosition:
    side: str
    entry: float
    opened_ms: int
    mfe: float = 0.0
    mae: float = 0.0
    peak_price: float = 0.0
    worst_price: float = 0.0

    def mark(self,price:float):
        move=((price/self.entry)-1.0)*(1 if self.side=="LONG" else -1)
        self.mfe=max(self.mfe,move)
        self.mae=max(self.mae,-move)
        if self.side=="LONG":
            self.peak_price=max(self.peak_price,price)
            self.worst_price=min(self.worst_price,price)
        else:
            self.peak_price=min(self.peak_price,price)
            self.worst_price=max(self.worst_price,price)
        return move

@dataclass
class ResearchStateMachine:
    min_score: float = .68
    min_score_gap: float = .12
    min_net_edge: float = .0012
    min_path_ratio: float = 1.5
    min_opposition: float = .64
    flip_gap: float = .22
    sustained_count: int = 3
    min_hold_ms: int = 3*60*1000
    cooldown_ms: int = 2*60*1000
    correction_atr_multiplier: float = 1.5
    max_giveback_fraction: float = .40
    position: PaperPosition | None = None
    last_close_ms: int = -10**18
    opposite_streak: int = 0
    events: list[dict[str,Any]] = field(default_factory=list)

    def _edge(self,x,side):
        k=side.lower()
        score=getf(x,k+"_score")
        net=getf(x,k+"_net_edge")
        mfe=max(0.0,getf(x,k+"_predicted_mfe"))
        mae=max(0.0,getf(x,k+"_predicted_mae"))
        return {"score":score,"net":net,"mfe":mfe,"mae":mae,
                "path_ratio":mfe/max(mae,1e-5)}

    def _entry_ok(self,edge,other):
        return (edge["score"]>=self.min_score and
                edge["score"]-other["score"]>=self.min_score_gap and
                edge["net"]>self.min_net_edge and
                edge["path_ratio"]>=self.min_path_ratio)

    def _quality_ok(self,x,now):
        if not x.get("data_quality_ok",False):
            return False
        received=x.get("data_ts_ms")
        if not valid(received) or now<int(received):
            return False
        if now-int(received)>5000:
            return False
        if getf(x,"gap_seconds")>10 or not x.get("book_valid",True):
            return False
        return True

    def evaluate(self,x:dict[str,Any])->dict[str,Any]:
        """Every transition is made from the CURRENT snapshot only."""
        now=int(x.get("ts_ms") or 0)
        price=getf(x,"price")
        if now<=0 or price<=0:
            raise ValueError("valid ts_ms and price required")
        long=self._edge(x,"LONG");short=self._edge(x,"SHORT")
        qual=self._quality_ok(x,now)
        info={"timestamp_ms":now,"price":price,"state":"FLAT",
              "side":self.position.side if self.position else None,
              "reason_codes":[],"research_only":True,"real_orders":False,
              "long_score":long["score"],"short_score":short["score"],
              "regime":x.get("regime","UNKNOWN")}
        if not qual:
            self.opposite_streak=0
            if self.position:
                return self._close(now,price,info,"DATA_QUALITY_FAIL")
            info.update(state="FLAT",reason_codes=["DATA_QUALITY_FAIL"])
            return info

        if self.position is None:
            if now-self.last_close_ms<self.cooldown_ms:
                info["reason_codes"]=["ENTRY_COOLDOWN"]
                return info
            if self._entry_ok(long,short):
                return self._open("LONG",now,price,info)
            if self._entry_ok(short,long):
                return self._open("SHORT",now,price,info)
            info["reason_codes"]=["INSUFFICIENT_CAUSAL_EDGE"]
            return info

        p=self.position
        live_move=p.mark(price)
        mine,opp=(long,short) if p.side=="LONG" else (short,long)
        info.update(side=p.side,mfe=p.mfe,mae=p.mae,
                    unrealized_return=live_move,
                    mfe_capture_so_far=(live_move/p.mfe if p.mfe>1e-9 else None),
                    mfe_giveback=max(0.0,p.mfe-live_move))
        held_ms=now-p.opened_ms
        vol=max(0.0,getf(x,"realized_volatility_60m"))
        opp_impact=getf(x,"opposite_price_impact")
        own_impact=getf(x,"own_price_impact")
        # A true opposing transfer requires score, relative advantage, and
        # price-impact evidence sustained across independent observations.
        strong_opposition=(opp["score"]>=self.min_opposition and
                           opp["score"]-mine["score"]>=self.min_score_gap and
                           opp_impact>max(0.0,own_impact))
        self.opposite_streak=self.opposite_streak+1 if strong_opposition else 0
        transfer=self.opposite_streak>=self.sustained_count
        giveback=max(0.0,p.mfe-live_move)
        threshold=max(vol*self.correction_atr_multiplier,
                      p.mfe*self.max_giveback_fraction,
                      .0005)
        weakening=(mine["score"]<self.min_score or
                   own_impact<0 or
                   opp_impact>own_impact)
        info.update(opposing_persistence=self.opposite_streak,
                    mfe_recoil_threshold=threshold)

        if held_ms<self.min_hold_ms:
            info.update(state="HOLD",reason_codes=["MIN_HOLD"])
            return info

        if transfer and weakening:
            if self._entry_ok(opp,mine) and (opp["score"]-mine["score"])>=self.flip_gap:
                # Virtual close and virtual opposite open only; no broker action.
                old=self._close(now,price,info,"SUSTAINED_OPPOSITE_TRANSFER_FLIP")
                new_side="SHORT" if p.side=="LONG" else "LONG"
                self.position=PaperPosition(new_side,price,now,peak_price=price,worst_price=price)
                self.opposite_streak=0
                old.update(state="FLIP",side=new_side,reason_codes=["SUSTAINED_OPPOSITE_TRANSFER_FLIP"])
                return old
            if giveback>=threshold or mine["net"]<=0:
                return self._close(now,price,info,"TRANSFER_AND_MFE_OR_EDGE_DECAY")

        # A standalone MFE recoil is NOT a trading exit. Ignore small
        # corrections while the own-side causal edge remains intact.
        info.update(state="HOLD",reason_codes=[
            "HEALTHY_CORRECTION" if giveback>0 and not transfer else
            "OWN_SIDE_EDGE_PERSISTS"])
        return info

    def _open(self,side,now,price,info):
        self.position=PaperPosition(side,price,now,peak_price=price,worst_price=price)
        self.opposite_streak=0
        info.update(state=side,side=side,reason_codes=["PATH_EDGE_AND_CONFIDENCE"])
        return info

    def _close(self,now,price,info,reason):
        p=self.position
        if p:
            net=((price/p.entry)-1.0)*(1 if p.side=="LONG" else -1)
            row={"side":p.side,"opened_ms":p.opened_ms,"closed_ms":now,
                 "entry":p.entry,"exit":price,"underlying_return_before_costs":net,
                 "mfe":p.mfe,"mae":p.mae,
                 "mfe_capture":net/p.mfe if p.mfe>1e-9 else None,
                 "mfe_giveback":p.mfe-net,"exit_reason":reason}
            self.events.append(row)
        self.position=None
        self.last_close_ms=now
        self.opposite_streak=0
        info.update(state="CLOSE",side=None,reason_codes=[reason])
        return info
