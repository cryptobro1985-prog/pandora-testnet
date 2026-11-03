from __future__ import annotations
import argparse,csv,json,statistics
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
from universal_features import build_universe,local_cache_for
from universal_params import candidate_space,SEED
from universal_sim import simulate
START=500.

def dt(s):return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--input",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);ap.add_argument("--split-date",default="2026-10-27");ap.add_argument("--candidates",type=int,default=220);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    np,pd,data,cov=build_universe(a.input);eligible={s:df for s,df in data.items() if int(cov.get(s,{}).get("days_ok",0) or 0)>=27 or (s not in cov and len(df)>=1440*27)}
    if len(eligible)<2:raise SystemExit(f"insufficient >=27-day symbols: {sorted(eligible)}")
    plist=candidate_space(a.candidates);keys=sorted({(p.h1_lookback,p.local_min_retrace,p.local_atr_mult) for p in plist});cache=local_cache_for(eligible,np,pd,keys)
    start=min(int(df.ts.min()) for df in eligible.values());end=max(int(df.ts.max()) for df in eligible.values())+60;split=int(dt(a.split_date).timestamp())
    scored=[]
    for p in plist:
        loc=cache[(p.h1_lookback,p.local_min_retrace,p.local_atr_mult)];r=simulate(p,eligible,loc,np,pd,start,split);scored.append((r["score"],p,r))
    scored.sort(key=lambda x:x[0],reverse=True);top=scored[:14]
    d0=datetime.fromtimestamp(start,tz=timezone.utc);d1=datetime.fromtimestamp(split,tz=timezone.utc);span=(d1.date()-d0.date()).days;edges=[d0+timedelta(days=round(span*x/4)) for x in range(5)];ranked=[]
    for base,p,disc in top:
        loc=cache[(p.h1_lookback,p.local_min_retrace,p.local_atr_mult)];fr=[simulate(p,eligible,loc,np,pd,int(x.timestamp()),int(y.timestamp())) for x,y in zip(edges,edges[1:])];pos=sum(x["final_equity"]>START for x in fr);med=statistics.median(x["return_pct"] for x in fr);worst=min(x["return_pct"] for x in fr);ranked.append((base+.035*med+.35*pos+.015*min(0,worst),p,disc,fr))
    ranked.sort(key=lambda x:x[0],reverse=True);_,best,disc,folds=ranked[0];loc=cache[(best.h1_lookback,best.local_min_retrace,best.local_atr_mult)]
    oos=simulate(best,eligible,loc,np,pd,split,end,record=True);full=simulate(best,eligible,loc,np,pd,start,end,record=True);per={s:simulate(best,eligible,loc,np,pd,start,end,symbols_subset=[s]) for s in sorted(eligible)}
    diag=[]
    for _,p,_ in scored[:30]:
        lc=cache[(p.h1_lookback,p.local_min_retrace,p.local_atr_mult)];rr=simulate(p,eligible,lc,np,pd,start,end);diag.append((rr["score"],p,rr))
    diag.sort(key=lambda x:x[0],reverse=True)
    result={"generated_at":datetime.now(timezone.utc).isoformat(),"period":{"start":datetime.fromtimestamp(start,tz=timezone.utc).isoformat(),"end_exclusive":datetime.fromtimestamp(end,tz=timezone.utc).isoformat(),"split":a.split_date},"symbols":sorted(eligible),"coverage":{s:cov.get(s,{}) for s in sorted(eligible)},"selected_params":asdict(best),"selection":"discovery only + four discovery stability folds; OOS untouched","discovery":disc,"discovery_folds":folds,"oos":{k:v for k,v in oos.items() if k!="trade_rows"},"full_30d":{k:v for k,v in full.items() if k!="trade_rows"},"per_symbol_30d":per,"hindsight_full_period_best":{"params":asdict(diag[0][1]),"metrics":diag[0][2],"warning":"diagnostic only; not selected strategy"},"search":{"candidates":len(plist),"seed":SEED},"limits":["public executed trades; no full-depth book","minute aggregation loses within-minute tick ordering","funding and market impact not modeled","historical results do not guarantee future returns"]}
    (a.output/"RESULTS.json").write_text(json.dumps(result,indent=2,default=str));(a.output/"SELECTED_PARAMS.json").write_text(json.dumps(asdict(best),indent=2))
    tr=full.get("trade_rows",[])
    if tr:
        with (a.output/"TRADES.csv").open("w",newline="") as f:w=csv.DictWriter(f,fieldnames=list(tr[0]));w.writeheader();w.writerows(tr)
    with (a.output/"DAILY_EQUITY.csv").open("w",newline="") as f:
        w=csv.writer(f);w.writerow(["date","equity"]);w.writerows(sorted(full["daily_equity"].items()))
    print(json.dumps({"symbols":sorted(eligible),"selected":asdict(best),"discovery":disc,"oos":result["oos"],"full":result["full_30d"]},indent=2,default=str))
if __name__=="__main__":main()
