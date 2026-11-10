#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,math
from datetime import datetime,timezone,timedelta
from pathlib import Path
import numpy as np,pandas as pd
from research.hype_full_micro_202607 import build_full_micro as fm

MOVE=.008
ADV=.015
LONG_TRADES15_LOG_MIN=9.366420603073673
LONG_RET240_MAX=-0.0223654803306015
SHORT_TRADES120_LOG_MIN=11.347329448638876
SHORT_EFF120_MAX=-0.1057408448492819
LONG_RET60_MAX=-0.024604170297572357
SHORT_EFF5_MIN=0.006498103118136646

def dt(s):
    x=datetime.fromisoformat(s.replace("Z","+00:00"))
    return x if x.tzinfo else x.replace(tzinfo=timezone.utc)

def load_minutes(src,start,end):
    begin=start-timedelta(hours=5);out=[];bar=None
    t=begin.replace(minute=0,second=0,microsecond=0)
    while t<end:
        p=src.get(t,"trades",required=False)
        if p:
            df=fm.read_parquet(p)
            for ts,px,q,side in fm.trade_rows(df):
                if ts<fm.ms(begin) or ts>=fm.ms(end):continue
                k=ts//60000*60000
                if bar is None or int(bar["start_ms"])!=int(k):
                    if bar is not None:out.append(fm.finish(bar,60000))
                    bar=fm.newbar(k,px)
                fm.addbar(bar,ts,px,q,side)
        t+=timedelta(hours=1)
    if bar is not None:out.append(fm.finish(bar,60000))
    return out

