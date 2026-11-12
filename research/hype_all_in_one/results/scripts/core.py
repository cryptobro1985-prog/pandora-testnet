"""HYPE early real-H1-Local research core (research/paper only, real orders OFF).

Causality convention: global second index g; 1s bar g aggregates trades in
[T0+g, T0+g+1) and becomes known at time T0+g+1. A decision at boundary time t
(seconds since T0) may only read bars g <= t-1, book samples at <= t, OI/ratio
records with ts+300s <= t, mark/index 1m bars with close-time <= t.
Strict H1 L6/K2 labels (repo research/hype_local_v5/labels.py) are scoring-only.
"""
from __future__ import annotations
import gzip,json,math,sys,bisect
from pathlib import Path
from datetime import datetime,timezone
import numpy as np

REPO=Path("/workspace/pandora-testnet")
sys.path.insert(0,str(REPO))
from research.hype_local_v5.labels import structural_labels  # offline teacher only

DATA=Path("/workspace/data")
T0=int(datetime(2026,4,24,tzinfo=timezone.utc).timestamp())
EPS=1e-12

def day_list(a="2026-04-24",b="2026-11-11"):
    from datetime import date,timedelta
    d=date.fromisoformat(a);e=date.fromisoformat(b);out=[]
    while d<=e:out.append(d.isoformat());d+=timedelta(days=1)
    return out

