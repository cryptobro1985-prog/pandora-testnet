from __future__ import annotations
import json
from pathlib import Path

AGG_HEADER=["ts","open","high","low","close","buy_notional","sell_notional","buy_qty","sell_qty","buy_count","sell_count","max_trade_notional","trade_count"]

def require_pandas():
    import numpy as np, pandas as pd
    return np,pd

def build_features(df,np,pd):
    df=df.sort_values("ts").drop_duplicates("ts").copy()
    for c in AGG_HEADER[1:]: df[c]=pd.to_numeric(df[c],errors="coerce")
    df["ts"]=pd.to_numeric(df["ts"],errors="coerce").astype("int64")
    df=df.dropna(subset=["open","high","low","close"]).reset_index(drop=True)
    bn=df["buy_notional"].clip(lower=0); sn=df["sell_notional"].clip(lower=0); total=bn+sn
    df["imb1"]=((bn-sn)/total.replace(0,np.nan)).fillna(0.0)
    for w in (3,5):
        b=bn.rolling(w,min_periods=1).sum(); s=sn.rolling(w,min_periods=1).sum()
        df[f"imb{w}"]=((b-s)/(b+s).replace(0,np.nan)).fillna(0.0)
    df["ret1"]=df["close"].pct_change(1).fillna(0.0)
    df["ret3"]=df["close"].pct_change(3).fillna(0.0)
    df["ret5"]=df["close"].pct_change(5).fillna(0.0)
    med=total.rolling(60,min_periods=10).median().replace(0,np.nan)
    df["activity"]=(total/med).replace([np.inf,-np.inf],np.nan).fillna(0.0).clip(0,20)
    df["range_pct"]=((df["high"]-df["low"])/df["close"].replace(0,np.nan)).fillna(0.0)
    df["atr60"]=df["range_pct"].rolling(60,min_periods=10).mean().fillna(df["range_pct"].expanding().mean()).fillna(0.0)
    return df

def h1_table(df,pd):
    x=df.copy(); idx=pd.to_datetime(x["ts"],unit="s",utc=True); x=x.set_index(idx)
    h=x.resample("1h",label="left",closed="left").agg({"open":"first","high":"max","low":"min","close":"last","buy_notional":"sum","sell_notional":"sum"}).dropna(subset=["open","high","low","close"])
    h["ts"]=(h.index.astype("int64")//10**9).astype("int64")
    h["range_pct"]=(h["high"]-h["low"])/h["close"]
    h["atr12"]=h["range_pct"].rolling(12,min_periods=4).median().fillna(h["range_pct"].expanding().median())
    return h.reset_index(drop=True)

def compute_local_state(minute_df,h1,lookback,min_retrace,atr_mult,np):
    conf_ts=[]; conf_side=[]; conf_id=[]; low_cand=None; high_cand=None; anchor_seq=0
    highs=h1["high"].to_numpy(float); lows=h1["low"].to_numpy(float); closes=h1["close"].to_numpy(float)
    tss=h1["ts"].to_numpy(int); atr=h1["atr12"].to_numpy(float)
    for i in range(len(h1)):
        if i>=lookback:
            if lows[i]<=np.nanmin(lows[i-lookback:i]):
                if low_cand is None or lows[i]<=low_cand[0]: low_cand=(lows[i],i)
            if highs[i]>=np.nanmax(highs[i-lookback:i]):
                if high_cand is None or highs[i]>=high_cand[0]: high_cand=(highs[i],i)
        low_ok=high_ok=False; low_strength=high_strength=-1.0
        if low_cand and i>low_cand[1]:
            if lows[i]<=low_cand[0]: low_cand=(lows[i],i)
            else:
                thr=max(min_retrace,atr_mult*max(0.0,atr[low_cand[1]])); retr=closes[i]/low_cand[0]-1.0
                low_ok=retr>=thr; low_strength=retr/max(thr,1e-9)
        if high_cand and i>high_cand[1]:
            if highs[i]>=high_cand[0]: high_cand=(highs[i],i)
            else:
                thr=max(min_retrace,atr_mult*max(0.0,atr[high_cand[1]])); retr=1.0-closes[i]/high_cand[0]
                high_ok=retr>=thr; high_strength=retr/max(thr,1e-9)
        side=1 if low_ok and (not high_ok or low_strength>high_strength) else -1 if high_ok else 0
        if side:
            anchor_seq+=1; conf_ts.append(int(tss[i]+3600)); conf_side.append(side); conf_id.append(anchor_seq)
            low_cand=high_cand=None
    mt=minute_df["ts"].to_numpy(int); sides=np.zeros(len(mt),dtype=np.int8); anchors=np.zeros(len(mt),dtype=np.int32)
    j=0; cur_s=0; cur_a=0
    for k,t in enumerate(mt):
        while j<len(conf_ts) and conf_ts[j]<=t:
            cur_s=conf_side[j]; cur_a=conf_id[j]; j+=1
        sides[k]=cur_s; anchors[k]=cur_a
    return sides,anchors

def build_universe(input_dir:Path):
    np,pd=require_pandas(); data={}; coverage={}
    for p in sorted(input_dir.rglob("*_minutes.csv.gz")):
        sym=p.name.split("_minutes.csv.gz")[0]
        try:
            df=pd.read_csv(p,compression="gzip")
            if len(df)>=1440*10: data[sym]=build_features(df,np,pd)
        except Exception: pass
    for p in sorted(input_dir.rglob("*_coverage.json")):
        try:
            j=json.loads(p.read_text()); coverage[j["symbol"]]=j
        except Exception: pass
    return np,pd,data,coverage

def local_cache_for(data,np,pd,keys):
    h1s={s:h1_table(df,pd) for s,df in data.items()}; out={}
    for key in keys:
        lookback,minr,atrm=key
        out[key]={s:compute_local_state(df,h1s[s],lookback,minr,atrm,np) for s,df in data.items()}
    return out
