"""Causal feature discovery for HYPE Local learning.

The canonical 116-point plane is a source contract, not a ceiling. This module
creates additional *derived* causal features from data already observed at the
snapshot timestamp. It never reads teacher labels or future candles.

Families:
- technical/price: RSI, stochastic, Bollinger z, ATR, EMA gaps/slopes, ROC
- structure/patterns: HH/HL/LH/LL counts, bar-body/wick/reversal geometry
- flow: multi-window acceleration/divergence/price-efficiency
- L50 book: depth pressure, microprice, slope/shape, replenishment/cancels
- liquidations: side imbalance, burst ratios, flow/price interactions
- OI/funding/basis: regime interactions
"""
from __future__ import annotations
import bisect,math,statistics
from typing import Any

def finite(v): return isinstance(v,(int,float)) and math.isfinite(v)

def _ema(values,n):
    if not values:return None
    a=2.0/(n+1.0);e=float(values[0])
    for v in values[1:]:e=a*float(v)+(1-a)*e
    return e

def _rsi(values,n=14):
    if len(values)<n+1:return None
    ds=[float(b)-float(a) for a,b in zip(values[-n-1:-1],values[-n:])]
    gain=sum(max(d,0.0) for d in ds)/n;loss=sum(max(-d,0.0) for d in ds)/n
    if loss<=1e-12:return 100.0 if gain>0 else 50.0
    rs=gain/loss
    return 100.0-100.0/(1.0+rs)

def _atr(rows,n=14):
    if len(rows)<2:return None
    q=rows[-n:]
    tr=[]
    prev=None
    for b in q:
        hi=float(b["high"]);lo=float(b["low"]);cl=float(b["close"])
        tr.append(hi-lo if prev is None else max(hi-lo,abs(hi-prev),abs(lo-prev)))
        prev=cl
    return statistics.fmean(tr) if tr else None

def _candle_features(rows,side,prefix):
    out={}
    if not rows:return out
    closes=[float(x["close"]) for x in rows if finite(x.get("close"))]
    if len(closes)<2:return out
    px=closes[-1];rev=1.0 if side=="LOW" else -1.0
    for n in (5,9,14,21,50):
        if len(closes)>=n:
            e=_ema(closes[-n:],n)
            if e and e!=0:out[f"{prefix}ema{n}_gap_bps"]=(px/e-1.0)*10000.0
    if len(closes)>=21:
        e9=_ema(closes[-9:],9);e21=_ema(closes[-21:],21)
        if e9 and e21:out[f"{prefix}ema9_21_gap_bps"]=(e9/e21-1.0)*10000.0
    for n in (7,14):
        r=_rsi(closes,n)
        if r is not None:
            out[f"{prefix}rsi{n}"]=r
            out[f"{prefix}rsi{n}_rev"]=rev*(r-50.0)/50.0
    if len(closes)>=14:
        recent=rows[-14:];hh=max(float(x["high"]) for x in recent);ll=min(float(x["low"]) for x in recent)
        if hh>ll:
            st=(px-ll)/(hh-ll)
            out[f"{prefix}stoch14"]=st
            out[f"{prefix}stoch14_rev"]=(st if side=="LOW" else 1.0-st)
    if len(closes)>=20:
        q=closes[-20:];m=statistics.fmean(q);sd=statistics.pstdev(q)
        if sd>1e-12:
            z=(px-m)/sd
            out[f"{prefix}bollinger_z20"]=z
            out[f"{prefix}bollinger_z20_rev"]=z*rev
    a=_atr(rows,14)
    if a is not None and px>0:out[f"{prefix}atr14_frac"]=a/px
    for n in (3,5,10,20):
        if len(closes)>n and closes[-n-1]>0:
            roc=px/closes[-n-1]-1.0
            out[f"{prefix}roc{n}"]=roc
            out[f"{prefix}roc{n}_rev"]=roc*rev
    # Structure / pattern counts over recent bars.
    q=rows[-12:]
    hh=hl=lh=ll=0
    for a,b in zip(q,q[1:]):
        hh+=int(float(b["high"])>float(a["high"]))
        hl+=int(float(b["low"])>float(a["low"]))
        lh+=int(float(b["high"])<float(a["high"]))
        ll+=int(float(b["low"])<float(a["low"]))
    den=max(1,len(q)-1)
    out[f"{prefix}hh_ratio"]=hh/den;out[f"{prefix}hl_ratio"]=hl/den
    out[f"{prefix}lh_ratio"]=lh/den;out[f"{prefix}ll_ratio"]=ll/den
    last=q[-1];rng=max(float(last["high"])-float(last["low"]),1e-12)
    op=float(last["open"]);cl=float(last["close"]);hi=float(last["high"]);lo=float(last["low"])
    out[f"{prefix}body_share"]=abs(cl-op)/rng
    out[f"{prefix}upper_wick_share"]=max(0.0,hi-max(op,cl))/rng
    out[f"{prefix}lower_wick_share"]=max(0.0,min(op,cl)-lo)/rng
    out[f"{prefix}close_position"]=(cl-lo)/rng
    return out

