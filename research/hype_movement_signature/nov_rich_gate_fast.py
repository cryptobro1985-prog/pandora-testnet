#!/usr/bin/env python3
from __future__ import annotations
import argparse,gzip,json,math,glob
from pathlib import Path
import numpy as np,pandas as pd

MOVE=.008;ADV=.0035;H=60
LONG_RET240_MAX=-1.0632321402270533
LONG_EFF5_MIN=.008174651851675081
SHORT_EFF5_MIN=.008174651851675081
SHORT_EFF120_MAX=-.03765468290410372
LONG_LIQ300_MIN=9194.60522
SHORT_RET180_MAX=-.00356
SHORT_SELL300_LOG_MIN=14.67727

def load(path):
    rows=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():rows.append(json.loads(line))
    d=pd.DataFrame(rows).sort_values("ts_ms").drop_duplicates("ts_ms").reset_index(drop=True)
    for c in ("high","low","close","buy_notional","sell_notional"):
        d[c]=pd.to_numeric(d[c],errors="coerce")
    d["gap"]=d.get("gap",False).fillna(False).astype(bool)
    return d

def feat(d):
    c=d.close;b=d.buy_notional.clip(lower=0);s=d.sell_notional.clip(lower=0);r=c.pct_change();v=r.rolling(240,min_periods=60).std()
    out={}
    for h in (5,120,180,240):
        ret=c/c.shift(h)-1
        bb=b.rolling(h,min_periods=max(2,h//3)).sum();ss=s.rolling(h,min_periods=max(2,h//3)).sum()
        fl=(bb-ss)/(bb+ss).replace(0,np.nan)
        out[f"ret{h}_raw"]=ret
        out[f"ret{h}"]=(ret/(v*np.sqrt(h)+1e-5)).clip(-10,10)
        out[f"eff{h}"]=(ret/(fl.abs()+.08)).clip(-.25,.25)
    out["sell300_log"]=np.log1p(s.rolling(5,min_periods=3).sum())
    good=(d.gap.astype(float).rolling(15,min_periods=1).max()==0)
    out["long_base"]=good&(out["ret240"]<=LONG_RET240_MAX)&(out["eff5"]>=LONG_EFF5_MIN)
    out["short_base"]=good&(out["eff5"]>=SHORT_EFF5_MIN)&(out["eff120"]<=SHORT_EFF120_MAX)
    return pd.DataFrame(out,index=d.index)

def fut(s,h,ma):
    z=s.shift(-1).iloc[::-1].rolling(h,min_periods=h)
    return (z.max() if ma else z.min()).iloc[::-1]

def to_ms_series(s):
    if pd.api.types.is_datetime64_any_dtype(s):
        return (s.astype("int64")//1_000_000).astype("int64")
    x=pd.to_numeric(s,errors="coerce")
    med=float(np.nanmedian(np.abs(x))) if np.isfinite(x).any() else 0
    if med>1e17:return (x/1e6).round()
    if med>1e14:return (x/1e3).round()
    if med>1e11:return x.round()
    if med>1e9:return (x*1000).round()
    return x.round()

def load_liq(cache):
    parts=[]
    for p in sorted(Path(cache).glob("*_liquidations.parquet")):
        try:parts.append(pd.read_parquet(p))
        except Exception:continue
    if not parts:return pd.DataFrame(columns=["ts_ms","long_liq"])
    q=pd.concat(parts,ignore_index=True)
    tc=next((c for c in ("received_time","trade_time","event_time","timestamp","time") if c in q.columns),None)
    pc=next((c for c in ("price","average_price") if c in q.columns),None)
    qc=next((c for c in ("quantity","qty","size") if c in q.columns),None)
    sc=next((c for c in ("side",) if c in q.columns),None)
    if not all((tc,pc,qc,sc)):return pd.DataFrame(columns=["ts_ms","long_liq"])
    ts=to_ms_series(q[tc]);price=pd.to_numeric(q[pc],errors="coerce");qty=pd.to_numeric(q[qc],errors="coerce")
    side=q[sc].astype(str).str.lower()
    z=pd.DataFrame({"ts_ms":ts,"notional":price*qty,"long_liq":side.eq("sell")})
    z=z[np.isfinite(z.ts_ms)&np.isfinite(z.notional)&(z.notional>0)].copy()
    z["ts_ms"]=z.ts_ms.astype("int64");z=z.sort_values("ts_ms").reset_index(drop=True)
    return z

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--compact",type=Path,required=True);ap.add_argument("--cache",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    d=load(a.compact);x=feat(d);liq=load_liq(a.cache)
    c=d.close;up=fut(d.high,H,True)/c-1;dn=1-fut(d.low,H,False)/c
    valid=up.notna()&dn.notna();yl=(up>=MOVE)&(dn<=ADV)&valid;ys=(dn>=MOVE)&(up<=ADV)&valid

    tsliq=liq.ts_ms.to_numpy(np.int64);notional=liq.notional.to_numpy(float);islong=liq.long_liq.to_numpy(bool)
    prefix=np.concatenate([[0.0],np.cumsum(np.where(islong,notional,0.0))])
    def longliq300(t):
        a0=np.searchsorted(tsliq,int(t)-300000,side="left");b0=np.searchsorted(tsliq,int(t),side="right")
        return float(prefix[b0]-prefix[a0])

    rows=[]
    for i,row in d.iterrows():
        t=int(row.ts_ms)
        if bool(x.long_base.iloc[i]):
            ll=longliq300(t);gate=ll>=LONG_LIQ300_MIN
            rows.append({"i":i,"ts_ms":t,"side":"LONG","true":bool(yl.iloc[i]),"gate":gate,"long_liq_300s":ll})
        if bool(x.short_base.iloc[i]):
            r180=float(x.ret180_raw.iloc[i]);sl=float(x.sell300_log.iloc[i]);gate=(r180<=SHORT_RET180_MAX and sl>=SHORT_SELL300_LOG_MIN)
            rows.append({"i":i,"ts_ms":t,"side":"SHORT","true":bool(ys.iloc[i]),"gate":gate,"ret180_raw":r180,"sell300_log":sl})
    rr=pd.DataFrame(rows)
    def st(side,gated):
        z=rr[rr.side==side]
        if gated:z=z[z.gate==True]
        n=len(z);tp=int(z.true.sum()) if n else 0
        return {"signals":n,"true":tp,"precision":tp/n if n else 0.0}
    rep={"version":"HYPE-NOV-RICH-GATE-FAST-V1",
         "base":{"LONG":st("LONG",False),"SHORT":st("SHORT",False)},
         "rich_gated":{"LONG":st("LONG",True),"SHORT":st("SHORT",True)},
         "gates":{"LONG":{"long_liq_300s_ge":LONG_LIQ300_MIN},
                  "SHORT":{"ret180_raw_le":SHORT_RET180_MAX,"sell300_log_ge":SHORT_SELL300_LOG_MIN}},
         "liq_events_loaded":int(len(liq)),
         "note":"Gates frozen from early/late July movement-label mining; no Local labels and no Nov retuning."}
    (a.out/"NOV_RICH_GATE_FAST_REPORT.json").write_text(json.dumps(rep,indent=2)+"\n")
    rr.to_csv(a.out/"NOV_RICH_GATE_FAST_ROWS.csv",index=False)
    print(json.dumps(rep,indent=2))
if __name__=="__main__":main()
