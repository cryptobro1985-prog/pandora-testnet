#!/usr/bin/env python3
"""HIGH-only EARLY60 persistence grid; PAPER research only.

LOW is untouched. Frozen HARD120 + HIGH Flow V2 remains fallback. This script
precomputes each causal HIGH lineage once, then grids only the +60m persistence
veto so historical regimes are not needlessly replayed for every threshold.
"""
from __future__ import annotations
import argparse,bisect,json,statistics
from functools import lru_cache
from pathlib import Path
from typing import Any
from research.hype_false_local_entry.replay_hard120_30d import (
    read_jsonl_gz,read_json_gz,generate_candidates,pre_move_180_bps,more_extreme,
)
from research.hype_false_local_entry.replay_hard120_plus_high_flow import raw_checkpoint,flow15
from research.hype_false_local_entry.high_flow_shadow_v2 import qualifies as v2_qualifies
from research.hype_local_v5.labels import structural_labels

EARLY_AGE_MS=60*60_000
EARLY_MIN_RETRACE_BPS=80.0
EARLY_MIN_FRACTION=.60
EARLY_MIN_FIRST15_REV_FLOW=.20
EARLY_MIN_FIRST15_TRADES=100
LAST15_THRESHOLDS=(-.10,0.0,.05,.10,.15,.20)
PERSISTENCE_THRESHOLDS=(0.0,.50,.60,.70,.80)

def _window_flow(rows):
    buy=sum(float(r.get("buy_notional") or 0) for r in rows)
    sell=sum(float(r.get("sell_notional") or 0) for r in rows)
    n=sum(int(r.get("trade_count") or 0) for r in rows);den=buy+sell
    return (None if den<=0 else (buy-sell)/den),n

def _early(candidate,end_ms,bars,starts,ends):
    if str(candidate["side"])!="HIGH":return None
    target=int(candidate["extreme_ts_ms"])+EARLY_AGE_MS
    si=bisect.bisect_left(ends,target)
    if si>=len(bars) or int(ends[si])>=int(end_ms):return None
    idx=starts.get(int(candidate["bar_start_ms"]))
    if idx is None or si<=idx:return None
    first=bars[idx+1:idx+16]
    if len(first)!=15:return None
    expected=int(bars[idx]["bar_end_ms"])
    for r in first:
        if int(r["start_ms"])!=expected or bool(r.get("gap",False)):return None
        expected=int(r["bar_end_ms"])
    path=bars[idx+1:si+1]
    if not path:return None
    last=path[-15:] if len(path)>=15 else path
    f1,n1=_window_flow(first);fl,nl=_window_flow(last)
    if f1 is None or fl is None:return None
    p=float(candidate["extreme_price"]);mark=float(bars[si]["close"])
    retr=(p/mark-1)*10000 if p>0 and mark>0 else 0
    pre=max(0.0,float(candidate["pre_move_180_bps"]));frac=retr/pre if pre>0 else 0
    minlow=min(float(r["low"]) for r in path)
    mx=max(0.0,(p/minlow-1)*10000) if minlow>0 else 0
    persist=max(0.0,min(1.0,retr/max(mx,1e-12)))
    return {
      "signal_ts_ms":int(ends[si]),"mark_price":mark,
      "retrace_bps":retr,"retrace_fraction_pre_180":frac,
      "first15_reversal_flow":-float(f1),"first15_trade_count":int(n1),
      "last15_reversal_flow":-float(fl),"last15_trade_count":int(nl),
      "max_reversal_bps":mx,"reversal_persistence":persist,
    }

def _hard(candidate,end_ms,bars,starts):
    cp=raw_checkpoint(candidate,end_ms,bars)
    if cp is None:return None
    retr=float(cp["retrace_bps"]);frac=float(cp["retrace_fraction_pre_180"])
    if retr>=40 and frac>=.45:return (cp,"PRIMARY")
    f=flow15(candidate,bars,starts)
    if f is None:return None
    ok,_=v2_qualifies(side="HIGH",primary_emitted=False,expected_side_ok=True,
        checkpoint_fresh=True,retrace_bps=retr,retrace_fraction_pre_180=frac,
        flow_15=float(f["flow_15"]),trade_count=int(f["trade_count"]))
    return (cp,"HIGH_FLOW_V2") if ok else None

