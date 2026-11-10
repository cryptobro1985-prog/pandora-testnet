#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import polars as pl

from research.hype_full_micro_202607 import build_full_micro as fm

MOVE=.008; ADV=.0035; HORIZON=60
LONG_RET240_MAX=-1.0632321402270533
LONG_EFF5_MIN=.008174651851675081
SHORT_EFF5_MIN=.008174651851675081
SHORT_EFF120_MAX=-.03765468290410372

def parse_dt(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def cpercentile(s,w=360,minp=120):
    a=s.to_numpy(float);out=np.full(len(a),np.nan)
    for i in range(len(a)):
        h=a[max(0,i-w):i];h=h[np.isfinite(h)]
        if len(h)>=minp and np.isfinite(a[i]):out[i]=float(np.mean(h<=a[i]))
    return pd.Series(out,index=s.index)

def future_roll(s,h,mode):
    z=s.shift(-1).iloc[::-1].rolling(h,min_periods=h)
    return (z.max() if mode=="max" else z.min()).iloc[::-1]

def findcol(cols,*names):
    low={str(c).lower():c for c in cols}
    for n in names:
        if n in cols:return n
        if n.lower() in low:return low[n.lower()]
    return None

def toms(v):
    if isinstance(v,datetime):return int(v.timestamp()*1000)
    try:x=float(v)
    except:return None
    if not math.isfinite(x):return None
    a=abs(x)
    if a>1e17:return int(x/1e6)
    if a>1e14:return int(x/1e3)
    if a>1e11:return int(x)
    if a>1e9:return int(x*1000)
    return int(x)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",required=True);ap.add_argument("--end",required=True)
    ap.add_argument("--cache",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    start,end=parse_dt(a.start),parse_dt(a.end)
    fm.START=start;fm.END=end
    src=fm.Source(a.cache,(os.getenv("CRYPTOHFTDATA_API_KEY") or "").strip() or None)

    fm.prefetch_hours(src,start-timedelta(hours=5),end,("trades","liquidations","open_interest"),workers=24)
    _,mins,_=fm.load_trades(src)
    rows=[r for r in mins if fm.ms(start)<=int(r["start_ms"])<fm.ms(end)]
    d=pd.DataFrame(rows).sort_values("start_ms").reset_index(drop=True)
    d["ts_ms"]=d.start_ms.astype("int64")
    for c in ("high","low","close","buy_notional","sell_notional","trade_count","turnover"):
        d[c]=pd.to_numeric(d[c],errors="coerce")
    d["gap"]=d.get("gap",False).fillna(False).astype(bool)

    c=d.close;b=d.buy_notional.clip(lower=0);s=d.sell_notional.clip(lower=0);r=c.pct_change();v=r.rolling(240,min_periods=60).std()
    f=pd.DataFrame(index=d.index)
    for h in (5,120,240):
        ret=c/c.shift(h)-1
        bb=b.rolling(h,min_periods=max(2,h//3)).sum();ss=s.rolling(h,min_periods=max(2,h//3)).sum()
        flow=(bb-ss)/(bb+ss).replace(0,np.nan)
        f[f"ret{h}_raw"]=ret
        f[f"ret{h}"]=(ret/(v*np.sqrt(h)+1e-5)).clip(-10,10)
        f[f"eff{h}"]=(ret/(flow.abs()+.08)).clip(-.25,.25)
    good=d.gap.astype(float).rolling(15,min_periods=1).max().eq(0)
    f["long_base"]=good&(f.ret240<=LONG_RET240_MAX)&(f.eff5>=LONG_EFF5_MIN)
    f["short_base"]=good&(f.eff5>=SHORT_EFF5_MIN)&(f.eff120<=SHORT_EFF120_MAX)
    f["participation"]=np.log1p(d.turnover.rolling(5,min_periods=3).sum())

    # Load all cached liquidation events.
    liq=[]
    oi=[]
    for p in sorted(a.cache.glob("*_liquidations.parquet")):
        try:
            z=pl.read_parquet(p);cs=z.columns
            tc=findcol(cs,"received_time","trade_time","event_time","timestamp","time")
            pc=findcol(cs,"price","average_price");qc=findcol(cs,"quantity","qty","size");sc=findcol(cs,"side")
            if not all((tc,pc,qc,sc)):continue
            for rr in z.iter_rows(named=True):
                t=toms(rr.get(tc));pr=fm.num(rr.get(pc));q=fm.num(rr.get(qc));side=str(rr.get(sc,"")).lower()
                if t and pr and q and side in ("buy","sell"):
                    liq.append((t,pr*q,side))
        except Exception:pass
    liq.sort()
    for p in sorted(a.cache.glob("*_open_interest.parquet")):
        try:
            z=pl.read_parquet(p);cs=z.columns
            tc=findcol(cs,"timestamp","received_time","event_time","time")
            vc=findcol(cs,"sum_open_interest","open_interest","openInterest")
            if not tc or not vc:continue
            for rr in z.iter_rows(named=True):
                t=toms(rr.get(tc));val=fm.num(rr.get(vc))
                if t and val is not None:oi.append((t,val))
        except Exception:pass
    oi.sort()

    # Per-minute causal aggregates.
    lts=np.array([z[0] for z in liq],dtype=np.int64) if liq else np.array([],dtype=np.int64)
    lnot=np.array([z[1] for z in liq],dtype=float) if liq else np.array([],dtype=float)
    lside=np.array([z[2] for z in liq],dtype=object) if liq else np.array([],dtype=object)
    long_pref=np.concatenate([[0.],np.cumsum(np.where(lside=="sell",lnot,0.))]) if len(liq) else np.array([0.])
    short_pref=np.concatenate([[0.],np.cumsum(np.where(lside=="buy",lnot,0.))]) if len(liq) else np.array([0.])
    ots=np.array([z[0] for z in oi],dtype=np.int64) if oi else np.array([],dtype=np.int64)
    oval=np.array([z[1] for z in oi],dtype=float) if oi else np.array([],dtype=float)

    longliq=[];shortliq=[];oival=[]
    for t in d.ts_ms.astype("int64"):
        if len(lts):
            aa=np.searchsorted(lts,t-300000,"left");bb=np.searchsorted(lts,t,"right")
            longliq.append(long_pref[bb]-long_pref[aa]);shortliq.append(short_pref[bb]-short_pref[aa])
        else:longliq.append(np.nan);shortliq.append(np.nan)
        if len(ots):
            j=np.searchsorted(ots,t,"right")-1
            oival.append(oval[j] if j>=0 and t-ots[j]<=15*60*1000 else np.nan)
        else:oival.append(np.nan)
    f["longliq"]=longliq;f["shortliq"]=shortliq;f["oi"]=oival;f["oi_delta5"]=f.oi.pct_change(5)

    pr=cpercentile(f.participation)
    lr=cpercentile(np.log1p(pd.Series(f.longliq).clip(lower=0)))
    sr=cpercentile(np.log1p(pd.Series(f.shortliq).clip(lower=0)))
    orank=cpercentile(f.oi_delta5)
    ret5=f.ret5_raw

    long_votes=pd.DataFrame({
      "participation":pr>=.60,
      "short_liq":sr>=.75,
      "new_longs":(orank>=.60)&(ret5>0),
      "short_covering":(orank<=.40)&(sr>=.65)&(ret5>0),
    })
    short_votes=pd.DataFrame({
      "participation":pr>=.60,
      "long_liq":lr>=.75,
      "new_shorts":(orank>=.60)&(ret5<0),
      "long_unwind":(orank<=.40)&(lr>=.65)&(ret5<0),
    })
    lv=long_votes.sum(axis=1);sv=short_votes.sum(axis=1)
    long_sig=f.long_base&(lv>=2)
    short_sig=f.short_base&(sv>=2)

    up=future_roll(d.high,HORIZON,"max")/c-1;dn=1-future_roll(d.low,HORIZON,"min")
    valid=up.notna()&dn.notna();yl=(up>=MOVE)&(dn<=ADV)&valid;ys=(dn>=MOVE)&(up<=ADV)&valid
    def stat(mask,y):
        m=mask&valid;n=int(m.sum());tp=int((m&y).sum());base=float(y[valid].mean())
        return {"signals":n,"true":tp,"precision":tp/n if n else 0.0,"base_rate":base,"lift":(tp/n)/base if n and base else 0.0}
    rep={
      "version":"HYPE-FRESH-SCALAR-MICRO-OOS-V1","window":[start.isoformat(),end.isoformat()],
      "local_dependency":False,"threshold_retuned_on_window":False,
      "base":{"LONG":stat(f.long_base,yl),"SHORT":stat(f.short_base,ys)},
      "scalar_micro":{"LONG":stat(long_sig,yl),"SHORT":stat(short_sig,ys)},
      "sources":{"liquidation_events":len(liq),"oi_points":len(oi),"downloads":src.downloads,"bytes":src.bytes},
      "note":"Fresh OOS; causal rolling ranks only; no Local labels or window-fitted thresholds."
    }
    (a.out/"FRESH_SCALAR_MICRO_OOS_REPORT.json").write_text(json.dumps(rep,indent=2)+"\n")
    pd.DataFrame({"ts_ms":d.ts_ms,"long_base":f.long_base,"short_base":f.short_base,
                  "long_votes":lv,"short_votes":sv,"long_signal":long_sig,"short_signal":short_sig,
                  "long_true":yl,"short_true":ys,"up60":up,"dn60":dn}).to_csv(a.out/"FRESH_SCALAR_MICRO_OOS_ROWS.csv",index=False)
    print(json.dumps(rep,indent=2))
if __name__=="__main__":main()
