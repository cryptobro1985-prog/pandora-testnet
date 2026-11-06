from __future__ import annotations
import math
from collections import defaultdict

def finite(v):
    return isinstance(v,(int,float)) and math.isfinite(v)

def ema(vals,n):
    a=2.0/(n+1.0);out=[];x=None
    for v in vals:
        x=v if x is None else a*v+(1-a)*x
        out.append(x)
    return out

def rma(vals,n):
    out=[];x=None
    for v in vals:
        x=v if x is None else ((n-1)*x+v)/n
        out.append(x)
    return out

def resample(rows,minutes):
    if minutes==1:return list(rows)
    groups=defaultdict(list)
    span=minutes*60_000
    for r in rows:
        groups[(int(r["ts_ms"])//span)*span].append(r)
    out=[]
    for ts,rs in sorted(groups.items()):
        rs=sorted(rs,key=lambda z:z["ts_ms"])
        out.append({"ts_ms":ts,"open":float(rs[0]["open"]),"high":max(float(x["high"]) for x in rs),
                    "low":min(float(x["low"]) for x in rs),"close":float(rs[-1]["close"]),
                    "volume":sum(float(x.get("volume",0) or 0) for x in rs),
                    "turnover":sum(float(x.get("turnover",0) or 0) for x in rs),
                    "count":len(rs)})
    return out

def indicator_series(rows):
    if not rows:return []
    close=[float(r["close"]) for r in rows]
    high=[float(r["high"]) for r in rows]
    low=[float(r["low"]) for r in rows]
    e12,e26=ema(close,12),ema(close,26)
    macd=[a-b for a,b in zip(e12,e26)]
    sig=ema(macd,9)
    hist=[a-b for a,b in zip(macd,sig)]
    e9,e21,e50=ema(close,9),ema(close,21),ema(close,50)
    tr=[];plus_dm=[];minus_dm=[]
    prev_c=prev_h=prev_l=None
    for h,l,c in zip(high,low,close):
        if prev_c is None:
            tr.append(h-l);plus_dm.append(0.0);minus_dm.append(0.0)
        else:
            tr.append(max(h-l,abs(h-prev_c),abs(l-prev_c)))
            up=h-prev_h;dn=prev_l-l
            plus_dm.append(up if up>dn and up>0 else 0.0)
            minus_dm.append(dn if dn>up and dn>0 else 0.0)
        prev_c,prev_h,prev_l=c,h,l
    atr=rma(tr,14);pdm=rma(plus_dm,14);mdm=rma(minus_dm,14)
    pdi=[100*x/a if a>0 else 0.0 for x,a in zip(pdm,atr)]
    mdi=[100*x/a if a>0 else 0.0 for x,a in zip(mdm,atr)]
    dx=[100*abs(p-m)/(p+m) if p+m>0 else 0.0 for p,m in zip(pdi,mdi)]
    adx=rma(dx,14)
    k=[]
    for i,c in enumerate(close):
        a=max(0,i-13);hh=max(high[a:i+1]);ll=min(low[a:i+1])
        k.append(50.0 if hh<=ll else 100*(c-ll)/(hh-ll))
    d=[]
    for i in range(len(k)):
        a=max(0,i-2);d.append(sum(k[a:i+1])/(i-a+1))
    out=[]
    for i,r in enumerate(rows):
        atr_pct=atr[i]/close[i] if close[i] else 0.0
        out.append({
            "ts_ms":int(r["ts_ms"]),
            "macd":macd[i],"macd_signal":sig[i],"macd_hist":hist[i],
            "macd_hist_slope":hist[i]-hist[i-1] if i else 0.0,
            "stoch_k":k[i],"stoch_d":d[i],"stoch_delta":k[i]-d[i],
            "adx":adx[i],"plus_di":pdi[i],"minus_di":mdi[i],
            "atr":atr[i],"atr_pct":atr_pct,
            "ema9_rel":e9[i]/close[i]-1.0 if close[i] else 0.0,
            "ema21_rel":e21[i]/close[i]-1.0 if close[i] else 0.0,
            "ema50_rel":e50[i]/close[i]-1.0 if close[i] else 0.0,
            "trend_dir":1.0 if e9[i]>e21[i]>e50[i] else -1.0 if e9[i]<e21[i]<e50[i] else 0.0,
            "trend_strength":min(1.0,max(0.0,adx[i]/50.0)),
        })
    return out

def causal_indicator_map(minute_rows):
    frames={}
    for tf in (5,15,60):
        rs=resample(minute_rows,tf)
        series=indicator_series(rs)
        span=tf*60_000
        # Indicators become usable only after the bar closes.
        frames[tf]=[(x["ts_ms"]+span,x) for x in series]
    out={}
    ptr={tf:0 for tf in frames};last={tf:None for tf in frames}
    for r in sorted(minute_rows,key=lambda z:z["ts_ms"]):
        now=int(r["ts_ms"])+60_000
        feat={}
        for tf in (5,15,60):
            arr=frames[tf]
            while ptr[tf]<len(arr) and arr[ptr[tf]][0]<=now:
                last[tf]=arr[ptr[tf]][1];ptr[tf]+=1
            if last[tf]:
                for k,v in last[tf].items():
                    if k!="ts_ms" and finite(v):feat[f"tech_{tf}m_{k}"]=float(v)
        out[now]=feat
    return out

def score_components(x):
    def g(k,d=0.0):
        v=x.get(k);return float(v) if finite(v) else d
    def sq(v,s=1.0):return math.tanh(v/max(s,1e-12))
    trend=0.0
    for tf,w in ((5,.25),(15,.40),(60,.35)):
        trend+=w*(.45*sq(g(f"tech_{tf}m_macd_hist"),max(abs(g(f"tech_{tf}m_atr"))*.1,1e-6))+
                  .25*sq(g(f"tech_{tf}m_macd_hist_slope"),max(abs(g(f"tech_{tf}m_atr"))*.05,1e-6))+
                  .30*g(f"tech_{tf}m_trend_dir"))
    stoch_momentum=sum(w*sq((g(f"tech_{tf}m_stoch_k")-50)/25,1) for tf,w in ((5,.25),(15,.45),(60,.30)))
    stoch_reversal=sum(w*sq((50-g(f"tech_{tf}m_stoch_k"))/25,1) for tf,w in ((5,.45),(15,.40),(60,.15)))
    strength=sum(w*g(f"tech_{tf}m_trend_strength") for tf,w in ((5,.25),(15,.40),(60,.35)))
    flow=g("agent_flow_direction",g("agent_consensus"))
    book=g("agent_book_direction")
    oi_liq=g("agent_oi_liq_direction")
    local=g("agent_local_direction")
    structure=g("agent_structure_direction")
    timing=g("agent_timing_direction")
    confidence=g("agent_confidence",.5)
    adversary=g("agent_adversary_risk",0.0)
    quant=g("quant_direction",0.0)
    quant_conf=g("quant_confidence",0.0)
    return {
        "trend":max(-1,min(1,trend)),
        "stoch_momentum":max(-1,min(1,stoch_momentum)),
        "stoch_reversal":max(-1,min(1,stoch_reversal)),
        "strength":max(0,min(1,strength)),
        "flow":max(-1,min(1,flow)),
        "book":max(-1,min(1,book)),
        "oi_liq":max(-1,min(1,oi_liq)),
        "local":max(-1,min(1,local)),
        "structure":max(-1,min(1,structure)),
        "timing":max(-1,min(1,timing)),
        "quant":max(-1,min(1,quant)),
        "quant_confidence":max(0,min(1,quant_conf)),
        "confidence":max(0,min(1,max(confidence,quant_conf))),
        "adversary":max(0,min(1,adversary)),
    }
