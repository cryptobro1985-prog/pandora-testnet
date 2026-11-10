#!/usr/bin/env python3
from __future__ import annotations
import argparse,gzip,json,math
from datetime import datetime,timezone
from pathlib import Path
import numpy as np,pandas as pd
from research.hype_full_micro_202607 import build_full_micro as fm

MOVE=.008; ADV=.0035; H=60
LONG_RET240_MAX=-1.0632321402270533
LONG_EFF5_MIN=.008174651851675081
SHORT_EFF5_MIN=.008174651851675081
SHORT_EFF120_MAX=-.03765468290410372

# Frozen July rich-micro movement conditions (early/late July stable).
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
    z=s.shift(-1).iloc[::-1].rolling(h,min_periods=h);return (z.max() if ma else z.min()).iloc[::-1]

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--compact",type=Path,required=True);ap.add_argument("--cache",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    d=load(a.compact);x=feat(d)
    c=d.close;up=fut(d.high,H,True)/c-1;dn=1-fut(d.low,H,False)/c
    valid=up.notna()&dn.notna();yl=(up>=MOVE)&(dn<=ADV)&valid;ys=(dn>=MOVE)&(up<=ADV)&valid

    # Audit only base trigger minutes. Enrich them causally from preserved raw cache.
    rec=[]; idx=[]
    for i,row in d.iterrows():
        if not (bool(x.long_base.iloc[i]) or bool(x.short_base.iloc[i])):continue
        t=int(row.ts_ms); sides=[]
        if bool(x.long_base.iloc[i]):sides.append("LONG")
        if bool(x.short_base.iloc[i]):sides.append("SHORT")
        for side in sides:
            rec.append({"snapshot_ts_ms":t,"features":{},"side":side,"row_i":int(i)})
            idx.append(i)

    start=datetime.fromtimestamp(int(d.ts_ms.iloc[0])/1000,tz=timezone.utc).replace(second=0,microsecond=0)
    end=datetime.fromtimestamp(int(d.ts_ms.iloc[-1])/1000,tz=timezone.utc)
    fm.START=start;fm.END=end
    src=fm.Source(a.cache,None)
    enriched=fm.enrich(src,rec,{},book_warmup_hours=1)

    rows=[]
    for r in enriched:
        i=int(r["row_i"]);f=r["features"];side=r["side"]
        liq300=f.get("fullmicro_long_liq_notional_300s")
        if side=="LONG":
            gate=liq300 is not None and float(liq300)>=LONG_LIQ300_MIN
            true=bool(yl.iloc[i])
        else:
            gate=bool(float(x.ret180_raw.iloc[i])<=SHORT_RET180_MAX and float(x.sell300_log.iloc[i])>=SHORT_SELL300_LOG_MIN)
            true=bool(ys.iloc[i])
        rows.append({"row_i":i,"ts_ms":int(d.ts_ms.iloc[i]),"side":side,"true":true,"micro_gate":gate,
                     "long_liq_300s":liq300,
                     "ret180_raw":float(x.ret180_raw.iloc[i]) if np.isfinite(x.ret180_raw.iloc[i]) else None,
                     "sell300_log":float(x.sell300_log.iloc[i]) if np.isfinite(x.sell300_log.iloc[i]) else None,
                     "book_valid":f.get("fullmicro_book_valid"),
                     "book_imbalance_50":f.get("fullmicro_book_imbalance_50")})
    rr=pd.DataFrame(rows)
    def stat(side,gate):
        z=rr[rr.side==side]
        if gate:z=z[z.micro_gate==True]
        n=len(z);tp=int(z.true.sum()) if n else 0
        return {"signals":n,"true":tp,"precision":tp/n if n else 0.0}
    report={
      "version":"HYPE-NOV-RICH-MICRO-GATE-AUDIT-V1","research_only":True,
      "base":{"LONG":stat("LONG",False),"SHORT":stat("SHORT",False)},
      "micro_gated":{"LONG":stat("LONG",True),"SHORT":stat("SHORT",True)},
      "frozen_gates":{
        "LONG":{"fullmicro_long_liq_notional_300s_ge":LONG_LIQ300_MIN},
        "SHORT":{"ret180_raw_le":SHORT_RET180_MAX,"sell300_log_ge":SHORT_SELL300_LOG_MIN}},
      "records":len(rr),
      "note":"Rich gates came from early/late July movement-label mining, not Local labels and not Nov tuning."
    }
    (a.out/"NOV_RICH_MICRO_GATE_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
    rr.to_csv(a.out/"NOV_RICH_MICRO_GATE_ROWS.csv",index=False)
    print(json.dumps(report,indent=2))
if __name__=="__main__":main()
