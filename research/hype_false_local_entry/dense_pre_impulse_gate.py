"""Causal pre-extreme impulse veto for dense post-Local entries.

A proposed LOW/LONG must reverse a meaningful preceding down impulse into its
causal anchor; a proposed HIGH/SHORT must reverse a preceding up impulse.
Thresholds are selected on early periods and scored unchanged on later periods.
"""
import argparse,json
from pathlib import Path
from statistics import median

from .dense_post_local_model_cv import load,build_events


def groups(rows):
    g={}
    for r in rows:g.setdefault((r["period"],r["interval"]),[]).append(r)
    for k in g:g[k].sort(key=lambda x:x["ts_ms"])
    return g


def eval_rows(rows,rule):
    g=groups(rows); true=[];wrong=[];no=0
    for _,rr in g.items():
        first=None
        for r in rr:
            cfg=rule[r["signal_side"]]
            f=r["features"]
            if f[f"pre_impulse{cfg['window']}_bps"] < cfg["min_impulse_bps"]:
                continue
            if f["move30"] > cfg["max_move30_bps"]:
                continue
            first=r;break
        if first is None:no+=1;continue
        if first["y"]==1:true.append(first)
        else:wrong.append(first)
    n=len(g);a=len(true)+len(wrong)
    entry=[];remain=[];lags=[]
    for r in true:
        sign=1.0 if r["target_side"]=="LOW" else -1.0
        entry.append(sign*(r["entry_price"]/r["extreme_price"]-1.0)*10000)
        full=sign*(r["next_price"]-r["extreme_price"]); rem=sign*(r["next_price"]-r["entry_price"])
        if full>0:remain.append(rem/full)
        lags.append(r["lag_ms"])
    return {"swings":n,"accepted":a,"true_first":len(true),"wrong_first":len(wrong),"no_signal":no,
            "precision":len(true)/a if a else None,"recall":len(true)/n if n else None,
            "median_lag_ms":median(lags) if lags else None,
            "median_entry_bps":median(entry) if entry else None,
            "median_remaining":median(remain) if remain else None}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--period",action="append",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    per={}
    for spec in args.period:
        n,b=spec.split("=",1); per[n]=build_events(load(b,n))
    train_names=("may","june","julaug")
    test_names=("lateaug","september","octnov")
    train=[r for n in train_names for r in per[n]]
    test=[r for n in test_names for r in per[n]]

    windows=(15,30,60)
    th=(0,5,10,15,20,25,30,40,50,75,100)
    maxmoves=(-75,-50,-25,0,25,50,75,100)
    candidates=[]
    # Side-specific pre-impulse windows/thresholds; same move30 cap by side can differ.
    for lw in windows:
      for lt in th:
       for hw in windows:
        for ht in th:
         # First search with permissive move cap to isolate impulse effect.
         rule={"LOW":{"window":lw,"min_impulse_bps":lt,"max_move30_bps":100},
               "HIGH":{"window":hw,"min_impulse_bps":ht,"max_move30_bps":100}}
         tr=eval_rows(train,rule)
         if tr["accepted"]>=50:
             candidates.append((rule,tr))
    # Keep the strongest impulse-only rules and refine with move30 caps.
    candidates.sort(key=lambda z:(z[1]["precision"] or 0,z[1]["recall"] or 0),reverse=True)
    seeds=candidates[:40]
    refined=[]
    for rule0,_ in seeds:
      for lm in maxmoves:
       for hm in maxmoves:
        rule={"LOW":dict(rule0["LOW"],max_move30_bps=lm),
              "HIGH":dict(rule0["HIGH"],max_move30_bps=hm)}
        tr=eval_rows(train,rule)
        if tr["accepted"]<30:continue
        te=eval_rows(test,rule)
        refined.append({"rule":rule,"train":tr,"test":te})

    # Chronological frontier, selecting ONLY on train.
    selected={}
    for target in (0.95,0.97,0.98,0.99,1.0):
        eligible=[x for x in refined if x["train"]["precision"] is not None and
                  x["train"]["precision"]>=target]
        selected[str(target)]=max(eligible,key=lambda x:(x["train"]["recall"],x["train"]["precision"]),default=None)
    best=max(refined,key=lambda x:(min(x["train"]["precision"] or 0,x["test"]["precision"] or 0),
                                   x["test"]["precision"] or 0,x["test"]["recall"] or 0),default=None)

    # Per-period score for best robust retrospective candidate, clearly meta-selected.
    if best:
        best["periods"]={n:eval_rows(per[n],best["rule"]) for n in per}
    result={"status":"research_only_orders_off",
            "chronology":{"train":list(train_names),"test":list(test_names)},
            "selected_train_only":selected,
            "best_cross_block_diagnostic_meta_selected":best}
    Path(args.out).write_text(json.dumps(result,indent=2)+"\n")
    print("SELECTED",json.dumps(selected,separators=(",",":")))
    print("BEST",json.dumps(best,separators=(",",":")))


if __name__=="__main__":main()
