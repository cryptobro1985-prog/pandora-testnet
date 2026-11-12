"""Exact replay of the late zero-FP teacher (h1_real_local_detector_v1 RULES) on the rebuilt tape.
Mirrors research/hype_false_local_entry/replay_hard120_30d.py episode logic, with strict L6/K2 labels."""
from __future__ import annotations
import statistics,sys
from core import *
from research.hype_false_local_entry.replay_hard120_30d import generate_candidates,pre_move_180_bps,more_extreme
from research.hype_terminal_local_strategy.h1_real_local_detector_v1 import RULES

def checkpoint(c,end_ms,bars,end_times):
    rule=RULES[c["side"]]
    target=int(c["extreme_ts_ms"])+int(rule["age_minutes"])*60000
    j=bisect.bisect_left(end_times,target)
    if j>=len(bars) or end_times[j]>int(end_ms)-1:return None
    mark=float(bars[j]["close"]);p=float(c["extreme_price"])
    retr=(mark/p-1)*1e4 if c["side"]=="LOW" else (p/mark-1)*1e4
    frac=retr/max(c["pre_move_180_bps"],1e-12)
    if retr>=rule["min_retrace_bps"] and frac>=rule["min_retrace_fraction_pre_180"]:
        return {"signal_ts_ms":end_times[j],"mark_price":mark,"retrace_bps":retr,"frac":frac}
    return None

def replay_period(bars,labels):
    starts={int(b["start_ms"]):i for i,b in enumerate(bars)}
    end_times=[int(b["bar_end_ms"]) for b in bars]
    cands=[]
    for e in generate_candidates(bars):
        if 360 not in e["lookbacks_m"]:continue
        idx=starts[e["bar_start_ms"]];pm=pre_move_180_bps(e["side"],float(e["extreme_price"]),idx,bars)
        if pm<=0:continue
        e=dict(e);e["pre_move_180_bps"]=pm;cands.append(e)
    labs=sorted([x for x in labels if x.get("reference_finalized")],key=lambda x:int(x["extreme_interval_start_ms"]))
    rows=[]
    for j in range(1,len(labs)-1):
        prev,target,nxt=labs[j-1],labs[j],labs[j+1]
        start=int(prev["extreme_interval_start_ms"]);tend=int(target["extreme_interval_end_ms"]);deadline=int(nxt["extreme_interval_start_ms"])
        side=target["side"]
        evs=sorted([e for e in cands if e["side"]==side and start<int(e["extreme_ts_ms"])<=tend],key=lambda e:(int(e["extreme_ts_ms"]),int(e["signal_ts_ms"])))
        cur=None;sigs=[]
        for e in evs:
            if cur is None:cur=e;continue
            if not more_extreme(side,float(e["extreme_price"]),float(cur["extreme_price"])):continue
            s=checkpoint(cur,int(e["extreme_ts_ms"]),bars,end_times)
            if s:sigs.append((s["signal_ts_ms"],cur,s))
            cur=e
        if cur is not None:
            s=checkpoint(cur,deadline,bars,end_times)
            if s:sigs.append((s["signal_ts_ms"],cur,s))
        row={"side":side,"target_label_id":target["label_id"],"target_ts_ms":int(target["extreme_interval_start_ms"]),
             "target_price":float(target["extreme_price"]),"next_price":float(nxt["extreme_price"]),
             "next_ts_ms":int(nxt["extreme_interval_start_ms"]),"accepted":False}
        if sigs:
            sigs.sort(key=lambda z:z[0]);_,c,s=sigs[0]
            true=int(target["extreme_interval_start_ms"])<=int(c["extreme_ts_ms"])<=int(target["extreme_interval_end_ms"])
            row.update(accepted=True,true_first=bool(true),signal_ts_ms=s["signal_ts_ms"],entry_price=s["mark_price"])
            tp=row["target_price"];npx=row["next_price"];m=s["mark_price"]
            row["entry_distance_pct"]=abs(m/tp-1)*100
            row["entry_delay_s"]=(s["signal_ts_ms"]-int(c["extreme_ts_ms"]))/1000
            full=abs(npx-tp)
            row["captured_fraction"]=(max(0.0,npx-m) if side=="LOW" else max(0.0,m-npx))/max(full,1e-12) if true else None
            row["remaining_move_pct"]=((npx/m-1)*100 if side=="LOW" else (m/npx-1)*100) if true else None
        rows.append(row)
    return rows

def summarize(rows):
    acc=[r for r in rows if r["accepted"]];tp=[r for r in acc if r["true_first"]]
    d=[r["entry_distance_pct"] for r in tp]
    return {"episodes":len(rows),"accepted":len(acc),"true_first":len(tp),"false_first":len(acc)-len(tp),
            "coverage":len(tp)/max(1,len(rows)),"median_entry_distance_pct":statistics.median(d) if d else None,
            "p90_entry_distance_pct":float(np.percentile(d,90)) if d else None,
            "median_captured_fraction":statistics.median([r["captured_fraction"] for r in tp]) if tp else None}

PLATEAU_PERIODS={"May":("2026-05-01","2026-06-01"),"Jul":("2026-07-12","2026-08-08"),"Aug":("2026-08-08","2026-09-01"),
                 "Sep":("2026-09-01","2026-10-01"),"Oct":("2026-10-04","2026-11-03")}
def minute_index(iso):
    return int((datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp()-T0)//60)

if __name__=="__main__":
    import json
    tp=Tape();out={};allrows=[]
    for name,(a,b) in PLATEAU_PERIODS.items():
        bars=tp.m1_rows(minute_index(a),minute_index(b))
        labels,_=structural_labels(bars,6,2)
        rows=replay_period(bars,labels)
        for r in rows:r["period"]=name
        allrows+=rows
        out[name]={s:summarize([r for r in rows if r["side"]==s]) for s in ("LOW","HIGH")}
        print(name,out[name])
    out["ALL"]={s:summarize([r for r in allrows if r["side"]==s]) for s in ("LOW","HIGH")}
    out["ALL"]["COMBINED"]=summarize(allrows)
    print(json.dumps(out["ALL"],indent=1))
    json.dump({"summary":out,"rows":allrows},open("/workspace/data/teacher_repro.json","w"))
