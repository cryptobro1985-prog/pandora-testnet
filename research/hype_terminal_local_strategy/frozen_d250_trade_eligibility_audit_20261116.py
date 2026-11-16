"""Frozen D250 entry eligibility audit, separate from event coverage and fill proof.
Research only. Never labels an entry safe solely from historical correctness.
Input: JSON list of per-trade records. UTC timestamps in milliseconds.
"""
import json,sys,math
from collections import Counter
THRESHOLDS={"rev_atr":2.0840049433824706,"trade_ratio5":0.2727842248141979,"flow15":0.4504731635235635}
def finite(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def audit(e):
    ident=e.get("id","UNKNOWN")
    side=e.get("side")
    if side not in ("LONG","SHORT"): return {"id":ident,"status":"INVALID_SIDE"}
    if e.get("local_type") != ("LOW" if side=="LONG" else "HIGH"):
        return {"id":ident,"status":"LOCAL_SIDE_MISMATCH"}
    try:
        extreme,confirm,signal,entry=[int(e[k]) for k in ("local_extreme_ts_ms","local_confirmed_ts_ms","signal_ts_ms","entry_ts_ms")]
    except (KeyError,TypeError,ValueError): return {"id":ident,"status":"MISSING_TIMESTAMPS"}
    if not (extreme<=confirm<=signal<=entry): return {"id":ident,"status":"CAUSALITY_VIOLATION"}
    if signal<extreme+250*60000: return {"id":ident,"status":"BEFORE_D250"}
    if e.get("same_side_extreme_before_signal") is not False or e.get("opposite_local_before_signal") is not False:
        return {"id":ident,"status":"LOCAL_STATE_UNKNOWN_OR_INVALID"}
    # Explicit timestamped feature observations; never accept features measured after signal.
    features=e.get("features")
    if not isinstance(features,dict): return {"id":ident,"status":"MISSING_FEATURES"}
    for k in THRESHOLDS:
        f=features.get(k)
        if not isinstance(f,dict) or not finite(f.get("value")) or not isinstance(f.get("observed_ts_ms"),int):
            return {"id":ident,"status":"MISSING_OR_INVALID_FEATURE","feature":k}
        if f["observed_ts_ms"]>signal or f["observed_ts_ms"]<extreme:
            return {"id":ident,"status":"FEATURE_TIME_VIOLATION","feature":k}
    if not (features["rev_atr"]["value"]>THRESHOLDS["rev_atr"] and
            features["trade_ratio5"]["value"]>THRESHOLDS["trade_ratio5"] and
            features["flow15"]["value"]<THRESHOLDS["flow15"]):
        return {"id":ident,"status":"D250_RULE_FAIL"}
    return {"id":ident,"status":"D250_ELIGIBLE_ONLY","execution_verified":False,"net_pnl":None}
def self_test():
    base={"id":"synthetic","side":"LONG","local_type":"LOW","local_extreme_ts_ms":0,
          "local_confirmed_ts_ms":7200000,"signal_ts_ms":15000000,"entry_ts_ms":15060000,
          "same_side_extreme_before_signal":False,"opposite_local_before_signal":False,
          "features":{k:{"value":v,"observed_ts_ms":15000000} for k,v in
                      {"rev_atr":2.2,"trade_ratio5":0.3,"flow15":0.4}.items()}}
    assert audit(base)["status"]=="D250_ELIGIBLE_ONLY"
    def change(fn):
        e=json.loads(json.dumps(base));fn(e);return audit(e)["status"]
    assert change(lambda e:e.update(local_type="HIGH"))=="LOCAL_SIDE_MISMATCH"
    assert change(lambda e:e["features"]["flow15"].update(value=0.46))=="D250_RULE_FAIL"
    assert change(lambda e:e["features"]["rev_atr"].update(observed_ts_ms=15000001))=="FEATURE_TIME_VIOLATION"
    assert change(lambda e:e.update(signal_ts_ms=14999999))=="BEFORE_D250"
    assert change(lambda e:e.update(same_side_extreme_before_signal=None))=="LOCAL_STATE_UNKNOWN_OR_INVALID"
    assert change(lambda e:e["features"]["trade_ratio5"].update(value=float("nan")))=="MISSING_OR_INVALID_FEATURE"
    print("PASS 7 synthetic D250 causality/threshold tests; zero historical trades validated")
if __name__=="__main__":
    if len(sys.argv)==1:self_test()
    else:
        rows=[audit(e) for e in json.load(open(sys.argv[1],encoding="utf8"))]
        for r in rows:print(json.dumps(r,sort_keys=True))
        print(json.dumps({"summary":dict(Counter(r["status"] for r in rows))}))
