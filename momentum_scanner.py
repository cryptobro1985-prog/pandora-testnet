"""High-conviction PANDORA pump/dump detector (PAPER research only).

The detector intentionally ignores ordinary micro-momentum. A candidate must
show a sustained, directionally consistent impulse plus abnormal participation.
Order-book/CVD confirmation is applied by app.py before an entry is allowed.
"""
import math

def _anchor(samples,epoch,age):
    rows=[r for r in samples if age-12 <= epoch-r["t"] <= age+18]
    return min(rows,key=lambda r:abs((epoch-r["t"])-age)) if rows else None

def candidates(prices,history,volumes,epoch,minimum_day_volume=5_000_000.0,contexts=None):
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
                if isinstance(t,(int,float)) and isinstance(p,(int,float)) and 0<=epoch-t<=240 and math.isfinite(p) and p>0:
                    rows.append({"t":float(t),"p":float(p)})
        if len(rows)<12 or epoch-rows[-1]["t"]>8:continue
        a15=_anchor(rows,epoch,15);a60=_anchor(rows,epoch,60);a180=_anchor(rows,epoch,180)
        if not a15 or not a60 or not a180:continue
        r15=price/a15["p"]-1;r60=price/a60["p"]-1;r180=price/a180["p"]-1
        side=1 if r15>0 else -1
        # Real impulse: all horizons point the same way. This removes the old
        # behaviour that bought a 15s bounce inside a 1-3 minute selloff.
        if not (side*r15>0 and side*r60>0 and side*r180>0):continue
        if abs(r15)<0.0025 or abs(r60)<0.0045 or abs(r180)<0.0040:continue
        # Avoid chasing already vertical terminal spikes.
        if abs(r15)>0.018 or abs(r60)>0.035 or abs(r180)>0.060:continue

        accel=side*(r15-r60*0.25)
        if accel<0.0010:continue
        recent=[r["p"] for r in rows[-6:]]
        if len(recent)<6:continue
        # Direction must persist through recent samples, not be one print.
        steps=[(recent[i]/recent[i-1]-1)*side for i in range(1,len(recent))]
        if sum(x>0 for x in steps)<3:continue

        ctx=contexts.get(symbol,{})
        oi_delta=float(ctx.get("oi_delta_60s") or 0)
        vol_burst=float(ctx.get("volume_burst_ratio") or 0)
        # Abnormal participation is mandatory. Academic P&D work consistently
        # finds anomalous volume more useful than raw price change alone.
        if vol_burst<2.0:continue

        score=40.0
        score+=min(16,abs(r15)*2400)
        score+=min(16,abs(r60)*1200)
        score+=min(10,abs(r180)*450)
        score+=min(12,max(0.0,(vol_burst-2.0))*2.0)
        if abs(oi_delta)>=0.003:score+=8
        if abs(oi_delta)>=0.010:score+=4
        if accel>=0.002:score+=6

        out.append({
            "symbol":symbol,"side":side,"score":round(max(0,min(100,score)),2),
            "r15_pct":round(r15*100,3),"r60_pct":round(r60*100,3),"r180_pct":round(r180*100,3),
            "accel":round(side*accel,6),"oi_delta_60s":round(oi_delta,6),
            "volume_burst_ratio":round(vol_burst,3),"day_volume_usd":round(day_volume,2),
            "trend_consistent":True,"exhaustion":False
        })
    return sorted(out,key=lambda x:x["score"],reverse=True)
