"""PANDORA independent pump/dump signal detector (PAPER research only).

Uses sustained acceleration, OI expansion, volume burst and optional order-book
confirmation. It never reads news-engine settings and never mutates news positions.
"""
import math

def _anchor(samples,epoch,age):
    rows=[r for r in samples if age-12 <= epoch-r["t"] <= age+18]
    return min(rows,key=lambda r:abs((epoch-r["t"])-age)) if rows else None

def candidates(prices,history,volumes,epoch,minimum_day_volume=2_000_000.0,contexts=None):
    contexts=contexts or {}
    out=[]
    for symbol,price in prices.items():
        day_volume=volumes.get(symbol)
        if not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:continue
        if not isinstance(day_volume,(int,float)) or not math.isfinite(day_volume) or day_volume<minimum_day_volume:continue
        rows=[]
        for item in history.get(symbol,[]):
            if len(item)>=2:
                t,p=item[0],item[1]
                if isinstance(t,(int,float)) and isinstance(p,(int,float)) and 0<=epoch-t<=210 and math.isfinite(p) and p>0:
                    rows.append({"t":float(t),"p":float(p)})
        if len(rows)<8 or epoch-rows[-1]["t"]>8:continue
        a15=_anchor(rows,epoch,15);a60=_anchor(rows,epoch,60);a180=_anchor(rows,epoch,180)
        if not a15 or not a60:continue
        r15=price/a15["p"]-1;r60=price/a60["p"]-1;r180=price/a180["p"]-1 if a180 else r60
        side=1 if r15>0 else -1
        accel=r15-r60*0.25
        # Require sustained impulse; a single spike is not enough.
        recent=[r["p"] for r in rows[-4:]]
        if len(recent)<4 or any(abs(p/price-1)>0.018 for p in recent):continue
        ctx=contexts.get(symbol,{})
        oi_delta=float(ctx.get("oi_delta_60s") or 0)
        vol_burst=float(ctx.get("volume_burst_ratio") or 0)
        imbalance=float(ctx.get("orderbook_imbalance") or 0)
        spread=float(ctx.get("spread_bps") or 9999)
        score=0.0
        # Responsive intraminute detector: price itself can trigger a candidate;
        # OI/volume/book improve confidence instead of being mandatory.
        score+=min(30,abs(r15)*7000)
        score+=min(28,abs(r60)*2600)
        score+=min(14,abs(r180)*900)
        if r15*r60>0:score+=8
        if r60*r180>0:score+=5
        if side*accel>0.00045:score+=8
        if oi_delta>0.002:score+=min(10,3+oi_delta*700)
        if vol_burst>1.2:score+=min(10,(vol_burst-1)*6)
        if side*imbalance>=0.10:score+=7
        elif side*imbalance<=-0.20:score-=10
        if spread<=12:score+=3
        elif spread>40:score-=15
        # A meaningful 60s move must exist; prevents micro-noise from opening trades.
        if abs(r60)<0.0018 and abs(r15)<0.0012:continue
        exhaustion=(abs(r15)>=0.009 and side*imbalance<0.02) or (abs(r60)>=0.018 and side*accel<0)
        if score>=48:
            out.append({"symbol":symbol,"side":side,"score":round(max(0,min(100,score)),2),
                        "r15_pct":round(r15*100,3),"r60_pct":round(r60*100,3),"r180_pct":round(r180*100,3),
                        "accel":round(accel,6),"oi_delta_60s":round(oi_delta,6),
                        "volume_burst_ratio":round(vol_burst,3),"orderbook_imbalance":round(imbalance,4),
                        "spread_bps":round(spread,2),"exhaustion":bool(exhaustion),
                        "day_volume_usd":round(day_volume,2)})
    return sorted(out,key=lambda x:x["score"],reverse=True)
