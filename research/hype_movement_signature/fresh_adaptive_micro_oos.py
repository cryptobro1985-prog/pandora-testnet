#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math,os
from datetime import datetime,timezone,timedelta
from pathlib import Path
import numpy as np,pandas as pd

from research.hype_full_micro_202607 import build_full_micro as fm

MOVE=.008
ADV=.0035
HORIZON=60

# Frozen base trigger from Jul-Aug-Sep-Oct development.
LONG_RET240_MAX=-1.0632321402270533
LONG_EFF5_MIN=.008174651851675081
SHORT_EFF5_MIN=.008174651851675081
SHORT_EFF120_MAX=-.03765468290410372

def parse_dt(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def compact_df(mins,start,end):
    rows=[r for r in mins if fm.ms(start)<=int(r["start_ms"])<fm.ms(end)]
    d=pd.DataFrame(rows).sort_values("start_ms").reset_index(drop=True)
    d["ts_ms"]=d["start_ms"].astype("int64")
    for c in ("high","low","close","buy_notional","sell_notional","trade_count","turnover"):
        d[c]=pd.to_numeric(d[c],errors="coerce")
    d["gap"]=d.get("gap",False).fillna(False).astype(bool)
    return d

def base_features(d):
    c=d.close;b=d.buy_notional.clip(lower=0);s=d.sell_notional.clip(lower=0)
    r=c.pct_change();v=r.rolling(240,min_periods=60).std()
    x=pd.DataFrame(index=d.index)
    for h in (5,120,240):
        ret=c/c.shift(h)-1
        bb=b.rolling(h,min_periods=max(2,h//3)).sum();ss=s.rolling(h,min_periods=max(2,h//3)).sum()
        flow=(bb-ss)/(bb+ss).replace(0,np.nan)
        x[f"ret{h}"]=(ret/(v*np.sqrt(h)+1e-5)).clip(-10,10)
        x[f"eff{h}"]=(ret/(flow.abs()+.08)).clip(-.25,.25)
    x["good"]=d.gap.astype(float).rolling(15,min_periods=1).max().eq(0)
    x["long_base"]=x.good&(x.ret240<=LONG_RET240_MAX)&(x.eff5>=LONG_EFF5_MIN)
    x["short_base"]=x.good&(x.eff5>=SHORT_EFF5_MIN)&(x.eff120<=SHORT_EFF120_MAX)
    return x

def future_roll(s,h,mode):
    z=s.shift(-1).iloc[::-1].rolling(h,min_periods=h)
    return (z.max() if mode=="max" else z.min()).iloc[::-1]

def rolling_rank(s,w=360,minp=120):
    # Strictly causal reference distribution excludes current observation.
    return s.shift(1).rolling(w,min_periods=minp).apply(
        lambda a: float(np.mean(a<=s.iloc[len(a)])) if False else np.nan, raw=False)

def causal_percentile(series,w=360,minp=120):
    a=series.to_numpy(float);out=np.full(len(a),np.nan)
    for i in range(len(a)):
        lo=max(0,i-w); hist=a[lo:i];hist=hist[np.isfinite(hist)]
        if len(hist)>=minp and np.isfinite(a[i]):
            out[i]=float(np.mean(hist<=a[i]))
    return pd.Series(out,index=series.index)

def safe_col(df,name,default=np.nan):
    return pd.to_numeric(df[name],errors="coerce") if name in df else pd.Series(default,index=df.index,dtype=float)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",required=True);ap.add_argument("--end",required=True)
    ap.add_argument("--cache",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    start,end=parse_dt(a.start),parse_dt(a.end)
    fm.START=start;fm.END=end
    src=fm.Source(a.cache,(os.getenv("CRYPTOHFTDATA_API_KEY") or "").strip() or None)
    # Warm price/flow history plus complete current tape.
    fm.prefetch_hours(src,start-timedelta(hours=5),end,("trades",),workers=24)
    _,mins,_=fm.load_trades(src)
    d=compact_df(mins,start,end)
    x=base_features(d)

    # One causal microstructure snapshot per completed minute.
    records=[]
    for i,row in d.iterrows():
        records.append({"snapshot_ts_ms":int(row.ts_ms),"row_i":int(i),"features":{}})
    # Enrich uses continuous L50 replay and scalar/liquidation streams.
    enriched=fm.enrich(src,records,{},book_warmup_hours=2)
    micro=pd.DataFrame([r["features"] for r in enriched],index=[int(r["row_i"]) for r in enriched]).sort_index()
    micro=micro.reindex(d.index)

    # Build causal regime-relative ranks.
    book50=safe_col(micro,"fullmicro_book_imbalance_50")
    biddef=safe_col(micro,"fullmicro_bid_defense_ratio_60s")
    askdef=safe_col(micro,"fullmicro_ask_defense_ratio_60s")
    bidrem=safe_col(micro,"fullmicro_bid_remove_notional_60s")
    askrem=safe_col(micro,"fullmicro_ask_remove_notional_60s")
    longliq=safe_col(micro,"fullmicro_long_liq_notional_300s",0.0).fillna(0.0)
    shortliq=safe_col(micro,"fullmicro_short_liq_notional_300s",0.0).fillna(0.0)
    oi=safe_col(micro,"fullmicro_open_interest_sum_open_interest")
    oi_age=safe_col(micro,"fullmicro_open_interest_age_ms")
    oi_delta=oi.pct_change(5)
    participation=np.log1p(d.turnover.rolling(5,min_periods=3).sum())

    ranks={
      "book50":causal_percentile(book50),
      "biddef":causal_percentile(np.log1p(biddef.clip(lower=0))),
      "askdef":causal_percentile(np.log1p(askdef.clip(lower=0))),
      "bidrem":causal_percentile(np.log1p(bidrem.clip(lower=0))),
      "askrem":causal_percentile(np.log1p(askrem.clip(lower=0))),
      "longliq":causal_percentile(np.log1p(longliq.clip(lower=0))),
      "shortliq":causal_percentile(np.log1p(shortliq.clip(lower=0))),
      "participation":causal_percentile(participation),
      "oi_delta":causal_percentile(oi_delta),
    }

    book_valid=safe_col(micro,"fullmicro_book_valid",0).fillna(0).ge(1)
    oi_valid=oi_age.lt(15*60*1000)&oi.notna()

    # Pre-specified voting rule. No labels used in these decisions.
    long_votes=pd.DataFrame({
      "book_bid_heavy":ranks["book50"]>=.60,
      "bid_defense":ranks["biddef"]>=.60,
      "ask_disappears":ranks["askrem"]>=.65,
      "short_liq_squeeze":ranks["shortliq"]>=.75,
      "participation":ranks["participation"]>=.60,
      "oi_support":(ranks["oi_delta"]>=.55)&oi_valid,
    })
    short_votes=pd.DataFrame({
      "book_ask_heavy":ranks["book50"]<=.40,
      "ask_defense":ranks["askdef"]>=.60,
      "bid_disappears":ranks["bidrem"]>=.65,
      "long_liq_cascade":ranks["longliq"]>=.75,
      "participation":ranks["participation"]>=.60,
      "oi_support":(ranks["oi_delta"]>=.55)&oi_valid,
    })
    lv=long_votes.sum(axis=1);sv=short_votes.sum(axis=1)
    # If book is invalid, book-specific votes are naturally unavailable; require 3 votes overall.
    long_gate=lv>=3
    short_gate=sv>=3
    long_sig=x.long_base&long_gate
    short_sig=x.short_base&short_gate

    # Evaluation only after decisions are frozen.
    up=future_roll(d.high,HORIZON,"max")/d.close-1
    dn=1-future_roll(d.low,HORIZON,"min")/d.close
    valid=up.notna()&dn.notna()
    yl=(up>=MOVE)&(dn<=ADV)&valid
    ys=(dn>=MOVE)&(up<=ADV)&valid

    def stat(mask,y):
        m=mask&valid;n=int(m.sum());tp=int((m&y).sum());base=float(y[valid].mean())
        return {"signals":n,"true":tp,"precision":tp/n if n else 0.0,"base_rate":base,
                "lift":(tp/n)/base if n and base else 0.0}
    report={
      "version":"HYPE-FRESH-ADAPTIVE-MICRO-OOS-V1",
      "window":[start.isoformat(),end.isoformat()],
      "local_dependency":False,"threshold_retuned_on_window":False,
      "target":{"horizon_min":HORIZON,"favorable":MOVE,"max_adverse":ADV},
      "base":{"LONG":stat(x.long_base,yl),"SHORT":stat(x.short_base,ys)},
      "adaptive_micro":{"LONG":stat(long_sig,yl),"SHORT":stat(short_sig,ys)},
      "vote_counts":{
        "long_signal_minutes":int(long_sig.sum()),"short_signal_minutes":int(short_sig.sum()),
        "mean_long_votes_on_base":float(lv[x.long_base].mean()) if x.long_base.any() else None,
        "mean_short_votes_on_base":float(sv[x.short_base].mean()) if x.short_base.any() else None,
      },
      "sources":{"book_valid_minutes":int(book_valid.sum()),"oi_valid_minutes":int(oi_valid.sum()),
                 "downloaded_files":int(src.downloads),"downloaded_bytes":int(src.bytes)},
      "note":"Causal rolling-rank microstructure vote; no Local labels and no target information enters decisions."
    }
    (a.out/"FRESH_ADAPTIVE_MICRO_OOS_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
    out=pd.DataFrame({
      "ts_ms":d.ts_ms,"long_base":x.long_base,"short_base":x.short_base,
      "long_votes":lv,"short_votes":sv,"long_signal":long_sig,"short_signal":short_sig,
      "long_true":yl,"short_true":ys,"up60":up,"dn60":dn,
    })
    out.to_csv(a.out/"FRESH_ADAPTIVE_MICRO_OOS_ROWS.csv",index=False)
    print(json.dumps(report,indent=2))
if __name__=="__main__":main()
