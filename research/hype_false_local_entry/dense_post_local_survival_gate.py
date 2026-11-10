"""Causal post-Local survival confirmation on top of the dense reversal engine.

A HARD/ULTRA flip starts a pending LOW/HIGH entry. A newer same-side extreme
resets the confirmation clock. Entry is emitted only after the pending direction
survives N completed M1 bars and price has moved at least R bps away from the
latest extreme. This is causal and label-blind; strict labels are offline scoring
only. Research/paper only.
"""
import argparse,gzip,json
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from .audit_dense_coverage import read_jsonl
from .causal_sequential_engine import CausalReversalMachine


def ltime(x): return int(x["extreme_interval_start_ms"])
def lprice(x): return float(x["extreme_price"])
def bend(b):
    if b.get("bar_end_ms") is not None:return int(b["bar_end_ms"])
    if b.get("start_ms") is not None:return int(b["start_ms"])+int(b.get("interval_ms",60000))
    return int(b["ts_ms"])


def load(base,name):
    base=Path(base)
    with gzip.open(base/"labels.json.gz","rt",encoding="utf-8") as f:d=json.load(f)
    labels=sorted([x for x in d.get("strict",[]) if x.get("reference_finalized")],key=ltime)
    bars=sorted(list(read_jsonl(base/"compact_1m.jsonl.gz")),key=bend)
    m=CausalReversalMachine(); flips_by_ts={}
    for b in bars:
        ev=m.on_bar(b)
        flips=[e for e in ev if e.core_flip and e.stage in ("HARD_CONFIRMED","ULTRA_CONFIRMED")]
        if flips:
            flips_by_ts.setdefault(bend(b),[]).extend(flips)
    return name,bars,labels,flips_by_ts


@dataclass
class Entry:
    ts_ms:int
    side:str
    close:float
    extreme:float
    age_min:int
    retrace_bps:float