def future(s,h,mode):
    z=s.shift(-1).iloc[::-1].rolling(h,min_periods=h)
    return (z.max() if mode=="max" else z.min()).iloc[::-1]

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--start",required=True);ap.add_argument("--end",required=True)
    ap.add_argument("--cache",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    start,end=dt(a.start),dt(a.end)
    src=fm.Source(a.cache,(os.getenv("CRYPTOHFTDATA_API_KEY") or "").strip() or None)
    fm.prefetch_hours(src,start-timedelta(hours=5),end,("trades",),workers=24)
    mins=load_minutes(src,start,end)
    d=pd.DataFrame(mins).sort_values("start_ms").reset_index(drop=True)
    d["ts_ms"]=d.start_ms.astype("int64")
    for c in ("high","low","close","buy_notional","sell_notional","trade_count"):
        d[c]=pd.to_numeric(d[c],errors="coerce")
    d["gap"]=d.get("gap",False).fillna(False).astype(bool)

    c=d.close;b=d.buy_notional.clip(lower=0);s=d.sell_notional.clip(lower=0)
    ret5=c/c.shift(5)-1;ret60=c/c.shift(60)-1;ret120=c/c.shift(120)-1;ret240=c/c.shift(240)-1
    bb=b.rolling(120,min_periods=40).sum();ss=s.rolling(120,min_periods=40).sum()
    flow120=(bb-ss)/(bb+ss).replace(0,np.nan)
    eff120=(ret120/(flow120.abs()+.08)).clip(-.25,.25)
    bb5=b.rolling(5,min_periods=2).sum();ss5=s.rolling(5,min_periods=2).sum()
    flow5=(bb5-ss5)/(bb5+ss5).replace(0,np.nan)
    eff5=(ret5/(flow5.abs()+.08)).clip(-.25,.25)
    trades15=np.log1p(d.trade_count.rolling(15,min_periods=5).sum())
    trades120=np.log1p(d.trade_count.rolling(120,min_periods=40).sum())
    good=d.gap.astype(float).rolling(15,min_periods=1).max().eq(0)

    L=good&(trades15>=LONG_TRADES15_LOG_MIN)&(ret240<=LONG_RET240_MAX)
    S=good&(trades120>=SHORT_TRADES120_LOG_MIN)&(eff120<=SHORT_EFF120_MAX)
    L_trigger=L&(ret60<=LONG_RET60_MAX)
    S_trigger=S&(eff5>=SHORT_EFF5_MIN)

    up=future(d.high,60,"max")/c-1
    dn=1-future(d.low,60,"min")/c
    valid=up.notna()&dn.notna()
    yL=(up>=MOVE)&(dn<=ADV)&valid
    yS=(dn>=MOVE)&(up<=ADV)&valid

    def stat(mask,y):
        m=mask&valid;n=int(m.sum());tp=int((m&y).sum());base=float(y[valid].mean())
        return {"signal_minutes":n,"true_minutes":tp,"precision":tp/n if n else 0.0,
                "base_rate":base,"lift":(tp/n)/base if n and base else 0.0}

    def episodes(mask,y,side,gap_min=30):
        ids=np.where((mask&valid).to_numpy(bool))[0]
        groups=[];cur=[]
        for i in ids:
            if not cur or int(d.ts_ms.iloc[i])-int(d.ts_ms.iloc[cur[-1]])<=gap_min*60000:cur.append(i)
            else:groups.append(cur);cur=[i]
        if cur:groups.append(cur)
        rr=[]
        for g in groups:
            rr.append({"start_ts_ms":int(d.ts_ms.iloc[g[0]]),"end_ts_ms":int(d.ts_ms.iloc[g[-1]]),
                       "signal_minutes":len(g),"any_valid_move":bool(any(bool(y.iloc[i]) for i in g)),
                       "best_mfe":float(max((up.iloc[i] if side=="LONG" else dn.iloc[i]) for i in g)),
                       "worst_mae":float(max((dn.iloc[i] if side=="LONG" else up.iloc[i]) for i in g))})
        return rr

    le=episodes(L,yL,"LONG");se=episodes(S,yS,"SHORT")
    rep={"version":"HYPE-RISK-ALIGNED-TRIGGERS-FRESH-OOS-V1","window":[start.isoformat(),end.isoformat()],
         "target":{"horizon_minutes":60,"mfe_min":MOVE,"mae_max":ADV},
         "frozen_rules":{
           "LONG":{"trades15_log_ge":LONG_TRADES15_LOG_MIN,"ret240_le":LONG_RET240_MAX},
           "SHORT":{"trades120_log_ge":SHORT_TRADES120_LOG_MIN,"eff120_le":SHORT_EFF120_MAX},
           "LONG_TRIGGER":{"ret60_le":LONG_RET60_MAX},
           "SHORT_TRIGGER":{"eff5_ge":SHORT_EFF5_MIN}},
         "setup_quality":{"LONG":stat(L,yL),"SHORT":stat(S,yS)},
         "trigger_quality":{"LONG":stat(L_trigger,yL),"SHORT":stat(S_trigger,yS)},
         "episodes":{"LONG":episodes(L_trigger,yL,"LONG"),"SHORT":episodes(S_trigger,yS,"SHORT")},
         "episode_quality":{},

         "downloads":src.downloads,"bytes":src.bytes,
         "note":"Rules mined from Jul/Aug, validated Sep, Oct holdout remained positive-lift; no Local labels and no fresh-window tuning."}
    (a.out/"RISK_ALIGNED_FRESH_OOS_REPORT.json").write_text(json.dumps(rep,indent=2)+"\n")
    pd.DataFrame({"ts_ms":d.ts_ms,"long_setup":L,"short_setup":S,"long_trigger":L_trigger,"short_trigger":S_trigger,"up60":up,"dn60":dn,
                  "long_true":yL,"short_true":yS,"trades15_log":trades15,
                  "trades120_log":trades120,"ret60":ret60,"ret240":ret240,"eff5":eff5,"eff120":eff120}).to_csv(a.out/"RISK_ALIGNED_FRESH_OOS_ROWS.csv",index=False)
    print(json.dumps(rep,indent=2))
if __name__=="__main__":main()
