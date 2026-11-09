#!/usr/bin/env python3
"""Score frozen HYPE_LOCAL_ULTRA_SURVIVAL_V2 on a compact HYPE tape.

Research only. The V2 thresholds are fixed in
research/hype_local_only/results/HYPE_LOCAL_ULTRA_SURVIVAL_V2.json.
Labels are used only after causal candidate/signal generation for scoring.
"""
from __future__ import annotations
import argparse,bisect,gzip,json
from collections import deque
from pathlib import Path
from research.hype_local_v5.labels import structural_labels

RULES={
    "LOW":{"age_minutes":215,"min_retrace_bps":130.0,"min_fraction":0.52},
    "HIGH":{"age_minutes":250,"min_retrace_bps":65.0,"min_fraction":0.50},
}

def read_jsonl_gz(path):
    out=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():out.append(json.loads(line))
    return out

def load_labels(path,bars):
    with gzip.open(path,"rt",encoding="utf-8") as f:doc=json.load(f)
    labs=doc.get("internal") or []
    source="artifact_internal"
    if not labs:
        labs,_=structural_labels(bars,lookback=3,lookahead=1)
        source="derived_from_compact_m1_L3_K1"
    labs=[dict(x) for x in labs if bool(x.get("reference_finalized"))]
    labs.sort(key=lambda x:int(x["extreme_interval_start_ms"]))
    return labs,source

def candidates(bars):
    hist=deque(maxlen=360);out=[]
    for idx,b in enumerate(bars):
        prior=list(hist)
        if len(prior)>=360:
            lo=float(b["low"]);hi=float(b["high"])
            p180=bars[idx-180:idx]
            if len(p180)>=180 and lo<=min(float(x["low"]) for x in prior[-360:]):
                opp=max(float(x["high"]) for x in p180)
                pm=max(0.0,(opp/lo-1.0)*10000.0)
                if pm>0:out.append({"side":"LOW","ts_ms":int(b.get("low_ts_ms") or b["start_ms"]),"price":lo,"pre_move_180_bps":pm})
            if len(p180)>=180 and hi>=max(float(x["high"]) for x in prior[-360:]):
                opp=min(float(x["low"]) for x in p180)
                pm=max(0.0,(hi/opp-1.0)*10000.0) if opp>0 else 0.0
                if pm>0:out.append({"side":"HIGH","ts_ms":int(b.get("high_ts_ms") or b["start_ms"]),"price":hi,"pre_move_180_bps":pm})
        hist.append(b)
    return out

def more_extreme(side,new,old):
    return new<old if side=="LOW" else new>old

def sample(c,stop_ms,ends,closes):
    rule=RULES[c["side"]]
    target=int(c["ts_ms"])+int(rule["age_minutes"])*60000
    i=bisect.bisect_left(ends,target)
    if i>=len(ends) or int(ends[i])>=int(stop_ms):return None
    mark=float(closes[i]);p=float(c["price"])
    retr=(mark/p-1.0)*10000.0 if c["side"]=="LOW" else (p/mark-1.0)*10000.0
    frac=retr/max(float(c["pre_move_180_bps"]),1e-12)
    return {"signal_ts_ms":int(ends[i]),"mark_price":mark,"retrace_bps":retr,"retrace_fraction_pre_180":frac}

def replay(compact,labels_path):
    bars=read_jsonl_gz(compact);labels,label_source=load_labels(labels_path,bars)
    cands=candidates(bars)
    ends=[int(b.get("bar_end_ms",int(b["start_ms"])+60000)) for b in bars]
    closes=[float(b["close"]) for b in bars]
    rows=[]
    for j in range(1,len(labels)-1):
        prev,target,nxt=labels[j-1],labels[j],labels[j+1]
        side=str(target["side"]);rule=RULES[side]
        start=int(prev["extreme_interval_start_ms"]);target_end=int(target["extreme_interval_end_ms"]);deadline=int(nxt["extreme_interval_start_ms"])
        evs=sorted([e for e in cands if e["side"]==side and start<int(e["ts_ms"])<=target_end],key=lambda x:x["ts_ms"])
        cur=None;sigs=[]
        for e in evs:
            if cur is None:cur=e;continue
            if not more_extreme(side,float(e["price"]),float(cur["price"])):continue
            s=sample(cur,int(e["ts_ms"]),ends,closes)
            if s and s["retrace_bps"]>=rule["min_retrace_bps"] and s["retrace_fraction_pre_180"]>=rule["min_fraction"]:
                sigs.append((s["signal_ts_ms"],cur,s))
            cur=e
        if cur is not None:
            s=sample(cur,deadline,ends,closes)
            if s and s["retrace_bps"]>=rule["min_retrace_bps"] and s["retrace_fraction_pre_180"]>=rule["min_fraction"]:
                sigs.append((s["signal_ts_ms"],cur,s))
        if not sigs:
            rows.append({"episode":j,"side":side,"accepted":False});continue
        sigs.sort(key=lambda x:x[0]);_,cand,s=sigs[0]
        true=int(target["extreme_interval_start_ms"])<=int(cand["ts_ms"])<=int(target["extreme_interval_end_ms"])
        row={"episode":j,"side":side,"accepted":True,"true_first":bool(true),"candidate_ts_ms":int(cand["ts_ms"]),"candidate_price":float(cand["price"]),**s}
        if true:
            tp=float(target["extreme_price"]);row["entry_distance_pct"]=abs(float(s["mark_price"])/tp-1.0)*100.0
        rows.append(row)
    def summary(rr):
        acc=[x for x in rr if x.get("accepted")];tp=sum(bool(x.get("true_first")) for x in acc);fp=len(acc)-tp
        return {"episodes":len(rr),"accepted":len(acc),"true_first":tp,"false_first":fp,"precision":tp/len(acc) if acc else None,"recall":tp/len(rr) if rr else 0.0}
    return {"version":"HYPE_LOCAL_ULTRA_SURVIVAL_V2_SCORE","research_only":True,"real_orders":False,"rules":RULES,"label_source":label_source,"evaluation":summary(rows),"by_side":{s:summary([x for x in rows if x["side"]==s]) for s in ("LOW","HIGH")},"episode_rows":rows}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--compact-1m",type=Path,required=True);ap.add_argument("--labels-gz",type=Path,required=True);ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args();out=replay(a.compact_1m,a.labels_gz);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"evaluation":out["evaluation"],"by_side":out["by_side"]},ensure_ascii=False))

if __name__=="__main__":main()