def generate_entries(bars,flips_by_ts,hold_min,min_retrace_bps):
    pending=None
    entries=[]
    active_entry_side=None
    for b in bars:
        end=bend(b); low=float(b["low"]); high=float(b["high"]); close=float(b["close"])
        flips=flips_by_ts.get(end,[])
        if flips:
            e=flips[-1]
            pending={"side":e.side,"since":end,
                     "extreme":low if e.side=="LOW" else high}
        if pending is None:
            continue
        side=pending["side"]; sign=1.0 if side=="LOW" else -1.0
        # New same-side extreme means the old candidate was not final yet.
        if side=="LOW" and low < pending["extreme"]:
            pending["extreme"]=low; pending["since"]=end
        elif side=="HIGH" and high > pending["extreme"]:
            pending["extreme"]=high; pending["since"]=end
        age_min=max(0,int((end-pending["since"])//60000))
        retrace=sign*(close/pending["extreme"]-1.0)*10000.0
        if age_min>=hold_min and retrace>=min_retrace_bps:
            # Avoid repeated same-direction entries until a pending opposite
            # direction actually confirms. If prior entry was same-side, this
            # confirmation adds no new directional information.
            if active_entry_side != side:
                entries.append(Entry(end,side,close,pending["extreme"],age_min,retrace))
                active_entry_side=side
            pending=None
    return entries


def score(labels,entries):
    labels=sorted(labels,key=ltime); entries=sorted(entries,key=lambda x:x.ts_ms)
    true=[]; wrong=[]; no=0
    for i in range(len(labels)-1):
        local=labels[i]; nxt=labels[i+1]
        cand=[e for e in entries if ltime(local)<=e.ts_ms<ltime(nxt)]
        if not cand:
            no+=1; continue
        e=cand[0]
        row={"label_id":local.get("label_id"),"target_side":local["side"],
             "entry_side":e.side,"ts_ms":e.ts_ms,"entry_price":e.close,
             "lag_ms":e.ts_ms-ltime(local),"retrace_bps":e.retrace_bps}
        if e.side==local["side"]:
            sign=1.0 if local["side"]=="LOW" else -1.0
            row["distance_bps"]=sign*(e.close/lprice(local)-1.0)*10000.0
            full=sign*(lprice(nxt)-lprice(local)); rem=sign*(lprice(nxt)-e.close)
            row["remaining"]=rem/full if full>0 else None
            true.append(row)
        else: wrong.append(row)
    n=len(labels)-1; a=len(true)+len(wrong)
    def med(key):
        z=[r[key] for r in true if r.get(key) is not None]
        return median(z) if z else None
    return {"swings":n,"accepted":a,"true_first":len(true),"wrong_first":len(wrong),
            "no_signal":no,"precision":len(true)/a if a else None,
            "recall":len(true)/n if n else None,
            "median_lag_ms":med("lag_ms"),"median_entry_bps":med("distance_bps"),
            "median_remaining":med("remaining"),"wrong_records":wrong}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--period",action="append",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    periods=[]
    for spec in args.period:
        n,b=spec.split("=",1); periods.append(load(b,n))

    holds=(0,1,2,3,5,8,10,15,20,30,45,60)
    retraces=(0,10,20,25,30,40,50,75,100)
    grid=[]
    for h in holds:
        for r in retraces:
            per={}
            for name,bars,labels,flips_by_ts in periods:
                per[name]=score(labels,generate_entries(bars,flips_by_ts,h,r))
            n=sum(x["swings"] for x in per.values())
            t=sum(x["true_first"] for x in per.values())
            w=sum(x["wrong_first"] for x in per.values())
            a=t+w
            grid.append({"hold_min":h,"min_retrace_bps":r,"periods":per,
                         "combined":{"swings":n,"accepted":a,"true_first":t,
                                     "wrong_first":w,
                                     "precision":t/a if a else None,
                                     "recall":t/n if n else None,
                                     "worst_period_precision":min(
                                         [x["precision"] for x in per.values() if x["precision"] is not None],
                                         default=None)}})

    # Global frontier for diagnostics.
    useful=[x for x in grid if x["combined"]["accepted"]>=40]
    top=sorted(useful,key=lambda x:(x["combined"]["precision"],x["combined"]["recall"]),reverse=True)[:20]

    # Chronological selection: first three periods -> last three unchanged.
    train_names={"may","june","julaug"}
    test_names={"lateaug","september","octnov"}
    chrono=[]
    for x in grid:
        tr=[x["periods"][n] for n in train_names]
        te=[x["periods"][n] for n in test_names]
        def agg(z):
            n=sum(q["swings"] for q in z); t=sum(q["true_first"] for q in z); w=sum(q["wrong_first"] for q in z); a=t+w
            return {"swings":n,"accepted":a,"true_first":t,"wrong_first":w,
                    "precision":t/a if a else None,"recall":t/n if n else None}
        chrono.append({"hold_min":x["hold_min"],"min_retrace_bps":x["min_retrace_bps"],
                       "train":agg(tr),"test":agg(te)})
    selected={}
    for target in (0.95,0.97,0.98,0.99,1.0):
        c=[x for x in chrono if x["train"]["accepted"]>=20 and
           x["train"]["precision"] is not None and x["train"]["precision"]>=target]
        selected[str(target)]=max(c,key=lambda x:(x["train"]["recall"],x["train"]["precision"]),default=None)

    result={"status":"research_only_orders_off","grid":grid,"top_global":top,
            "chronological_train_may_june_julaug_test_lateaug_sep_octnov":selected}
    Path(args.out).write_text(json.dumps(result,indent=2)+"\n")
    print("TOP_GLOBAL",json.dumps([{k:v for k,v in x.items() if k!="periods"} for x in top[:10]],separators=(",",":")))
    print("CHRONO",json.dumps(selected,separators=(",",":")))


if __name__=="__main__":main()
