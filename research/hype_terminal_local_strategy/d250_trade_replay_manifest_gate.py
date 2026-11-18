#!/usr/bin/env python3
"""Fail-closed gate for frozen-D250 trade-level event replay. No orders or training."""
import argparse, csv, json, math
from collections import Counter
from datetime import datetime, timezone

REQUIRED = ("trade_id","side","local_kind","local_extreme_utc","h1_confirmed_utc",
            "d250_signal_utc","entry_utc","entry_price","rev_atr","trade_ratio5",
            "flow15","rev_atr_asof_utc","trade_ratio5_asof_utc","flow15_asof_utc",
            "exit_utc","exit_price","exit_reason","m1_coverage",
            "public_trades_coverage","mark_coverage")
THRESHOLDS = (2.0840049433824706, 0.2727842248141979, 0.4504731635235635)
def stamp(v):
    t=datetime.fromisoformat(v.replace("Z","+00:00"))
    if t.tzinfo is None: raise ValueError("naive timestamp")
    return t.astimezone(timezone.utc)
def audit(row):
    reasons=[]
    try:
        if row["side"] not in ("LONG","SHORT") or (row["side"],row["local_kind"]) not in (("LONG","LOW"),("SHORT","HIGH")):
            reasons.append("SIDE_LOCAL_MISMATCH")
        ts={k:stamp(row[k]) for k in ("local_extreme_utc","h1_confirmed_utc","d250_signal_utc","entry_utc","rev_atr_asof_utc","trade_ratio5_asof_utc","flow15_asof_utc","exit_utc")}
        if not (ts["local_extreme_utc"]<=ts["h1_confirmed_utc"]<=ts["d250_signal_utc"]<=ts["entry_utc"]<=ts["exit_utc"]):
            reasons.append("NONCAUSAL_SEQUENCE")
        if (ts["d250_signal_utc"]-ts["local_extreme_utc"]).total_seconds()<250*60:
            reasons.append("D250_TOO_EARLY")
        if row["exit_reason"]=="OPPOSITE_CONFIRMED" and not row.get("opposite_confirmed_utc","").strip():
            reasons.append("MISSING_OPPOSITE_CONFIRMATION")
        if row.get("opposite_confirmed_utc","").strip():
            ts["opposite_confirmed_utc"]=stamp(row["opposite_confirmed_utc"])
            if ts["opposite_confirmed_utc"]<=ts["entry_utc"]:
                reasons.append("OPPOSITE_PRECEDES_SIGNAL")
            if row["exit_reason"]=="STOP" and ts["opposite_confirmed_utc"]<ts["exit_utc"]:
                reasons.append("STOP_AFTER_OPPOSITE_CONFIRMATION")
        if row["exit_reason"] not in ("STOP","OPPOSITE_CONFIRMED"):
            reasons.append("UNKNOWN_EXIT_REASON")
        if row["exit_reason"]=="OPPOSITE_CONFIRMED" and "opposite_confirmed_utc" in ts and ts["exit_utc"]<=ts["opposite_confirmed_utc"]:
            reasons.append("EXIT_BEFORE_OPPOSITE_CONFIRMATION")
        for name in ("rev_atr","trade_ratio5","flow15"):
            if ts[name+"_asof_utc"]>ts["d250_signal_utc"]:
                reasons.append("FUTURE_FEATURE_"+name.upper())
        a,b,c=[float(row[k]) for k in ("rev_atr","trade_ratio5","flow15")]
        if not all(map(math.isfinite,(a,b,c))) or not (a>THRESHOLDS[0] and b>THRESHOLDS[1] and c<THRESHOLDS[2]):
            reasons.append("FROZEN_D250_NOT_MET")
        if not all(math.isfinite(float(row[k])) and float(row[k])>0 for k in ("entry_price","exit_price")):
            reasons.append("BAD_PRICE")
        for k in ("m1_coverage","public_trades_coverage","mark_coverage"):
            if row[k]!="COMPLETE": reasons.append("UNCERTAIN_"+k.upper())
    except (ValueError,TypeError,KeyError,OverflowError) as e:
        reasons.append("INVALID_OR_MISSING_FIELD:"+type(e).__name__)
    return sorted(set(reasons))
def main():
    p=argparse.ArgumentParser()
    p.add_argument("manifest_csv")
    p.add_argument("--out",required=True)
    a=p.parse_args()
    with open(a.manifest_csv,newline="",encoding="utf-8") as f:
        reader=csv.DictReader(f)
        missing=sorted(set(REQUIRED)-set(reader.fieldnames or []))
        if missing: raise SystemExit("MISSING_COLUMNS: "+",".join(missing))
        rows=list(reader)
    seen=set(); findings=[]; counts=Counter()
    for r in rows:
        reasons=audit(r)
        if not r["trade_id"] or r["trade_id"] in seen: reasons.append("DUPLICATE_OR_EMPTY_ID")
        seen.add(r["trade_id"])
        counts[r["side"]]+=1
        findings.append({"trade_id":r["trade_id"],"side":r["side"],"status":"ELIGIBLE_FOR_EVENT_REPLAY" if not reasons else "BLOCKED","reasons":reasons})
    result={"status":"MANIFEST_ONLY_NOT_EXECUTION_REPLAY","count":len(rows),"by_side":dict(counts),
            "eligible":sum(x["status"]=="ELIGIBLE_FOR_EVENT_REPLAY" for x in findings),
            "blocked":sum(x["status"]=="BLOCKED" for x in findings),"findings":findings,
            "limitations":["Coverage COMPLETE is a manifest assertion, not independently verified exchange evidence",
                           "Does not validate same-side invalidation, book fills, funding, stop gaps, liquidation, or overlapping capital",
                           "STOP exits may precede opposite confirmation; opposite_confirmed_utc optional for STOP and required for OPPOSITE_CONFIRMED",
                           "Requires independent matched event tape before reporting PnL or liquidation count"]}
    with open(a.out,"w",encoding="utf-8") as f: json.dump(result,f,indent=2)
    print(json.dumps({"count":result["count"],"eligible":result["eligible"],"blocked":result["blocked"]}))
if __name__=="__main__": main()