@lru_cache(maxsize=8)
def prepare(compact_s,labels_s,derive):
    compact=Path(compact_s);labels_gz=Path(labels_s)
    bars=read_jsonl_gz(compact);starts={int(b["start_ms"]):i for i,b in enumerate(bars)}
    ends=[int(b["bar_end_ms"]) for b in bars]
    cands=[]
    for e in generate_candidates(bars):
        if 360 not in e["lookbacks_m"]:continue
        idx=starts[e["bar_start_ms"]]
        pm=pre_move_180_bps(e["side"],float(e["extreme_price"]),idx,bars)
        if pm<=0:continue
        z=dict(e);z["pre_move_180_bps"]=pm;cands.append(z)
    doc=read_json_gz(labels_gz);internal=doc.get("internal") or [];source="artifact_internal"
    if not internal and derive:
        internal,_=structural_labels(bars,lookback=3,lookahead=1);source="derived_from_compact_m1_L3_K1"
    labels=sorted((dict(x) for x in internal if bool(x.get("reference_finalized"))),
                  key=lambda x:int(x["extreme_interval_start_ms"]))
    episodes=[]
    for j in range(1,len(labels)-1):
        prev,target,nxt=labels[j-1],labels[j],labels[j+1]
        if str(target["side"])!="HIGH":continue
        start=int(prev["extreme_interval_start_ms"]);tend=int(target["extreme_interval_end_ms"])
        deadline=int(nxt["extreme_interval_start_ms"])
        evs=sorted((e for e in cands if e["side"]=="HIGH" and start<int(e["extreme_ts_ms"])<=tend),
                   key=lambda e:(int(e["extreme_ts_ms"]),int(e["signal_ts_ms"])))
        lineage=[];cur=None
        for e in evs:
            if cur is None:cur=e;continue
            if more_extreme("HIGH",float(e["extreme_price"]),float(cur["extreme_price"])):
                lineage.append((cur,int(e["extreme_ts_ms"])));cur=e
        if cur is not None:lineage.append((cur,deadline))
        options=[]
        for cand,end_ms in lineage:
            true=int(target["extreme_interval_start_ms"])<=int(cand["extreme_ts_ms"])<=int(target["extreme_interval_end_ms"])
            early=_early(cand,end_ms,bars,starts,ends)
            hard=_hard(cand,end_ms,bars,starts)
            options.append({
              "true":bool(true),"target_price":float(target["extreme_price"]),
              "candidate_ts_ms":int(cand["extreme_ts_ms"]),"early":early,
              "hard":None if hard is None else {"payload":hard[0],"kind":hard[1]},
            })
        episodes.append({"episode":j,"options":options})
    return {"source":source,"episodes":episodes}

def _early_ok(m,last15_min,persist_min):
    return bool(
      float(m["retrace_bps"])>=EARLY_MIN_RETRACE_BPS
      and float(m["retrace_fraction_pre_180"])>=EARLY_MIN_FRACTION
      and float(m["first15_reversal_flow"])>=EARLY_MIN_FIRST15_REV_FLOW
      and int(m["first15_trade_count"])>=EARLY_MIN_FIRST15_TRADES
      and float(m["last15_reversal_flow"])>=float(last15_min)
      and float(m["reversal_persistence"])>=float(persist_min)
    )

