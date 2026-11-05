from __future__ import annotations
import os, time, threading, json, math
from flask import Flask, jsonify
import requests

app=Flask(__name__)
BASES=("https://api.bybit.com","https://api.bytick.com","https://api.bybit.kz","https://api.bybit.ae","https://api.bybit.eu")
SYMBOL="HYPEUSDT"
_lock=threading.Lock()
_cache={"ts":0.0,"data":None}
_session=requests.Session()
_session.headers.update({"User-Agent":"PANDORA-HYPE-Research-Relay/1.0","Accept":"application/json"})

def request_json(path,params=None):
    errors=[]
    for base in BASES:
        try:
            r=_session.get(base+path,params=params or {},timeout=8)
            if r.status_code!=200:
                errors.append({"base":base,"status":r.status_code,"body":r.text[:160]})
                continue
            obj=r.json()
            if obj.get("retCode") not in (0,None):
                errors.append({"base":base,"retCode":obj.get("retCode"),"retMsg":obj.get("retMsg")})
                continue
            return obj,base
        except Exception as exc:
            errors.append({"base":base,"error":repr(exc)})
    raise RuntimeError(str(errors))

def _f(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None

def _book_imbalance(levels, n):
    bids=levels.get("b",[])[:n]; asks=levels.get("a",[])[:n]
    b=sum((_f(x[1]) or 0.0) for x in bids); a=sum((_f(x[1]) or 0.0) for x in asks)
    return None if b+a<=0 else (b-a)/(b+a)

def _derived(ticker, kl1, kl60, book, trades):
    last=_f(ticker.get("lastPrice")); mark=_f(ticker.get("markPrice")); idx=_f(ticker.get("indexPrice"))
    oi=_f(ticker.get("openInterest")); funding=_f(ticker.get("fundingRate"))
    m1=[]
    for r in reversed(kl1):
        if len(r)>=5:
            m1.append({"ts":int(r[0]),"o":_f(r[1]),"h":_f(r[2]),"l":_f(r[3]),"c":_f(r[4])})
    h1=[]
    for r in reversed(kl60):
        if len(r)>=5:
            h1.append({"ts":int(r[0]),"o":_f(r[1]),"h":_f(r[2]),"l":_f(r[3]),"c":_f(r[4])})
    def low(rows,n):
        z=[x["l"] for x in rows[-n:] if x.get("l") is not None]
        return min(z) if z else None
    def high(rows,n):
        z=[x["h"] for x in rows[-n:] if x.get("h") is not None]
        return max(z) if z else None
    buy=sell=0.0; nbuy=nsell=0
    for t in trades:
        p=_f(t.get("price")); q=_f(t.get("size"))
        if p is None or q is None: continue
        notion=p*q
        if str(t.get("side","")).lower()=="buy":
            buy+=notion; nbuy+=1
        elif str(t.get("side","")).lower()=="sell":
            sell+=notion; nsell+=1
    imb=None if buy+sell<=0 else (buy-sell)/(buy+sell)
    lo60=low(m1,60); lo360=low(m1,360); lo24=low(h1,24)
    hi60=high(m1,60)
    current_low=m1[-1]["l"] if m1 else None
    prev_low=min((x["l"] for x in m1[-11:-1] if x.get("l") is not None), default=None) if len(m1)>1 else None
    rebound=None if last is None or current_low in (None,0) else last/current_low-1.0
    return {
        "last_price":last,"mark_price":mark,"index_price":idx,"open_interest":oi,"funding_rate":funding,
        "basis_bps":None if mark is None or idx in (None,0) else (mark/idx-1)*10000,
        "rolling_60m_low":lo60,"rolling_60m_high":hi60,"rolling_6h_low":lo360,"rolling_24h_low":lo24,
        "current_m1_low":current_low,"previous_10m_low":prev_low,"rebound_from_current_m1_low":rebound,
        "book_imbalance_l5":_book_imbalance(book,5),"book_imbalance_l25":_book_imbalance(book,25),"book_imbalance_l50":_book_imbalance(book,50),
        "recent_trade_buy_notional":buy,"recent_trade_sell_notional":sell,"recent_trade_imbalance":imb,
        "recent_buy_trades":nbuy,"recent_sell_trades":nsell,
        "last_h1":h1[-1] if h1 else None,"prev_h1":h1[-2] if len(h1)>=2 else None,
    }

def fetch():
    now=time.time()
    with _lock:
        if _cache["data"] is not None and now-_cache["ts"]<15:
            return _cache["data"]
        out={"research_only":True,"symbol":SYMBOL,"relay_ts_ms":int(now*1000),"sources":{}}
        obj,base=request_json("/v5/market/instruments-info",{"category":"linear","symbol":SYMBOL})
        rows=obj.get("result",{}).get("list",[])
        out["instrument"]=rows[0] if rows else {}
        out["sources"]["instrument"]=base
        obj,base=request_json("/v5/market/account-ratio",{"category":"linear","symbol":SYMBOL,"period":"5min","limit":1})
        rows=obj.get("result",{}).get("list",[])
        out["account_ratio"]=rows[0] if rows else {}
        out["sources"]["account_ratio"]=base
        obj,base=request_json("/v5/market/time")
        out["server_time"]={"api_time_ms":obj.get("time"),"result":obj.get("result",{})}
        out["sources"]["server_time"]=base

        obj,base=request_json("/v5/market/tickers",{"category":"linear","symbol":SYMBOL})
        rows=obj.get("result",{}).get("list",[])
        ticker=rows[0] if rows else {}
        out["ticker"]=ticker; out["sources"]["ticker"]=base

        obj,base=request_json("/v5/market/kline",{"category":"linear","symbol":SYMBOL,"interval":"1","limit":360})
        kl1=obj.get("result",{}).get("list",[])
        out["sources"]["kline_1m"]=base

        obj,base=request_json("/v5/market/kline",{"category":"linear","symbol":SYMBOL,"interval":"60","limit":48})
        kl60=obj.get("result",{}).get("list",[])
        out["sources"]["kline_60m"]=base

        obj,base=request_json("/v5/market/orderbook",{"category":"linear","symbol":SYMBOL,"limit":50})
        book=obj.get("result",{}) or {}
        out["sources"]["orderbook"]=base

        obj,base=request_json("/v5/market/recent-trade",{"category":"linear","symbol":SYMBOL,"limit":500})
        trades=obj.get("result",{}).get("list",[])
        out["sources"]["recent_trade"]=base

        out["local_low_watch"]=_derived(ticker,kl1,kl60,book,trades)
        print("HYPE_LOCAL_LOW_WATCH "+json.dumps(out["local_low_watch"],separators=(",",":")),flush=True)
        _cache.update(ts=now,data=out)
        return out

@app.get("/")
def root():
    try:
        data=fetch()
        return jsonify({"ok":True,"symbol":SYMBOL,"relay_ts_ms":data["relay_ts_ms"],"local_low_watch":data.get("local_low_watch")})
    except Exception as exc:
        return jsonify({"ok":False,"error":repr(exc)}),503

@app.get("/health")
def health():
    try:
        data=fetch()
        return jsonify({"ok":True,"symbol":SYMBOL,"relay_ts_ms":data["relay_ts_ms"],"sources":data["sources"]})
    except Exception as exc:
        return jsonify({"ok":False,"error":repr(exc)}),503

@app.get("/hype-context")
def hype_context():
    try:
        return jsonify(fetch())
    except Exception as exc:
        return jsonify({"research_only":True,"symbol":SYMBOL,"error":repr(exc)}),503
