"""Final compact causal confirmation gate: pre-impulse + post-local rejection.

Research only. Uses the existing label-blind dense core-flip stream. Strict
labels are used only offline for chronological scoring.
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

def eval_gate(g,rule):
    true=[]; wrong=[]; no=0
    for _,rr in g.items():
        first=None
        for r in rr:
            c=rule[r["signal_side"]]; f=r["features"]
            if f["pre_impulse30_bps"] < c["pre30"]: continue
            if f["pre_impulse60_bps"] < c["pre60"]: continue
            if f["move30"] > c["max_move30"]: continue
            if f["retrace_bps"] < c["retrace"]: continue
            first=r; break
        if first is None:no+=1
        elif first["y"]==1:true.append(first)
        else:wrong.append(first)
    n=len(g); a=len(true)+len(wrong)
    entry=[]; rem=[]; lag=[]
    for r in true:
        s=1.0 if r["target_side"]=="LOW" else -1.0
        entry.append(s*(r["entry_price"]/r["extreme_price"]-1.0)*10000.0)
        full=s*(r["next_price"]-r["extreme_price"]); left=s*(r["next_price"]-r["entry_price"])
        if full>0: rem.append(left/full)
        lag.append(r["lag_ms"])
    return {
      "swings":n,"accepted":a,"true_first":len(true),"wrong_first":len(wrong),"no_signal":no,
      "precision":len(true)/a if a else None,"recall":len(true)/n if n else None,
      "median_lag_ms":median(lag) if lag else None,
      "median_entry_bps":median(entry) if entry else None,
      "median_remaining":median(rem) if rem else None,
      "wrong":[{"period":r["period"],"interval":r["interval"],"ts_ms":r["ts_ms"],
                "signal_side":r["signal_side"],"target_side":r["target_side"],
                "pre30":r["features"]["pre_impulse30_bps"],
                "pre60":r["features"]["pre_impulse60_bps"],
                "move30":r["features"]["move30"],
                "retrace":r["features"]["retrace_bps"]} for r in wrong]
    }

def main():
    p=argparse.ArgumentParser();p.add_argument("--period",action="append",required=True);p.add_argument("--out",required=True)
    a=p.parse_args(); per={}
    for spec in a.period:
        n,b=spec.split("=",1);per[n]=build_events(load(b,n))
    train_names=("may","june","julaug"); test_names=("lateaug","september","octnov")
    tg=grouped([r for n in train_names for r in per[n]])
    vg=grouped([r for n in test_names for r in per[n]])
    pg={n:grouped(v) for n,v in per.items()}

    # Freeze the already-discovered causal pre-impulse families, and search only
    # the post-local rejection threshold. No broad feature fishing.
    families=[
      {"name":"chronological_preimpulse",
       "LOW":{"pre30":0,"pre60":10,"max_move30":50},
       "HIGH":{"pre30":0,"pre60":30,"max_move30":50}},
      {"name":"broad_preimpulse_diagnostic",
       "LOW":{"pre30":0,"pre60":10,"max_move30":50},
       "HIGH":{"pre30":0,"pre60":10,"max_move30":150}},
      {"name":"dual_impulse",
       "LOW":{"pre30":10,"pre60":10,"max_move30":50},
       "HIGH":{"pre30":10,"pre60":10,"max_move30":150}},
    ]
    retraces=(20,22.5,25,27.5,30,32.5,35,40,50,60,75)
    results=[]
    for fam in families:
      for lr in retraces:
       for hr in retraces:
        rule={
          "LOW":dict(fam["LOW"],retrace=lr),
          "HIGH":dict(fam["HIGH"],retrace=hr),
        }
        tr=eval_gate(tg,rule); te=eval_gate(vg,rule)
        results.append({"family":fam["name"],"rule":rule,"train":tr,"test":te})

    selected={}
    for target in (0.95,0.97,0.98,0.99,1.0):
      eligible=[x for x in results if x["train"]["precision"] is not None and
                x["train"]["precision"]>=target and x["train"]["accepted"]>=40]
      selected[str(target)]=max(eligible,key=lambda x:(x["train"]["recall"],x["train"]["precision"]),default=None)

    # Diagnostic only: optimize worst block precision, then recall. Explicitly
    # meta-selected and not untouched OOS.
    best=max(results,key=lambda x:(min(x["train"]["precision"] or 0,x["test"]["precision"] or 0),
                                   min(x["train"]["recall"] or 0,x["test"]["recall"] or 0),
                                   x["test"]["precision"] or 0),default=None)
    if best:
      best["periods"]={n:eval_gate(pg[n],best["rule"]) for n in per}
    out={"status":"research_only_orders_off",
         "chronology":{"train":list(train_names),"test":list(test_names)},
         "selected_train_only":selected,
         "best_cross_block_diagnostic_meta_selected":best}
    Path(a.out).write_text(json.dumps(out,indent=2)+"\n")
    print("SELECTED",json.dumps(selected,separators=(",",":")))
    print("BEST",json.dumps(best,separators=(",",":")))

if __name__=="__main__":main()