def score(prepared,last15_min,persist_min):
    rows=[]
    for ep in prepared["episodes"]:
        sigs=[]
        for o in ep["options"]:
            e=o["early"]
            if e is not None and _early_ok(e,last15_min,persist_min):
                sigs.append((int(e["signal_ts_ms"]),0,o,e,"EARLY60_PERSIST"))
            h=o["hard"]
            if h is not None:
                p=h["payload"];sigs.append((int(p["signal_ts_ms"]),1,o,p,h["kind"]))
        if not sigs:
            rows.append({"episode":ep["episode"],"accepted":False});continue
        sigs.sort(key=lambda z:(z[0],z[1]));_,_,o,p,kind=sigs[0]
        r={"episode":ep["episode"],"accepted":True,"true_first":bool(o["true"]),"kind":kind,
           "signal_ts_ms":int(p["signal_ts_ms"]),"retrace_bps":float(p["retrace_bps"])}
        if kind=="EARLY60_PERSIST":
            r.update({"first15_reversal_flow":float(p["first15_reversal_flow"]),
                      "last15_reversal_flow":float(p["last15_reversal_flow"]),
                      "reversal_persistence":float(p["reversal_persistence"])})
        if o["true"]:
            r["entry_distance_pct"]=abs(float(p["mark_price"])/float(o["target_price"])-1)*100
        rows.append(r)
    acc=[r for r in rows if r.get("accepted")];tp=sum(bool(r.get("true_first")) for r in acc);fp=len(acc)-tp
    tr=[r for r in acc if r.get("true_first")];early=[r for r in acc if r.get("kind")=="EARLY60_PERSIST"]
    return {
      "episodes":len(rows),"accepted_first":len(acc),"true_first":tp,"false_first":fp,
      "precision":tp/len(acc) if acc else 0.0,"recall":tp/len(rows) if rows else 0.0,
      "median_entry_distance_pct":statistics.median(r["entry_distance_pct"] for r in tr) if tr else None,
      "early_signals":len(early),"early_true":sum(bool(r.get("true_first")) for r in early),
      "early_false":sum(not bool(r.get("true_first")) for r in early),
      "early_median_distance_pct":statistics.median(r["entry_distance_pct"] for r in early if r.get("true_first"))
          if any(r.get("true_first") for r in early) else None,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--period",action="append",nargs=4,metavar=("NAME","COMPACT","LABELS","DERIVE"))
    ap.add_argument("--output",type=Path,required=True);args=ap.parse_args()
    periods=[]
    for name,compact,labels,derive in args.period or []:
        periods.append((name,prepare(compact,labels,derive.lower() in {"1","true","yes"})))
    if not periods:raise SystemExit("no periods")
    # baseline = same frozen HARD120+V2 fallback, with EARLY layer disabled.
    baseline={name:score(p,999.0,1.1) for name,p in periods}
    grid=[]
    for last15 in LAST15_THRESHOLDS:
      for persist in PERSISTENCE_THRESHOLDS:
        by={name:score(p,last15,persist) for name,p in periods}
        t=sum(v["true_first"] for v in by.values());f=sum(v["false_first"] for v in by.values())
        meds=[v["median_entry_distance_pct"] for v in by.values() if v["median_entry_distance_pct"] is not None]
        row={"last15_min_reversal_flow":last15,"min_reversal_persistence":persist,
             "min_period_precision":min(v["precision"] for v in by.values()),
             "min_period_recall":min(v["recall"] for v in by.values()),
             "pooled_precision":t/max(1,t+f),"early_true":sum(v["early_true"] for v in by.values()),
             "early_false":sum(v["early_false"] for v in by.values()),
             "mean_period_median_distance_pct":statistics.mean(meds) if meds else None,"by_period":by}
        grid.append(row)
    eligible=[r for r in grid if r["min_period_precision"]>=.80 and r["min_period_recall"]>=.40 and r["early_true"]>0]
    eligible.sort(key=lambda r:(r["mean_period_median_distance_pct"] if r["mean_period_median_distance_pct"] is not None else 999,
                                -r["early_true"],r["early_false"],-r["pooled_precision"]))
    preferred=eligible[0] if eligible else None
    out={"title":"HYPE HIGH EARLY60 persistence four-period development grid","mode":"RESEARCH_PAPER_ONLY",
         "real_orders":False,"low_logic_changed":False,"hard120_primary_changed":False,
         "base_early60":{"age_minutes":60,"min_retrace_bps":80.0,"min_retrace_fraction_pre_180":.60,
                         "min_first15_reversal_flow":.20,"min_first15_trade_count":100},
         "baseline_by_period":baseline,
         "selection_warning":"All four regimes are development data after this run; preferred rule requires new terminal-forward validation.",
         "preferred":preferred,"grid":grid}
    args.output.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("HIGH_EARLY60_PERSISTENCE="+json.dumps({"preferred":preferred,"eligible_count":len(eligible)},separators=(",",":")))
if __name__=="__main__":main()
