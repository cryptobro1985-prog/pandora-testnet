from __future__ import annotations
import os, time, threading
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
        _cache.update(ts=now,data=out)
        return out

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