def _book_features(state,price,side):
    out={}
    bids=sorted((getattr(state,"book_bids",{}) or {}).items(),reverse=True)[:50]
    asks=sorted((getattr(state,"book_asks",{}) or {}).items())[:50]
    if not bids or not asks:
        return {"book_quality_valid":0.0}
    # If the source exposes an exchange-time book timestamp, reject stale or
    # future-dated quotes rather than treating them as current liquidity.
    # Missing timestamp is explicitly unknown (not a fabricated fresh quote).
    book_ts=getattr(state,"book_ts_ms",None)
    decision_ts=getattr(state,"last_ts_ms",None)
    if book_ts is not None:
        if (not finite(book_ts) or not finite(decision_ts)
            or book_ts<=0 or decision_ts<=0):
            return {"book_quality_valid":0.0,"book_quality_timestamp_invalid":1.0}
        age_ms=decision_ts-book_ts
        if age_ms<0:
            return {"book_quality_valid":0.0,"book_quality_future":1.0}
        if age_ms>5000:
            return {"book_quality_valid":0.0,"book_quality_stale":1.0}
    # Do NOT clamp negative spreads to zero. A crossed/locked or malformed
    # book is an invalid executable quote, not a valid low-spread signal.
    # Keep all derived depth/microprice features absent when book is bad.
    if (not finite(price) or price<=0 or
        any(not finite(p) or not finite(q) or p<=0 or q<=0
            for p,q in bids+asks)):
        return {"book_quality_valid":0.0,"book_quality_malformed":1.0}
    bb,bq=bids[0];aa,aq=asks[0]
    if bb>=aa:
        return {"book_quality_valid":0.0,"book_quality_crossed_or_locked":1.0}
    rev=1.0 if side=="LOW" else -1.0
    spread=aa-bb
    out["book_quality_valid"]=1.0
    out["book_spread_bps"]=spread/price*10000.0
    den=bq+aq
    if den>0:
        micro=(aa*bq+bb*aq)/den
        out["book_microprice_dist_bps"]=(micro/price-1.0)*10000.0
        out["book_microprice_rev_bps"]=out["book_microprice_dist_bps"]*rev
    for n in (5,10,25,50):
        b=bids[:n];a=asks[:n]
        bn=sum(p*q for p,q in b);an=sum(p*q for p,q in a);tot=bn+an
        if tot>0:
            imb=(bn-an)/tot
            out[f"book_depth_imbalance_{n}"]=imb
            out[f"book_depth_imbalance_{n}_rev"]=imb*rev
        if b and a:
            bdist=statistics.fmean(abs(p/price-1.0)*10000.0 for p,_ in b)
            adist=statistics.fmean(abs(p/price-1.0)*10000.0 for p,_ in a)
            out[f"book_depth_shape_{n}"]=bdist-adist
            out[f"book_depth_shape_{n}_rev"]=(bdist-adist)*rev
    changes=list(getattr(state,"book_changes",[]) or [])
    ts=int(getattr(state,"last_ts_ms",0) or 0)
    for sec in (15,60,180):
        cs=[c for t,c in changes if ts-sec*1000 <= int(t) <= ts]
        if not cs:continue
        sums={k:sum(float(c.get(k,0.0) or 0.0) for c in cs) for k in ("bid_add","bid_cancel","ask_add","ask_cancel")}
        addden=sums["bid_add"]+sums["ask_add"];canden=sums["bid_cancel"]+sums["ask_cancel"]
        if addden>0:
            x=(sums["bid_add"]-sums["ask_add"])/addden
            out[f"book_add_imbalance_{sec}s"]=x;out[f"book_add_imbalance_{sec}s_rev"]=x*rev
        if canden>0:
            x=(sums["ask_cancel"]-sums["bid_cancel"])/canden
            out[f"book_cancel_pressure_{sec}s"]=x;out[f"book_cancel_pressure_{sec}s_rev"]=x*rev
    return out

