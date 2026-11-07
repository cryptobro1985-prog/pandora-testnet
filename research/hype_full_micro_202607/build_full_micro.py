from __future__ import annotations
import argparse,bisect,gzip,json,math,os,time,hashlib
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import polars as pl
import requests

from research.hype_local_v5.labels import structural_labels
from research.hype_quant.feature_contract import POINTS,INPUT_IDS,TARGET_IDS,METADATA_IDS

API="https://api.cryptohftdata.com/v1/download"
BYBIT_RATIO="https://api.bybit.com/v5/market/account-ratio"
SYMBOL="HYPEUSDT"
EXCHANGE="bybit"
START=datetime(2026,7,12,17,tzinfo=timezone.utc)
END=datetime(2026,8,7,0,tzinfo=timezone.utc)
DELAYS=(0,30,60,180,300)
WINDOWS=(5,15,30,60,180,300)
H=3_600_000

def finite(x):return isinstance(x,(int,float,np.number)) and math.isfinite(float(x))
def num(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except Exception:return None
def ms(dt):return int(dt.timestamp()*1000)

def first_col(cols,*names):
    low={c.lower():c for c in cols}
    for n in names:
        if n in cols:return n
        if n.lower() in low:return low[n.lower()]
    for c in cols:
        cl=c.lower()
        if any(n.lower() in cl for n in names):return c
    return None

def to_ms(v):
    if v is None:return None
    if isinstance(v,datetime):return int(v.timestamp()*1000)
    try:x=float(v)
    except Exception:return None
    a=abs(x)
    if a>1e17:return int(x/1e6)
    if a>1e14:return int(x/1e3)
    if a>1e11:return int(x)
    if a>1e9:return int(x*1000)
    return int(x)

class Source:
    def __init__(self,cache:Path,api_key:str|None=None):
        self.cache=cache;cache.mkdir(parents=True,exist_ok=True)
        self.api_key=(api_key or "").strip()
        self.last=0.0;self.downloads=0;self.missing=[];self.bytes=0;self.counts=defaultdict(int)
    def path(self,dt,kind):
        return f"{EXCHANGE}/{dt:%Y-%m-%d}/{dt:%H}/{SYMBOL}_{kind}.parquet"
    def get(self,dt,kind,required=False):
        rel=self.path(dt,kind);fn=self.cache/f"{dt:%Y%m%d_%H}_{kind}.parquet"
        if fn.exists() and fn.stat().st_size>32:return fn
        if not self.api_key:
            wait=1.05-(time.time()-self.last)
            if wait>0:time.sleep(wait)
        params={"file":rel}
        if self.api_key:params["api_key"]=self.api_key
        try:
            r=requests.get(API,params=params,timeout=90,stream=True)
            self.last=time.time()
            if r.status_code in (404,400):
                self.missing.append(rel)
                if required:raise RuntimeError(f"missing required {rel}: {r.status_code} {r.text[:160]}")
                return None
            if r.status_code==429:
                time.sleep(float(r.headers.get("Retry-After","2"))+0.2)
                return self.get(dt,kind,required)
            r.raise_for_status()
            with fn.open("wb") as f:
                for b in r.iter_content(1024*1024):
                    if b:f.write(b)
            if fn.stat().st_size<32:
                fn.unlink(missing_ok=True);self.missing.append(rel)
                if required:raise RuntimeError(f"empty required {rel}")
                return None
            self.downloads+=1;self.bytes+=fn.stat().st_size;self.counts[kind]+=1
            return fn
        except Exception:
            fn.unlink(missing_ok=True)
            if required:raise
            self.missing.append(rel);return None

def cols_sample(path):
    if not path:return []
    try:return pl.read_parquet(path,n_rows=3).columns
    except Exception:return []

def read_parquet(path):
    if not path:return None
    try:return pl.read_parquet(path)
    except Exception:return None

def trade_rows(df):
    if df is None or df.height==0:return
    cs=df.columns
    tc=first_col(cs,"trade_time","event_time","timestamp","time")
    pc=first_col(cs,"price","trade_price")
    qc=first_col(cs,"quantity","qty","size")
    sc=first_col(cs,"side","direction")
    mc=first_col(cs,"is_buyer_maker","buyer_maker")
    if not tc or not pc or not qc:raise RuntimeError(f"trade schema unsupported {cs}")
    for r in df.iter_rows(named=True):
        t=to_ms(r.get(tc));p=float(r.get(pc));q=float(r.get(qc))
        if not t or p<=0 or q<=0:continue
        s=str(r.get(sc,"")).lower() if sc else ""
        if s in ("buy","b","1","true"):side=1
        elif s in ("sell","s","-1","false"):side=-1
        elif mc:side=-1 if bool(r.get(mc)) else 1
        else:side=1
        yield t,p,q,side

def newbar(start,p):
    return {"start_ms":start,"bar_end_ms":None,"open":p,"high":p,"low":p,"close":p,
            "high_ts_ms":start,"low_ts_ms":start,"buy_notional":0.0,"sell_notional":0.0,
            "buy_count":0,"sell_count":0,"trade_count":0,"quantity":0.0,"max_trade_notional":0.0}
def addbar(b,t,p,q,s):
    n=p*q
    if p>b["high"]:b["high"]=p;b["high_ts_ms"]=t
    if p<b["low"]:b["low"]=p;b["low_ts_ms"]=t
    b["close"]=p;b["quantity"]+=q;b["trade_count"]+=1;b["max_trade_notional"]=max(b["max_trade_notional"],n)
    if s>0:b["buy_notional"]+=n;b["buy_count"]+=1
    else:b["sell_notional"]+=n;b["sell_count"]+=1
def finish(b,w):
    b["bar_end_ms"]=b["start_ms"]+w;b["ts_ms"]=b["bar_end_ms"];b["turnover"]=b["buy_notional"]+b["sell_notional"]
    b["volume"]=b["quantity"];b["flow_imbalance"]=(b["buy_notional"]-b["sell_notional"])/b["turnover"] if b["turnover"] else 0.0
    b["interval_ms"]=w;b["gap"]=False;return b

def load_trades(src):
    sec5=[];mins=[];b5=b1=None;schemas={}
    dt=START-timedelta(hours=24)
    while dt<END:
        p=src.get(dt,"trades",required=False)
        if p:
            schemas.setdefault("trades",cols_sample(p))
            df=read_parquet(p)
            for t,px,q,s in trade_rows(df):
                if t<ms(START-timedelta(hours=24)) or t>=ms(END):continue
                k5=t//5000*5000;k1=t//60000*60000
                if b5 is None or b5["start_ms"]!=k5:
                    if b5:sec5.append(finish(b5,5000))
                    b5=newbar(k5,px)
                if b1 is None or b1["start_ms"]!=k1:
                    if b1:mins.append(finish(b1,60000))
                    b1=newbar(k1,px)
                addbar(b5,t,px,q,s);addbar(b1,t,px,q,s)
            p.unlink(missing_ok=True)
        dt+=timedelta(hours=1)
    if b5:sec5.append(finish(b5,5000))
    if b1:mins.append(finish(b1,60000))
    return sec5,mins,schemas

def h1(mins):
    g=defaultdict(list)
    for r in mins:g[r["start_ms"]//H*H].append(r)
    out=[]
    for k,rr in sorted(g.items()):
        rr.sort(key=lambda z:z["start_ms"])
        if len(rr)<50:continue
        out.append({"start_ms":k,"end_ms":k+H,"open":rr[0]["open"],"high":max(x["high"] for x in rr),
                    "low":min(x["low"] for x in rr),"close":rr[-1]["close"]})
    return out

def matches(c,labels):
    for x in labels:
        if x["side"]!=c["side"]:continue
        if int(x["extreme_interval_start_ms"])<=c["extreme_ts_ms"]<=int(x["extreme_interval_end_ms"]):
            if math.isclose(float(x["extreme_price"]),float(c["extreme_price"]),rel_tol=1e-10,abs_tol=1e-8):return x["label_id"]
    return None

def candidates(mins,labels):
    out=[];lows=[];highs=[]
    for i,r in enumerate(mins):
        if i>=360:
            recent=mins[i-360:i+1]
            if all(b["start_ms"]-a["start_ms"]==60000 for a,b in zip(recent,recent[1:])):
                lo=min(lows[-360:]);hi=max(highs[-360:])
                if r["low"]<lo:
                    c={"side":"LOW","extreme_price":r["low"],"extreme_ts_ms":r["low_ts_ms"],"candidate_id":f"L-{r['low_ts_ms']}"}
                    c["strict_label_id"]=matches(c,labels);out.append(c)
                if r["high"]>hi:
                    c={"side":"HIGH","extreme_price":r["high"],"extreme_ts_ms":r["high_ts_ms"],"candidate_id":f"H-{r['high_ts_ms']}"}
                    c["strict_label_id"]=matches(c,labels);out.append(c)
        lows.append(r["low"]);highs.append(r["high"])
    return [c for c in out if c["extreme_ts_ms"]>=ms(START)]

def secwin(sec5,starts,end,seconds):
    return sec5[bisect.bisect_left(starts,end-seconds*1000):bisect.bisect_right(starts,end-1)]
def agg(rows,rev):
    if not rows:return {}
    buy=sum(x["buy_notional"] for x in rows);sell=sum(x["sell_notional"] for x in rows);tot=buy+sell
    ret=rows[-1]["close"]/rows[0]["open"]-1 if rows[0]["open"] else 0.0
    imb=(buy-sell)/tot if tot else 0.0
    return {"imbalance":imb,"rev_flow":imb*rev,"ret":ret,"rev_ret":ret*rev,
            "buy":buy,"sell":sell,"total":tot,"trade_count":sum(x["trade_count"] for x in rows),
            "rev_eff":max(ret*rev,0)/(buy if rev>0 else sell+1e-12)*1e6 if (buy if rev>0 else sell)>0 else 0.0}

def base_features(c,t,sec5,mins):
    starts=[x["start_ms"] for x in sec5];mstarts=[x["start_ms"] for x in mins];rev=1 if c["side"]=="LOW" else -1
    rows5=secwin(sec5,starts,t,5);cur=rows5[-1]["close"] if rows5 else c["extreme_price"]
    f={"age_s":(t-c["extreme_ts_ms"])/1000,"retrace_bps":(cur/c["extreme_price"]-1)*rev*10000}
    for w in WINDOWS:
        a=agg(secwin(sec5,starts,t,w),rev)
        for k,v in a.items():f[f"{k}_{w}s_log" if k in ("buy","sell","total") else f"{k}_{w}s"]=math.log1p(v) if k in ("buy","sell","total") else v
    j=bisect.bisect_right(mstarts,t)-1
    if j>=0:
        for n,name in ((60,"60m"),(360,"6h"),(1440,"24h")):
            rr=mins[max(0,j-n+1):j+1]
            if rr:
                lo=min(x["low"] for x in rr);hi=max(x["high"] for x in rr);span=max(hi-lo,1e-12)
                f[f"position_{name}"]=(cur-lo)/span;f[f"distance_low_{name}_bps"]=(cur/lo-1)*10000
                f[f"distance_high_{name}_bps"]=(hi/cur-1)*10000
    return {k:float(v) for k,v in f.items() if finite(v)}

def target_records(cands,sec5,mins):
    out=[]
    for c in cands:
        for d in DELAYS:
            t=c["extreme_ts_ms"]+d*1000
            out.append({"symbol":"HYPE","candidate_id":c["candidate_id"],"side":c["side"],"candidate_ts_ms":c["extreme_ts_ms"],
                        "snapshot_ts_ms":t,"delay_s":d,"extreme_price":c["extreme_price"],
                        "strict_true":bool(c["strict_label_id"]),"strict_label_id":c["strict_label_id"],
                        "features":base_features(c,t,sec5,mins)})
    return out

def scalar_snapshots(df,targets,carry=None):
    """Causal forward-fill for pre-Sep-2026 Bybit change-only scalar files."""
    state=dict(carry or {});snaps={};rows=[];cs=[]
    if df is not None and df.height:
        cs=df.columns
        tc=first_col(cs,"timestamp","event_time","received_time","time")
        if tc:
            for r in df.iter_rows(named=True):
                tt=to_ms(r.get(tc))
                if tt is not None:rows.append((tt,r))
            rows.sort(key=lambda z:z[0])
    idx=0
    def apply(tt,r):
        state["_last_ts_ms"]=tt
        for k,v in r.items():
            if k in ("timestamp","event_time","received_time","time"):continue
            z=num(v)
            if z is not None:state[k]=z
    for t in sorted(targets):
        while idx<len(rows) and rows[idx][0]<=t:
            apply(*rows[idx]);idx+=1
        snap={k:v for k,v in state.items() if k!="_last_ts_ms"}
        snap["_ts_ms"]=state.get("_last_ts_ms")
        snaps[t]=snap
    while idx<len(rows):
        apply(*rows[idx]);idx+=1
    return snaps,state,cs

def liquidation_events(df):
    if df is None or df.height==0:return [],[]
    cs=df.columns
    tc=first_col(cs,"trade_time","event_time","timestamp","received_time","time")
    pc=first_col(cs,"price","average_price");qc=first_col(cs,"quantity","qty","size");sc=first_col(cs,"side")
    if not tc:return [],cs
    out=[]
    for r in df.iter_rows(named=True):
        tt=to_ms(r.get(tc));p=num(r.get(pc)) if pc else None;q=num(r.get(qc)) if qc else None
        if tt is None or p is None or q is None:continue
        s=str(r.get(sc,"")).strip().lower() if sc else ""
        # CryptoHFTData publishes the liquidation ORDER side:
        # SELL = a long position was liquidated; BUY = a short was liquidated.
        position="LONG" if s=="sell" else "SHORT" if s=="buy" else "UNKNOWN"
        out.append((tt,p*q,position))
    out.sort(key=lambda z:z[0])
    return out,cs

def liq_features(events,t):
    out={}
    for sec in (5,15,60,180,300):
        q=[z for z in events if t-sec*1000<=z[0]<=t]
        lng=sum(n for _,n,pos in q if pos=="LONG");sht=sum(n for _,n,pos in q if pos=="SHORT")
        out[f"fullmicro_liq_count_{sec}s"]=float(len(q))
        out[f"fullmicro_long_liq_notional_{sec}s"]=lng
        out[f"fullmicro_short_liq_notional_{sec}s"]=sht
        den=lng+sht
        if den:out[f"fullmicro_liq_imbalance_{sec}s"]=(sht-lng)/den
    return out

def book_replay(path,target_times,carry=None):
    state=carry or {"bids":{},"asks":{},"last_u":None,"valid":False,"gap_count":0}
    bids=state["bids"];asks=state["asks"];snaps={}
    df=read_parquet(path)
    if df is None or df.height==0:
        state["valid"]=False
        return {t:book_features(state) for t in target_times},state,[]
    cs=df.columns
    tc=first_col(cs,"received_time","event_time","transaction_time","timestamp","time")
    pc=first_col(cs,"price");qc=first_col(cs,"quantity","qty","size");sc=first_col(cs,"side")
    typ=first_col(cs,"event_type","update_type","type","action")
    uc=first_col(cs,"final_update_id","update_id")
    msgc=uc or first_col(cs,"event_time","received_time","timestamp")
    if not all((tc,pc,qc,sc)):raise RuntimeError(f"orderbook schema unsupported {cs}")
    targets=sorted(target_times);ti=0;lastmsg=object()
    for r in df.iter_rows(named=True):
        tt=to_ms(r.get(tc))
        if tt is None:continue
        while ti<len(targets) and targets[ti]<tt:
            snaps[targets[ti]]=book_features(state);ti+=1
        msg=r.get(msgc) if msgc else tt
        if msg!=lastmsg:
            et=str(r.get(typ,"")).lower() if typ else ""
            u=num(r.get(uc)) if uc else None
            u=int(u) if u is not None else None
            if "snapshot" in et:
                bids.clear();asks.clear();state["valid"]=True
            else:
                prev=state.get("last_u")
                if prev is not None and u is not None and u!=int(prev)+1:
                    state["valid"]=False;state["gap_count"]=int(state.get("gap_count",0))+1
            if u is not None:state["last_u"]=u
            lastmsg=msg
        p=num(r.get(pc));q=num(r.get(qc))
        if p is None or q is None:continue
        side=str(r.get(sc,"")).lower();book=bids if side.startswith("b") or side=="buy" else asks
        if q<=0:book.pop(p,None)
        else:book[p]=q
    while ti<len(targets):
        snaps[targets[ti]]=book_features(state);ti+=1
    return snaps,state,cs

def book_features(state):
    if not state or not state.get("valid"):
        return {"fullmicro_book_valid":0.0,"fullmicro_book_gap_count":float((state or {}).get("gap_count",0))}
    b=sorted(state["bids"].items(),reverse=True)[:50];a=sorted(state["asks"].items())[:50]
    if not b or not a:return {"fullmicro_book_valid":0.0,"fullmicro_book_gap_count":float(state.get("gap_count",0))}
    bb=b[0][0];aa=a[0][0];mid=(bb+aa)/2
    out={"fullmicro_book_valid":1.0,"fullmicro_book_gap_count":float(state.get("gap_count",0)),
         "fullmicro_spread_bps":(aa-bb)/mid*10000}
    for n in (5,10,25,50):
        bn=sum(p*q for p,q in b[:n]);an=sum(p*q for p,q in a[:n]);den=bn+an
        if den:out[f"fullmicro_book_imbalance_{n}"]=(bn-an)/den
    for i,(p,q) in enumerate(b,1):
        out[f"fullmicro_bid_{i:02d}_dist_bps"]=(p/mid-1)*10000
        out[f"fullmicro_bid_{i:02d}_log_qty"]=math.log1p(max(q,0))
    for i,(p,q) in enumerate(a,1):
        out[f"fullmicro_ask_{i:02d}_dist_bps"]=(p/mid-1)*10000
        out[f"fullmicro_ask_{i:02d}_log_qty"]=math.log1p(max(q,0))
    return out

def enrich(src,records,schemas):
    byhour=defaultdict(list)
    for r in records:
        dt=datetime.fromtimestamp(r["snapshot_ts_ms"]/1000,tz=timezone.utc).replace(minute=0,second=0,microsecond=0)
        byhour[dt].append(r)
    book_state=None
    scalar_state={k:{} for k in ("open_interest","mark_price","ticker")}
    liq_recent=[]
    dt=START-timedelta(hours=24)
    while dt<END:
        targets=sorted(r["snapshot_ts_ms"] for r in byhour.get(dt,[]))

        bp=src.get(dt,"orderbook")
        if bp:
            bsn,book_state,cs=book_replay(bp,targets,book_state)
            schemas.setdefault("orderbook",cs);bp.unlink(missing_ok=True)
        else:
            if book_state is None:book_state={"bids":{},"asks":{},"last_u":None,"valid":False,"gap_count":0}
            book_state["valid"]=False;book_state["gap_count"]=int(book_state.get("gap_count",0))+1
            bsn={t:book_features(book_state) for t in targets}

        lp=src.get(dt,"liquidations")
        if lp:
            ldf=read_parquet(lp);ev,cs=liquidation_events(ldf);liq_recent.extend(ev)
            schemas.setdefault("liquidations",cs);lp.unlink(missing_ok=True)
        # Keep only events that could affect a 300s window in this/next hour.
        floor=ms(dt)-300_000
        liq_recent=[z for z in liq_recent if z[0]>=floor]

        scalar_snaps={}
        for kind in ("open_interest","mark_price","ticker"):
            p=src.get(dt,kind)
            df=read_parquet(p) if p else None
            snaps,scalar_state[kind],cs=scalar_snapshots(df,targets,scalar_state[kind])
            scalar_snaps[kind]=snaps
            if cs:schemas.setdefault(kind,cs)
            if p:p.unlink(missing_ok=True)

        for r in sorted(byhour.get(dt,[]),key=lambda z:z["snapshot_ts_ms"]):
            t=r["snapshot_ts_ms"];f=r["features"]
            f.update(bsn.get(t,{"fullmicro_book_valid":0.0}))
            f.update(liq_features(liq_recent,t))
            for kind in ("open_interest","mark_price","ticker"):
                z=scalar_snaps[kind].get(t,{})
                stamp=z.get("_ts_ms")
                if stamp is not None:f[f"fullmicro_{kind}_age_ms"]=float(max(0,t-stamp))
                for k,v in z.items():
                    if k!="_ts_ms" and finite(v):f[f"fullmicro_{kind}_{k}"]=float(v)

        if targets or dt.hour==0:
            print(json.dumps({"hour":dt.isoformat(),"records":len(targets),"downloads":src.downloads,
                              "bytes":src.bytes,"book_valid":bool(book_state and book_state.get("valid")),
                              "book_gaps":int((book_state or {}).get("gap_count",0))}),flush=True)
        dt+=timedelta(hours=1)
    return records

def fetch_account_ratio():
    rows=[]
    day=START-timedelta(hours=1)
    while day<END:
        nxt=min(day+timedelta(days=1),END)
        cursor=None
        while True:
            params={"category":"linear","symbol":SYMBOL,"period":"5min","limit":500,
                    "startTime":ms(day),"endTime":ms(nxt)}
            if cursor:params["cursor"]=cursor
            try:
                r=requests.get(BYBIT_RATIO,params=params,timeout=30);r.raise_for_status();obj=r.json()
                if obj.get("retCode")!=0:break
                part=(obj.get("result") or {}).get("list") or []
                for z in part:
                    t=to_ms(z.get("timestamp"));buy=num(z.get("buyRatio"));sell=num(z.get("sellRatio"))
                    if t is None or buy is None or sell is None:continue
                    rows.append({"ts_ms":t,"buy_ratio":buy,"sell_ratio":sell,
                                 "long_short_ratio":buy/sell if sell else None})
                cursor=(obj.get("result") or {}).get("nextPageCursor") or None
                if not cursor:break
            except Exception:break
        day=nxt
    uniq={int(z["ts_ms"]):z for z in rows}
    return [uniq[k] for k in sorted(uniq)]

def attach_account_ratio(records,ratio_rows):
    if not ratio_rows:return records
    ts=[z["ts_ms"] for z in ratio_rows]
    for r in records:
        t=int(r["snapshot_ts_ms"]);j=bisect.bisect_right(ts,t)-1
        if j<0:continue
        z=ratio_rows[j];age=t-z["ts_ms"]
        if age>30*60*1000:continue
        f=r["features"]
        f["fullmicro_account_buy_ratio"]=float(z["buy_ratio"])
        f["fullmicro_account_sell_ratio"]=float(z["sell_ratio"])
        if finite(z.get("long_short_ratio")):f["fullmicro_account_long_short_ratio"]=float(z["long_short_ratio"])
        f["fullmicro_account_ratio_age_ms"]=float(max(0,age))
    return records

def write_jsonl_gz(path,rows):
    with gzip.open(path,"wt",encoding="utf-8",compresslevel=9) as f:
        for r in rows:f.write(json.dumps(r,separators=(",",":"),allow_nan=False)+"\n")
def write_json_gz(path,obj):
    with gzip.open(path,"wt",encoding="utf-8",compresslevel=9) as f:json.dump(obj,f,separators=(",",":"),allow_nan=False)
def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output",type=Path,required=True);ap.add_argument("--cache",type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    src=Source(args.cache,os.getenv("CRYPTOHFTDATA_API_KEY"))
    sec5,mins,schemas=load_trades(src)
    strict,strict_exc=structural_labels(mins,lookback=6,lookahead=2)
    cands=candidates(mins,strict);records=target_records(cands,sec5,mins)
    ratio_rows=fetch_account_ratio()
    records=attach_account_ratio(records,ratio_rows)
    records=enrich(src,records,schemas)
    observed=set(range(1,44))|{77,78,79,80,116}
    if src.counts.get("orderbook",0) and any(r["features"].get("fullmicro_book_valid")==1.0 for r in records):
        observed|=set(range(44,58))
    if src.counts.get("open_interest",0):
        observed|={58,59,60,61,115}
    if src.counts.get("mark_price",0):
        observed|={2,3,62,114}
    if src.counts.get("ticker",0):
        observed|={63,64}
    if src.counts.get("liquidations",0):
        observed|=set(range(65,77))
    if ratio_rows:
        observed|={113}
    availability={"points_total":116,"causal_input_points":len(INPUT_IDS),"target_eval_points":len(TARGET_IDS),"metadata_points":len(METADATA_IDS),
                  "historically_observed_or_derived_input_ids":sorted(observed&set(INPUT_IDS)),
                  "missing_input_ids":sorted(set(INPUT_IDS)-observed),
                  "source_file_counts":dict(src.counts),
                  "note":"targets 83-110 are labels/evaluation only and never enter X; unavailable causal inputs are not fabricated"}
    write_jsonl_gz(args.output/"candidate_snapshots_full_micro.jsonl.gz",records)
    write_jsonl_gz(args.output/"compact_1m.jsonl.gz",[r for r in mins if r["start_ms"]>=ms(START)])
    write_json_gz(args.output/"labels.json.gz",{"strict":strict,"strict_exclusions":strict_exc})
    (args.output/"feature_availability.json").write_text(json.dumps(availability,indent=2)+"\n")
    manifest={"symbol":SYMBOL,"period":[START.isoformat(),END.isoformat()],"strict_labels":len(strict),
              "strict_low":sum(x["side"]=="LOW" for x in strict),"strict_high":sum(x["side"]=="HIGH" for x in strict),
              "candidates":len(cands),"snapshots":len(records),"source":"CryptoHFTData Bybit hourly Parquet/Zstd",
              "downloaded_files":src.downloads,"downloaded_bytes":src.bytes,"source_file_counts":dict(src.counts),"account_ratio_rows":len(ratio_rows),"missing_files":src.missing,
              "schemas":schemas,"raw_files_retained":False,"compression":"gzip-9 compact outputs",
              "future_leakage_guard":"strict labels and target/eval points never enter causal features"}
    (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n")
    am={}
    for p in args.output.iterdir():
        if p.is_file():am[p.name]={"bytes":p.stat().st_size,"sha256":sha(p)}
    (args.output/"artifact_manifest.json").write_text(json.dumps(am,indent=2)+"\n")
    print("FULL_MICRO_DATASET="+json.dumps({k:manifest[k] for k in ("strict_labels","strict_low","strict_high","candidates","snapshots","downloaded_files","downloaded_bytes")},separators=(",",":")))
if __name__=="__main__":main()
