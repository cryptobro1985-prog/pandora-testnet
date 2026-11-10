"""Search a two-horizon causal pre-extreme impulse gate."""
import argparse,json
from pathlib import Path
from statistics import median
from .dense_post_local_model_cv import load,build_events

def make_groups(rows):
    g={}
    for r in rows:g.setdefault((r["period"],r["interval"]),[]).append(r)
    for k in g:g[k].sort(key=lambda x:x["ts_ms"])
    return g

def ev(g,rule):
    t=[];w=[];no=0
    for _,rr in g.items():
        first=None
        for r in rr:
            c=rule[r["signal_side"]];f=r["features"]
            if f["pre_impulse30_bps"]<c["min30"]:continue
            if f["pre_impulse60_bps"]<c["min60"]:continue
            if f["move30"]>c["max_move30"]:continue
            first=r;break
        if first is None:no+=1
        elif first["y"]==1:t.append(first)
        else:w.append(first)
    n=len(g);a=len(t)+len(w)
    def med(vals):return median(vals) if vals else None
    entry=[];rem=[];lag=[]
    for r in t:
        s=1.0 if r["target_side"]=="LOW" else -1.0
        entry.append(s*(r["entry_price"]/r["extreme_price"]-1)*10000)
        full=s*(r["next_price"]-r["extreme_price"]); left=s*(r["next_price"]-r["entry_price"])
        if full>0:rem.append(left/full)
        lag.append(r["lag_ms"])
    return {"swings":n,"accepted":a,"true_first":len(t),"wrong_first":len(w),"no_signal":no,
            "precision":len(t)/a if a else None,"recall":len(t)/n if n else None,
            "median_lag_ms":med(lag),"median_entry_bps":med(entry),"median_remaining":med(rem),
            "wrong":[{"period":r["period"],"interval":r["interval"],"ts_ms":r["ts_ms"],
                      "signal_side":r["signal_side"],"target_side":r["target_side"],
                      "pre30":r["features"]["pre_impulse30_bps"],
                      "pre60":r["features"]["pre_impulse60_bps"],
                      "move30":r["features"]["move30"],
                      "retrace":r["features"]["retrace_bps"]} for r in w]}

def main():
    p=argparse.ArgumentParser();p.add_argument("--period",action="append",required=True);p.add_argument("--out",required=True)
    a=p.parse_args();per={}
    for spec in a.period:
        n,b=spec.split("=",1);per[n]=build_events(load(b,n))
    tg=make_groups([r for n in ("may","june","julaug") for r in per[n]])
    vg=make_groups([r for n in ("lateaug","september","octnov") for r in per[n]])
    pg={n:make_groups(x) for n,x in per.items()}
    t30=(0,5,10,15,20,25,30,40,50,75)
    t60=(0,5,10,20,30,50)
    caps=(25,50,75,100,150)
    # First rank side-local settings by their ability to preserve correct events
    # while rejecting wrong events; then evaluate cross-side combinations.
    configs=[]
    for a30 in t30:
      for a60 in t60:
       for cap in caps:
        configs.append({"min30":a30,"min60":a60,"max_move30":cap})
    # Exhaustive side pair is 90k; reduce to configurations that occur on the train
    # first-signal frontier by keeping all but cap duplicates via deterministic sample.
    sidecfg=configs
    results=[]
    # Search full LOW/HIGH pair but use coarse prefilter of 60 best unilateral configs.
    def unilateral(side,cfg):
        other={"min30":0,"min60":0,"max_move30":150}
        rule={"LOW":other.copy(),"HIGH":other.copy()};rule[side]=cfg
        return ev(tg,rule)
    shortlist={}
    for side in ("LOW","HIGH"):
        scored=[(unilateral(side,c),c) for c in sidecfg]
        scored.sort(key=lambda z:((z[0]["precision"] or 0),(z[0]["recall"] or 0)),reverse=True)
        shortlist[side]=[c for _,c in scored[:50]]
    for lc in shortlist["LOW"]:
      for hc in shortlist["HIGH"]:
        rule={"LOW":lc,"HIGH":hc};tr=ev(tg,rule)
        if tr["accepted"]<40:continue
        te=ev(vg,rule)
        results.append({"rule":rule,"train":tr,"test":te})
    sel={}
    for target in (0.95,0.97,0.98,0.99,1.0):
        q=[x for x in results if x["train"]["precision"] is not None and x["train"]["precision"]>=target]
        sel[str(target)]=max(q,key=lambda x:(x["train"]["recall"],x["train"]["precision"]),default=None)
    best=max(results,key=lambda x:(min(x["train"]["precision"] or 0,x["test"]["precision"] or 0),
                                   x["test"]["precision"] or 0,x["test"]["recall"] or 0),default=None)
    if best:best["periods"]={n:ev(pg[n],best["rule"]) for n in pg}
    out={"status":"research_only_orders_off","selected_train_only":sel,"best_meta_diagnostic":best}
    Path(a.out).write_text(json.dumps(out,indent=2)+"\n")
    print("SELECTED",json.dumps(sel,separators=(",",":")))
    print("BEST",json.dumps(best,separators=(",",":")))

if __name__=="__main__":main()