def _liq_features(state,x,side):
    out={};rev=1.0 if side=="LOW" else -1.0
    ts=int(getattr(state,"last_ts_ms",0) or 0)
    liqs=list(getattr(state,"liqs",[]) or [])
    for sec in (15,60,180,300):
        q=[z for z in liqs if ts-sec*1000 <= int(z.get("ts_ms",0)) <= ts]
        if not q:continue
        lng=sum(float(z.get("notional",0.0) or 0.0) for z in q if z.get("side",0)>0)
        sht=sum(float(z.get("notional",0.0) or 0.0) for z in q if z.get("side",0)<0)
        den=lng+sht
        if den>0:
            imb=(sht-lng)/den  # positive = short-liquidation dominance
            out[f"liq_side_imbalance_{sec}s"]=imb
            # For LOW, long-liquidation flush can be capitulation; for HIGH the reverse.
            out[f"liq_capitulation_rev_{sec}s"]=(-imb if side=="LOW" else imb)
        out[f"liq_events_{sec}s"]=float(len(q))
    # Cross-family interactions are valuable only if both causes are observed.
    for sec in (60,180,300):
        liq=out.get(f"liq_side_imbalance_{sec}s")
        flow=x.get(f"flow_imbalance_raw_{sec}s")
        ret=x.get(f"ret_{sec}s")
        oi=x.get(f"oi_delta_{sec}s")
        if finite(liq) and finite(flow):out[f"liq_x_flow_{sec}s"]=liq*float(flow)
        if finite(liq) and finite(ret):out[f"liq_x_price_{sec}s"]=liq*float(ret)
        if finite(liq) and finite(oi):out[f"liq_x_oi_{sec}s"]=liq*float(oi)
    return out

def scalar_interactions(f,side):
    """Derived interactions from any causal snapshot dictionary, also usable offline."""
    out={};rev=1.0 if side=="LOW" else -1.0
    def g(k):return f.get(k)
    # Multi-window acceleration / divergence.
    for a,b in ((5,15),(15,60),(60,180),(180,300)):
        fa=g(f"imbalance_{a}s");fb=g(f"imbalance_{b}s")
        if finite(fa) and finite(fb):
            out[f"flow_accel_{a}v{b}"]=float(fa)-float(fb)
            out[f"flow_accel_{a}v{b}_rev"]=(float(fa)-float(fb))*rev
        ra=g(f"ret_{a}s");rb=g(f"ret_{b}s")
        if finite(ra) and finite(rb):
            out[f"return_accel_{a}v{b}"]=float(ra)-float(rb)
            out[f"return_accel_{a}v{b}_rev"]=(float(ra)-float(rb))*rev
        if finite(fa) and finite(ra):
            out[f"flow_price_agreement_{a}s"]=float(fa)*float(ra)
            out[f"flow_price_divergence_{a}s"]=float(fa)-math.tanh(float(ra)*1000.0)
    # Enriched OI/funding/basis regimes.
    oi5=g("hist_oi_delta_300s");oi60=g("hist_oi_delta_3600s")
    r300=g("ret_300s")
    if finite(oi5) and finite(r300):
        out["oi5m_x_price5m"]=float(oi5)*float(r300)
        out["oi5m_price_regime_rev"]=float(oi5)*float(r300)*rev
    if finite(oi5) and finite(oi60):out["oi_accel_5m_vs_1h"]=float(oi5)-float(oi60)/12.0
    fund=g("hist_funding_rate");basis=g("hist_basis_bps")
    if finite(fund) and finite(basis):out["funding_x_basis"]=float(fund)*float(basis)
    # Relative distance geometry.
    for label in ("60m","6h","24h"):
        lo=g(f"distance_low_{label}_bps");hi=g(f"distance_high_{label}_bps")
        if finite(lo) and finite(hi):
            den=abs(float(lo))+abs(float(hi))+1e-9
            out[f"range_pressure_{label}"]=(float(hi)-float(lo))/den
            out[f"range_pressure_{label}_rev"]=out[f"range_pressure_{label}"]*rev
    return out

def discover_live_features(side,price,x,state):
    out={}
    out.update(scalar_interactions(x,side))
    candles=getattr(state,"candles",{}) or {}
    for tf,prefix in (("1","m1__"),("3","m3__"),("5","m5__"),("60","h1__")):
        rows=[candles.get(tf,{})[k] for k in sorted(candles.get(tf,{}) or {})]
        out.update(_candle_features(rows,side,prefix))
    out.update(_book_features(state,price,side))
    out.update(_liq_features(state,x,side))
    # Generic live cross-effects from already causal state.
    for sec in (60,180,300):
        flow=x.get(f"flow_imbalance_raw_{sec}s");ret=x.get(f"ret_{sec}s");oi=x.get(f"oi_delta_{sec}s")
        if finite(flow) and finite(ret):out[f"live_flow_x_return_{sec}s"]=float(flow)*float(ret)
        if finite(oi) and finite(flow):out[f"live_oi_x_flow_{sec}s"]=float(oi)*float(flow)
    return {"discovery__"+k:float(v) for k,v in out.items() if finite(v)}

def historical_indicator_features(minutes,end_times,ts_ms,side):
    """Technical/structure discovery using only completed 1m bars <= ts_ms."""
    j=bisect.bisect_right(end_times,int(ts_ms))
    rows=minutes[max(0,j-240):j]
    out=_candle_features(rows,side,"m1__")
    return {"discovery__"+k:float(v) for k,v in out.items() if finite(v)}
