"""Fetch public Bybit REST series (OI 5m, holder ratio 5m, mark/index 1m kline, funding). Research only, public endpoints, no keys."""
import json,time,urllib.request,urllib.parse,gzip,sys
from pathlib import Path
OUT=Path("/workspace/data/rest");OUT.mkdir(parents=True,exist_ok=True)
START=1776988800000 # 2026-04-24
END=1794528000000   # 2026-11-13
def get(path,q):
    url="https://api.bybit.com"+path+"?"+urllib.parse.urlencode(q)
    for a in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"research"}),timeout=30) as r:
                d=json.loads(r.read())
            if d.get("retCode")==0:return d["result"]
            time.sleep(1+a)
        except Exception as e:
            time.sleep(1+a)
    raise RuntimeError(url)
def windowed(path,base,key,span_ms,parse,tsk):
    rows={}
    t=START
    while t<END:
        e=min(END,t+span_ms)
        res=get(path,{**base,key[0]:t,key[1]:e-1})
        for x in res["list"]:
            r=parse(x);rows[r[tsk]]=r
        t=e
    return [rows[k] for k in sorted(rows)]
which=sys.argv[1]
if which=="oi":
    rows=windowed("/v5/market/open-interest",{"category":"linear","symbol":"HYPEUSDT","intervalTime":"5min","limit":200},("startTime","endTime"),200*300000-1,
        lambda x:{"ts":int(x["timestamp"]),"oi":float(x["openInterest"])},"ts")
elif which=="ratio":
    rows=windowed("/v5/market/account-ratio",{"category":"linear","symbol":"HYPEUSDT","period":"5min","limit":500},("startTime","endTime"),500*300000-1,
        lambda x:{"ts":int(x["timestamp"]),"buy_ratio":float(x["buyRatio"])},"ts")
elif which in("mark","index"):
    p="/v5/market/mark-price-kline" if which=="mark" else "/v5/market/index-price-kline"
    rows=windowed(p,{"category":"linear","symbol":"HYPEUSDT","interval":"1","limit":1000},("start","end"),1000*60000,
        lambda x:{"ts":int(x[0]),"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4])},"ts")
elif which=="funding":
    rows=windowed("/v5/market/funding/history",{"category":"linear","symbol":"HYPEUSDT","limit":200},("startTime","endTime"),200*3600000,
        lambda x:{"ts":int(x["fundingRateTimestamp"]),"rate":float(x["fundingRate"])},"ts")
with gzip.open(OUT/f"{which}.json.gz","wt") as f:json.dump(rows,f)
print(which,len(rows),rows[0] if rows else None,rows[-1] if rows else None)
