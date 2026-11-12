"""Bybit public trade archive -> 1-second aggressor bars (causal: bar t covers trades in [t-1s, t)). Research only."""
import sys,numpy as np,pandas as pd
from pathlib import Path
from datetime import datetime,timezone
OUT=Path("/workspace/data/s1")
def run(day):
    out=OUT/f"{day}.npz"
    if out.exists():return "skip "+day
    df=pd.read_csv(f"/workspace/data/trades/HYPEUSDT{day}.csv.gz",usecols=["timestamp","side","size","price","foreignNotional"])
    df=df.sort_values("timestamp",kind="stable")
    d0=int(datetime.strptime(day,"%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    sec=np.floor(df["timestamp"].values).astype(np.int64)-d0
    sec=np.clip(sec,0,86399)
    px=df["price"].values.astype(np.float64);notional=df["foreignNotional"].values.astype(np.float64)
    buy=(df["side"].values=="Buy")
    n=86400
    cnt=np.bincount(sec,minlength=n)
    bn=np.bincount(sec,weights=notional*buy,minlength=n);sn=np.bincount(sec,weights=notional*(~buy),minlength=n)
    bc=np.bincount(sec,weights=buy.astype(float),minlength=n);sc=cnt-bc
    hi=np.full(n,-np.inf);lo=np.full(n,np.inf)
    np.maximum.at(hi,sec,px);np.minimum.at(lo,sec,px)
    # close = last trade in second, open=first
    idx_last=np.zeros(n,dtype=np.int64)-1;idx_first=np.zeros(n,dtype=np.int64)-1
    order=np.arange(len(sec))
    idx_last[sec]=order  # later overwrite wins (sorted)
    rev=order[::-1];idx_first[sec[::-1]]=rev
    has=cnt>0
    close=np.where(has,px[np.maximum(idx_last,0)],np.nan);op=np.where(has,px[np.maximum(idx_first,0)],np.nan)
    mx=np.zeros(n);np.maximum.at(mx,sec,notional)
    # forward-fill price for empty seconds (no trade => price unchanged), flag empties
    s=pd.Series(close).ffill()
    hi=np.where(has,hi,np.nan);lo=np.where(has,lo,np.nan)
    np.savez_compressed(out,t0=d0,open=op.astype(np.float64),high=hi,low=lo,close=close,
        buy=bn.astype(np.float32),sell=sn.astype(np.float32),bc=bc.astype(np.int32),sc=sc.astype(np.int32),maxn=mx.astype(np.float32),
        ntr=cnt.astype(np.int32))
    return f"ok {day} trades={len(df)}"
if __name__=="__main__":
    for d in sys.argv[1:]:
        try:print(run(d),flush=True)
        except Exception as e:print("ERR",d,repr(e),flush=True)