class Tape:
    """Continuous 1s tape + derived M1 + auxiliary causal series."""
    def __init__(self,days=None):
        days=days or day_list()
        parts={k:[] for k in ("high","low","close","buy","sell","bc","sc","maxn","ntr")}
        for d in days:
            z=np.load(DATA/"s1"/f"{d}.npz")
            assert int(z["t0"])==T0+len(parts["close"])*86400, d
            for k in parts:parts[k].append(z[k])
        for k in parts:setattr(self,k,np.concatenate(parts[k]))
        self.N=len(self.close)
        has=~np.isnan(self.close)
        # forward-fill close for no-trade seconds (price unchanged); high/low fall back to close
        idx=np.where(has,np.arange(self.N),0);np.maximum.accumulate(idx,out=idx)
        self.closef=self.close[idx]
        self.high=np.where(np.isnan(self.high),self.closef,self.high)
        self.low=np.where(np.isnan(self.low),self.closef,self.low)
        self.has_trade=has
        self.cbuy=np.concatenate([[0.0],np.cumsum(self.buy.astype(np.float64))])
        self.csell=np.concatenate([[0.0],np.cumsum(self.sell.astype(np.float64))])
        self.ccnt=np.concatenate([[0],np.cumsum(self.ntr.astype(np.int64))])
        self.cnotrade=np.concatenate([[0],np.cumsum((~has).astype(np.int64))])
        # M1
        nm=self.N//60
        # V2 alignment fix: M1 high/low from ACTUAL trades only (v1 let forward-filled previous close of
        # no-trade seconds enter the minute's high/low -> 1-tick differences vs project compact M1).
        hm=np.where(has,self.high,-np.inf);lm=np.where(has,self.low,np.inf)
        h=hm[:nm*60].reshape(nm,60);l=lm[:nm*60].reshape(nm,60);c=self.closef[:nm*60].reshape(nm,60)
        empty=~has[:nm*60].reshape(nm,60).any(1)
        h=np.where(empty[:,None],c,h);l=np.where(empty[:,None],c,l)
        self.m_high=h.max(1);self.m_low=l.min(1);self.m_close=c[:,-1];self.m_open=c[:,0]
        o=self.closef[np.maximum(np.arange(nm)*60-1,0)];self.m_open=np.where(np.arange(nm)>0,o,c[:,0])
        self.m_low_sec=np.argmin(l,1)+np.arange(nm)*60
        self.m_high_sec=np.argmax(h,1)+np.arange(nm)*60
        self.nm=nm
        # sparse tables for range min/max over M1 (prefix via simple approach: precompute rolling 360/180/60/1440)
        self._load_aux()

    def m1_rows(self,m0=0,m1=None):
        m1=self.nm if m1 is None else m1
        out=[]
        for i in range(m0,m1):
            s=(T0+i*60)*1000
            out.append({"start_ms":s,"bar_end_ms":s+60000,"ts_ms":s+60000,"open":float(self.m_open[i]),
                        "high":float(self.m_high[i]),"low":float(self.m_low[i]),"close":float(self.m_close[i]),
                        "gap":False,"low_ts_ms":(T0+int(self.m_low_sec[i]))*1000,"high_ts_ms":(T0+int(self.m_high_sec[i]))*1000})
        return out

    def _load_aux(self):
        def lj(n):
            p=DATA/"rest"/f"{n}.json.gz"
            if not p.exists():return []
            with gzip.open(p,"rt") as f:return json.load(f)
        oi=lj("oi");self.oi_t=np.array([x["ts"]//1000+300 for x in oi],dtype=np.int64)-T0  # available 5min after stamp
        self.oi_v=np.array([x["oi"] for x in oi]);
        r=lj("ratio");self.ra_t=np.array([x["ts"]//1000+300 for x in r],dtype=np.int64)-T0;self.ra_v=np.array([x["buy_ratio"] for x in r])
        f=lj("funding");self.fu_t=np.array([x["ts"]//1000 for x in f],dtype=np.int64)-T0;self.fu_v=np.array([x["rate"] for x in f])
        mk=lj("mark");self.mk_t=np.array([x["ts"]//1000+60 for x in mk],dtype=np.int64)-T0;self.mk_c=np.array([x["c"] for x in mk])
        ix=lj("index");self.ix_t=np.array([x["ts"]//1000+60 for x in ix],dtype=np.int64)-T0;self.ix_c=np.array([x["c"] for x in ix])
        # book: 1s grid sample at time T0+g (state includes updates with ts<=that time)
        self.book=None
        bp=DATA/"ob_feat"
        if bp.exists():
            cols=None;arrs=[];
            days=day_list()[:self.N//86400]
            for i,d in enumerate(days):
                p=bp/f"{d}.npz"
                if p.exists():
                    z=np.load(p);a=z["a"];cols=list(z["cols"])
                    # grid t = d0+1000.. d0+86400000 -> index g = (t/1000 - T0)
                    blk=np.full((86400,a.shape[1]),np.nan);g=(a[:,0]/1000).astype(np.int64)-T0-i*86400
                    ok=(g>=0)&(g<86400);blk[g[ok]]=a[ok]
                    arrs.append(blk)
                else:arrs.append(np.full((86400,16),np.nan))
            if cols:
                B=np.concatenate(arrs)
                self.book_cols=cols;self.book=B   # row g == sample at time T0+g+1? see below
                # a[:,0]=grid time ms=T0+g' ; we stored at index g' -> state at time T0+g'

    # ---------- causal accessors (t = decision boundary in seconds since T0) ----------
    def flow(self,a,b):
        """buy,sell notional over bars [a,b) clipped."""
        a=max(0,a);b=max(a,min(self.N,b))
        return self.cbuy[b]-self.cbuy[a],self.csell[b]-self.csell[a],int(self.ccnt[b]-self.ccnt[a])
    def step_val(self,ts,vs,t):
        j=np.searchsorted(ts,t,side="right")-1
        return (float(vs[j]),int(t-ts[j])) if j>=0 else (np.nan,None)
    def book_at(self,t):
        if self.book is None:return None
        g=int(t)
        if g<0 or g>=self.N:return None
        r=self.book[g]
        if np.isnan(r[1]) or np.isnan(r[5]):return None
        return r

def strict_labels_for(tape,m0,m1):
    rows=tape.m1_rows(m0,m1)
    labels,excl=structural_labels(rows,lookback=6,lookahead=2)
    return labels,excl
