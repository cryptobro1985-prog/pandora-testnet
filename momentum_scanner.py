"""PANDORA paper-only impulse detector.

A candidate is produced only from fresh, sustained price changes in liquid
perpetuals. It does not fabricate a price, volume or real-time social signal.
"""
import math

CORE=("BTC","ETH","SOL","XRP","BNB","DOGE","ADA","TRX")
EVENT=("HYPE",)
ALL=CORE+EVENT

def candidates(prices,history,volumes,epoch,minimum_day_volume=1_000_000.0):
    out=[]
    for symbol in ALL:
        price=prices.get(symbol)
        day_volume=volumes.get(symbol)
        if not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:
            continue
        if not isinstance(day_volume,(int,float)) or not math.isfinite(day_volume) or day_volume<minimum_day_volume:
            continue
        samples=[(float(t),float(p)) for t,p in history.get(symbol,[])
                 if isinstance(t,(int,float)) and isinstance(p,(int,float))
                 and 0<=epoch-t<=195 and math.isfinite(p) and p>0]
        if len(samples)<10 or epoch-samples[-1][0]>8:
            continue
        # Ignore a stale/broken market stream and abrupt data gaps.
        if any(b[0]-a[0]>12 for a,b in zip(samples[-20:],samples[-19:])):
            continue
        for window,threshold in ((60,0.012),(180,0.024)):
            anchors=[(t,p) for t,p in samples if window-10<=epoch-t<=window+12]
            if not anchors:
                continue
            anchor=min(anchors,key=lambda row:abs(epoch-row[0]-window))[1]
            change=price/anchor-1
            if abs(change)<threshold:
                continue
            # Impulse must not be a single bad tick: latest prices must agree.
            if len(samples)<3:continue
            recent=[p for _,p in samples[-3:]]
            if any(abs(p/price-1)>0.012 for p in recent):continue
            side=1 if change>0 else -1
            out.append({"symbol":symbol,"side":side,"window":window,
                        "change_pct":round(change*100,3),
                        "day_volume_usd":round(day_volume,2)})
            break
    return sorted(out,key=lambda p:abs(p["change_pct"]),reverse=True)
