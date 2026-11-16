"""Research-only conservative M1 stop replay. No invented intrabar ordering or fills.
Input: JSON list of episodes {id,side,entry_ts_ms,entry_price,stop_price,exit_ts_ms,
exit_price,bars:[{ts_ms,open,high,low,close}...]}. Timestamp is bar START.
All prices are hypothetical executable proxies, not verified bid/ask or mark fills.
"""
import json,sys
import math
def replay(e):
    side=e["side"]; assert side in ("LONG","SHORT")
    entry=float(e["entry_price"]); stop=float(e["stop_price"])
    assert entry>0 and stop>0 and ((stop<entry) if side=="LONG" else (stop>entry))
    if not (math.isfinite(entry) and math.isfinite(stop)): return {"id":e["id"],"status":"INVALID_PRICE"}
    t0=int(e["entry_ts_ms"]); t1=int(e["exit_ts_ms"]); assert t1>t0
    bars=sorted(e["bars"],key=lambda x:x["ts_ms"])
    if not bars or bars[0]["ts_ms"]>t0 or bars[-1]["ts_ms"]+60000<t1:
        return {"id":e["id"],"status":"UNKNOWN_COVERAGE"}
    # M1 cannot resolve price path after an entry/exit inside a candle.
    if t0%60000: return {"id":e["id"],"status":"UNKNOWN_ENTRY_INTRABAR"}
    if t1%60000: return {"id":e["id"],"status":"UNKNOWN_EXIT_INTRABAR"}
    expected=list(range(t0,t1,60000))
    relevant=[int(b["ts_ms"]) for b in bars if t0<=int(b["ts_ms"])<t1]
    if relevant!=expected: return {"id":e["id"],"status":"UNKNOWN_GAP_OR_BOUNDARY"}
    prev=None; hit=None; mfe=0.; mae=0.; completed_mfe=0.; completed_mae=0.
    for b in bars:
        t=int(b["ts_ms"])
        if t<t0 or t>=t1: continue
        if prev is not None and t-prev!=60000: return {"id":e["id"],"status":"UNKNOWN_GAP"}
        prev=t
        o,h,l,c=[float(b[k]) for k in ("open","high","low","close")]
        if not (0<l<=min(o,c)<=max(o,c)<=h): return {"id":e["id"],"status":"INVALID_OHLC"}
        # If entry is inside a bar, pre-entry high/low cannot be attributed to the position.
        if t==t0 and t0%60000: return {"id":e["id"],"status":"UNKNOWN_ENTRY_INTRABAR"}
        favorable=(h-entry if side=="LONG" else entry-l)/entry
        adverse=(entry-l if side=="LONG" else h-entry)/entry
        mfe=max(mfe,favorable);mae=max(mae,adverse)
        touched=l<=stop if side=="LONG" else h>=stop
        if touched:
            gap=o<stop if side=="LONG" else o>stop
            hit={"ts_ms":t,"stop_touched":True,"open_beyond_stop":gap,
                 "fill_status":"UNKNOWN_NO_BID_ASK_OR_TRADE_TAPE"}
            break
        completed_mfe=max(completed_mfe,favorable)
        completed_mae=max(completed_mae,adverse)
    return {"id":e["id"],"status":"STOP_TOUCHED_FILL_UNKNOWN" if hit else "NO_STOP_TOUCH_IN_M1",
            "stop":hit,"mfe_upper_bound":None if hit else mfe,"mae_upper_bound":None if hit else mae,
            "completed_pre_stop_m1_mfe_envelope":completed_mfe,
            "completed_pre_stop_m1_mae_envelope":completed_mae,
            "pre_stop_bar_favorable_upper_bound":mfe if hit else None,
            "note":"Completed pre-stop M1 candle extremes are observed envelopes, not executable fills. Stop-bar MAE/MFE are excluded from completed envelopes. Stop bar favorable extreme is not verified to occur before stop; pre_stop_bar_favorable_upper_bound is NOT captured MFE. M1 is not a verified fill."}
def self_test():
    base={"id":"synthetic","side":"LONG","entry_ts_ms":0,"entry_price":100,
          "stop_price":99,"exit_ts_ms":120000,"exit_price":102,
          "bars":[{"ts_ms":0,"open":100,"high":103,"low":98,"close":102},
                  {"ts_ms":60000,"open":102,"high":104,"low":101,"close":103}]}
    assert replay(base)["status"]=="STOP_TOUCHED_FILL_UNKNOWN"
    assert replay(base)["stop"]["open_beyond_stop"] is False
    g=dict(base,bars=[dict(base["bars"][0],open=98,low=97,high=103,close=102),base["bars"][1]])
    assert replay(g)["stop"]["open_beyond_stop"] is True
    gap=dict(base,bars=[base["bars"][0],dict(base["bars"][1],ts_ms=180000)],exit_ts_ms=240000)
    assert replay(gap)["status"]=="UNKNOWN_GAP_OR_BOUNDARY"
    clean=dict(base,bars=[dict(base["bars"][0],low=99.2),base["bars"][1]])
    assert replay(clean)["status"]=="NO_STOP_TOUCH_IN_M1"
    print("PASS 4 synthetic cases; no real execution verified")
if __name__=="__main__":
    if len(sys.argv)==1:self_test()
    else:
        for e in json.load(open(sys.argv[1],encoding="utf8")): print(json.dumps(replay(e),sort_keys=True))
