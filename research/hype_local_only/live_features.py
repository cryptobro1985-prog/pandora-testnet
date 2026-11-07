from __future__ import annotations
import math,statistics
from typing import Any
from research.hype_local_only.feature_discovery import discover_live_features

WINDOWS=(5,15,30,60,180,300)

def finite(v):
    return isinstance(v,(int,float)) and math.isfinite(v)

def live_to_archive_features(side:str,age_s:float,extreme_price:float,price:float,x:dict[str,Any],state)->dict[str,float]:
    rev=1.0 if side=="LOW" else -1.0
    out={"age_s":float(max(0.0,age_s)),"retrace_bps":(price/extreme_price-1.0)*rev*10000.0}
    for w in WINDOWS:
        imb=x.get(f"flow_imbalance_raw_{w}s",x.get(f"flow_imbalance_{w}s"))
        ret=x.get(f"ret_{w}s")
        buy=x.get(f"trade_buy_notional_{w}s")
        sell=x.get(f"trade_sell_notional_{w}s")
        cnt=x.get(f"trade_count_{w}s")
        if finite(imb):
            out[f"imbalance_{w}s"]=float(imb);out[f"rev_flow_{w}s"]=float(imb)*rev
        if finite(ret):
            out[f"ret_{w}s"]=float(ret);out[f"rev_ret_{w}s"]=float(ret)*rev
        if finite(buy):out[f"buy_{w}s_log"]=math.log1p(max(0.0,float(buy)))
        if finite(sell):out[f"sell_{w}s_log"]=math.log1p(max(0.0,float(sell)))
        if finite(buy) and finite(sell):out[f"total_{w}s_log"]=math.log1p(max(0.0,float(buy)+float(sell)))
        if finite(cnt):out[f"trade_count_{w}s"]=float(cnt)
        be=x.get(f"buy_efficiency_{w}s");se=x.get(f"sell_efficiency_{w}s")
        if side=="LOW": rev_eff,old_eff=be,se
        else: rev_eff,old_eff=se,be
        if finite(rev_eff):out[f"rev_eff_{w}s"]=float(rev_eff)*1e6
        if finite(old_eff):out[f"old_eff_{w}s"]=float(old_eff)*1e6

    struct=getattr(state,"structural",{}) or {}
    for label,lo_key,hi_key in (
        ("60m","rolling_60m_low","rolling_60m_high"),
        ("6h","rolling_6h_low","rolling_6h_high"),
        ("24h","rolling_24h_low","rolling_24h_high"),
    ):
        lo=struct.get(lo_key);hi=struct.get(hi_key)
        if finite(lo) and finite(hi) and float(hi)>float(lo):
            lo=float(lo);hi=float(hi)
            out[f"position_{label}"]=(price-lo)/(hi-lo)
            out[f"distance_low_{label}_bps"]=(price/lo-1.0)*10000.0
            out[f"distance_high_{label}_bps"]=(hi/price-1.0)*10000.0

    m1=[state.candles["1"][k] for k in sorted(state.candles.get("1",{}))][-61:]
    if len(m1)>=2:
        rr=[m1[i]["close"]/m1[i-1]["close"]-1.0 for i in range(1,len(m1)) if m1[i-1]["close"]]
        if rr:out["volatility_60m"]=math.sqrt(sum(v*v for v in rr)/len(rr))
    v24=x.get("log_volume_24h")
    t24=x.get("log_turnover_24h")
    if finite(v24):out["volume_24h_log"]=float(v24)
    if finite(t24):out["turnover_24h_log"]=float(t24)

    # Names shared with the causally backfilled 30-day mark/index/OI/funding set.
    mark=x.get("mark_price");idx=x.get("index_price")
    if finite(mark):
        out["hist_mark_available"]=1.0
        if price>0:out["hist_mark_price_rel"]=float(mark)/price-1.0
    if finite(idx):
        out["hist_index_available"]=1.0
        if price>0:out["hist_index_price_rel"]=float(idx)/price-1.0
    if finite(mark) and finite(idx) and float(idx)!=0:
        out["hist_basis_bps"]=(float(mark)/float(idx)-1.0)*10000.0
    elif finite(x.get("basis_bps")):
        out["hist_basis_bps"]=float(x["basis_bps"])
    funding=x.get("funding_rate",x.get("struct_funding_rate"))
    if finite(funding):
        out["hist_funding_available"]=1.0;out["hist_funding_rate"]=float(funding)
    oi=x.get("open_interest_full",x.get("ticker_open_interest",x.get("open_interest")))
    if finite(oi) and float(oi)>=0:
        out["hist_oi_available"]=1.0
        out["hist_open_interest_log"]=math.log1p(float(oi))
        if price>0:out["hist_oi_notional_log"]=math.log1p(float(oi)*price)
        if finite(x.get("oi_delta_300s")):out["hist_oi_delta_300s"]=float(x["oi_delta_300s"])
        # FeatureState keeps ~3h of OI observations; reconstruct the same 1h delta
        # used by historical enrichment without looking forward.
        hist=list(getattr(state,"oi_history",[]) or [])
        target=int(getattr(state,"last_ts_ms",0) or 0)-3_600_000
        prev=None
        for t,v in hist:
            if int(t)<=target:prev=float(v)
            else:break
        if prev is not None and prev>0:
            out["hist_oi_delta_3600s"]=float(oi)/prev-1.0

    h1=[state.candles["60"][k] for k in sorted(state.candles.get("60",{}))]
    if h1:
        ranges=[(b["high"]-b["low"])/b["close"] for b in h1[-14:] if b.get("close")]
        if ranges:out["atr_h1_frac"]=sum(ranges)/len(ranges)
        for n in (3,6):
            p=h1[-n:]
            if len(p)==n and p[0].get("open"):
                out[f"directional_{n}h_rev"]=(p[-1]["close"]/p[0]["open"]-1.0)*rev

    prices=[(t,p) for t,p in getattr(state,"prices",[]) if t>=int(state.last_ts_ms or 0)-int(max(5,age_s)*1000)]
    signs=[]
    for (_,a),(_,b) in zip(prices,prices[1:]):
        d=b-a;s=1 if d>0 else -1 if d<0 else 0
        if s:signs.append(s)
    out["reversal_attempts"]=float(sum(a!=b for a,b in zip(signs,signs[1:])))

    # Discovery layer: indicators, structure/patterns, L50, liquidations,
    # OI/flow/price interactions. All values are causal at this timestamp.
    out.update(discover_live_features(side,price,x,state))

    # Preserve every live-only causal input as a separate namespace. Historical
    # training has no weight for these dimensions; they become learnable only
    # after live strict labels mature, never through zero-imputation.
    for k,v in x.items():
        if finite(v):out["live__"+str(k)]=float(v)
    return {k:float(v) for k,v in out.items() if finite(v)}
