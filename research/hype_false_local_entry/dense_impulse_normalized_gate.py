"""Causal impulse-normalized post-Local confirmation gate.

Existing dense HARD/ULTRA flips are filtered only with pre-extreme impulse and
retrace fraction relative to that impulse. Strict labels are offline scoring only.
"""
import argparse,json
from pathlib import Path
from statistics import median
from .dense_post_local_model_cv import load,build_events

def grouped(rows):
    g={}
    for r in rows:g.setdefault((r["period"],r["interval"]),[]).append(r)
    for k in g:g[k].sort(key=lambda x:x["ts_ms"])
    return g

def ev(g,rule):
    t=[];w=[];no=0
    for _,rr in g.items():
        first=None
        for r in rr:
            c=rule[r["signal_side"]]; f=r["features"]
            if f["pre_impulse30_bps"] < c["pre30"]: continue
            if f["pre_impulse60_bps"] < c["pre60"]: continue
            if f["move30"] > c["max_move30"]: continue
            ratio=f["retrace_frac_pre60"]
            if ratio < c["ratio_min"] or ratio > c["ratio_max"]: continue
            first=r; break
        if first is None:no+=1
        elif first["y"]==1:t.append(first)
        else:w.append(first)
    n=len(g);a=len(t)+len(w)
    ent=[];rem=[];lag=[]
    for r in t:
        s=1.0 if r["target_side"]=="LOW" else -1.0
        ent.append(s*(r["entry_price"]/r["extreme_price"]-1.0)*10000.0)
        full=s*(r["next_price"]-r["extreme_price"]); left=s*(r["next_price"]-r["entry_price"])
        if full>0:rem.append(left/full)
        lag.append(r["lag_ms"])
    return {"swings":n,"accepted":a,"true_first":len(t),"wrong_first":len(w),"no_signal":no,
            "precision":len(t)/a if a else None,"recall":len(t)/n if n else None,
            "median_lag_ms":median(lag) if lag else None,
            "median_entry_bps":median(ent) if ent else None,
            "median_remaining":median(rem) if rem else None,
            "wrong":[{"period":r["period"],"interval":r["interval"],"ts_ms":r["ts_ms"],
                      "signal_side":r["signal_side"],"target_side":r["target_side"],
                      "pre30":r["features"]["pre_impulse30_bps"],
                      "pre60":r["features"]["pre_impulse60_bps"],
                      "ratio60":r["features"]["retrace_frac_pre60"],
                      "ratio30":r["features"]["retrace_frac_pre30"],
                      "move30":r["features"]["move30"],
                      "retrace":r["features"]["retrace_bps"]} for r in w]}

def main():
    p=argparse.ArgumentParser();p.add_argument("--period",action="append",required=True);p.add_argument("--out",required=True)
    a=p.parse_args();per={}
    for spec in a.period:
        n,b=spec.split("=",1);per[n]=build_events(load(b,n))
    train_names=("may","june","julaug"); test_names=("lateaug","september","octnov")
    tg=grouped([r for n in train_names for r in per[n]])
    vg=grouped([r for n in test_names for r in per[n]])
    pg={n:grouped(v) for n,v in per.items()}

    # Fixed causal pre-impulse families already discovered; only normalize the
    # reversal by preceding impulse. Ratio grids intentionally coarse.
    bases=[
      {"name":"chronological",
       "LOW":{"pre30":0,"pre60":10,"max_move30":50},
       "HIGH":{"pre30":0,"pre60":30,"max_move30":50}},
      {"name":"broad",
       "LOW":{"pre30":0,"pre60":10,"max_move30":50},
       "HIGH":{"pre30":0,"pre60":10,"max_move30":150}},
      {"name":"dual30",
       "LOW":{"pre30":10,"pre60":10,"max_move30":50},
       "HIGH":{"pre30":10,"pre60":10,"max_move30":150}},
      {"name":"dual30_high30",
       "LOW":{"pre30":10,"pre60":10,"max_move30":50},
       "HIGH":{"pre30":30,"pre60":10,"max_move30":150}},
    ]
    mins=(0,0.10,0.15,0.20,0.25,0.30,0.35,0.40)
    maxs=(0.45,0.50,0.60,0.75,1.0,1.5,2.0,5.0,1e9)
    results=[]
    for b in bases:
      for lmin in mins:
       for lmax in maxs:
        if lmax<lmin: continue
        for hmin in mins:
         for hmax in maxs:
          if hmax<hmin: continue
          rule={
            "LOW":dict(b["LOW"],ratio_min=lmin,ratio_max=lmax),
            "HIGH":dict(b["HIGH"],ratio_min=hmin,ratio_max=hmax),
          }
          tr=ev(tg,rule); te=ev(vg,rule)
          results.append({"family":b["name"],"rule":rule,"train":tr,"test":te})

    selected={}
    for target in (0.95,0.97,0.98,0.99,1.0):
      q=[x for x in results if x["train"]["precision"] is not None and
         x["train"]["precision"]>=target and x["train"]["accepted"]>=40]
      selected[str(target)]=max(q,key=lambda x:(x["train"]["recall"],x["train"]["precision"],
                                                -(x["train"]["median_lag_ms"] or 10**18)),default=None)
    best=max(results,key=lambda x:(min(x["train"]["precision"] or 0,x["test"]["precision"] or 0),
                                   min(x["train"]["recall"] or 0,x["test"]["recall"] or 0),
                                   x["test"]["precision"] or 0),default=None)
    if best:best["periods"]={n:ev(pg[n],best["rule"]) for n in per}
    out={"status":"research_only_orders_off","selected_train_only":selected,
         "best_cross_block_diagnostic_meta_selected":best}
    Path(a.out).write_text(json.dumps(out,indent=2)+"\n")
    print("SELECTED",json.dumps(selected,separators=(",",":")))
    print("BEST",json.dumps(best,separators=(",",":")))

if __name__=="__main__":main()
