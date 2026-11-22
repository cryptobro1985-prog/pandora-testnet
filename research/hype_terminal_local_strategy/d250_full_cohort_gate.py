#!/usr/bin/env python3
"""Audit full frozen D250 accepted-signal cohort without fabricating censored exits.
Research-only manifest gate, NOT an execution replay or live-order authorization.
Usage: python d250_full_cohort_gate.py signals.csv --out audit.json
       python d250_full_cohort_gate.py --self-test
"""
import argparse, csv, json, math
from collections import Counter
from datetime import datetime, timezone, timedelta

THRESHOLDS=(2.0840049433824706,0.2727842248141979,0.4504731635235635)
STATUSES={"CLOSED_STOP","CLOSED_OPPOSITE","OPEN_AT_CUTOFF","UNKNOWN_DATA"}
REQUIRED={"signal_id","side","local_kind","local_extreme_utc","h1_confirmed_utc",
"d250_signal_utc","feature_available_utc","entry_utc","rev_atr","trade_ratio5",
"flow15","rev_atr_asof_utc","trade_ratio5_asof_utc","flow15_asof_utc",
"status","observation_cutoff_utc","source_sha256","same_side_ledger_coverage",
"opposite_ledger_coverage","opposite_ledger_start_utc","opposite_ledger_end_utc",
"opposite_ledger_first_utc","entry_price","exit_utc","exit_price","exit_reason",
"quote_coverage","mark_coverage","last_bid_utc","last_ask_utc","last_mark_utc",
"last_bid","last_ask","last_mark"}
def dt(v):
    t=datetime.fromisoformat(v.replace("Z","+00:00"))
    if t.tzinfo is None: raise ValueError("timestamp missing timezone")
    return t.astimezone(timezone.utc)
def positive(v):
    n=float(v)
    return math.isfinite(n) and n>0
def audit(r):
    issues=[]
    try:
        status=r["status"]
        if status not in STATUSES: issues.append("INVALID_STATUS")
        if (r["side"],r["local_kind"]) not in {("LONG","LOW"),("SHORT","HIGH")}:
            issues.append("SIDE_LOCAL_MISMATCH")
        t={k:dt(r[k]) for k in ("local_extreme_utc","h1_confirmed_utc",
          "d250_signal_utc","feature_available_utc","entry_utc",
          "observation_cutoff_utc","rev_atr_asof_utc","trade_ratio5_asof_utc",
          "flow15_asof_utc","opposite_ledger_start_utc","opposite_ledger_end_utc")}
        earliest=max(t["h1_confirmed_utc"],t["d250_signal_utc"],t["feature_available_utc"])
        if t["entry_utc"]<earliest: issues.append("ENTRY_BEFORE_CAUSAL_AVAILABILITY")
        if status=="UNKNOWN_DATA": issues.append("UNKNOWN_DATA_NOT_EXECUTION_ELIGIBLE")
        if t["feature_available_utc"]>t["d250_signal_utc"]: issues.append("FEATURE_NOT_AVAILABLE_AT_SIGNAL")
        if t["opposite_ledger_start_utc"]>t["entry_utc"]: issues.append("OPPOSITE_LEDGER_STARTS_AFTER_ENTRY")
        if t["d250_signal_utc"]<t["local_extreme_utc"]+timedelta(minutes=250):
            issues.append("D250_TOO_EARLY")
        if t["local_extreme_utc"]>t["h1_confirmed_utc"]: issues.append("LOCAL_TIME_INVERSION")
        if t["entry_utc"]>t["observation_cutoff_utc"]: issues.append("ENTRY_AFTER_CUTOFF")
        for k in ("rev_atr","trade_ratio5","flow15"):
            if t[k+"_asof_utc"]>t["d250_signal_utc"]: issues.append("FUTURE_FEATURE_"+k.upper())
        a,b,c=(float(r[k]) for k in ("rev_atr","trade_ratio5","flow15"))
        if not all(map(math.isfinite,(a,b,c))) or not (a>THRESHOLDS[0] and b>THRESHOLDS[1] and c<THRESHOLDS[2]):
            issues.append("FROZEN_RULE_NOT_MET")
        if not positive(r["entry_price"]): issues.append("BAD_ENTRY_PRICE")
        if len(r["source_sha256"])!=64 or any(ch not in "0123456789abcdefABCDEF" for ch in r["source_sha256"]):
            issues.append("MISSING_SOURCE_HASH")
        for k in ("same_side_ledger_coverage","opposite_ledger_coverage"):
            if r[k]!="COMPLETE": issues.append("UNVERIFIED_"+k.upper())
        if t["opposite_ledger_start_utc"]>t["entry_utc"] or t["opposite_ledger_end_utc"]<t["observation_cutoff_utc"]:
            issues.append("INCOMPLETE_OPPOSITE_LEDGER_WINDOW")
        first=r["opposite_ledger_first_utc"].strip()
        if not first: issues.append("MISSING_OPPOSITE_LEDGER_RESULT")
        elif first!="NONE":
            f=dt(first)
            if f<=t["entry_utc"]: issues.append("OPPOSITE_KNOWN_BEFORE_ENTRY")
            if f>t["observation_cutoff_utc"]: issues.append("OPPOSITE_EVENT_AFTER_CUTOFF")
            if not t["opposite_ledger_start_utc"]<=f<=t["opposite_ledger_end_utc"]:
                issues.append("OPPOSITE_OUTSIDE_LEDGER")
        closed=status.startswith("CLOSED_")
        if closed:
            if not r["exit_utc"] or not positive(r["exit_price"]):
                issues.append("CLOSED_WITHOUT_EXIT_EVIDENCE")
            else:
                x=dt(r["exit_utc"])
                if not t["entry_utc"]<x<=t["observation_cutoff_utc"]: issues.append("INVALID_EXIT_TIME")
            if r["exit_reason"]!=("STOP" if status=="CLOSED_STOP" else "OPPOSITE_CONFIRMED"):
                issues.append("EXIT_REASON_MISMATCH")
            if status=="CLOSED_OPPOSITE" and first=="NONE":
                issues.append("OPPOSITE_EXIT_WITHOUT_EVENT")
            if status=="CLOSED_OPPOSITE" and first not in ("","NONE") and r["exit_utc"]:
                if dt(r["exit_utc"])<=dt(first): issues.append("EXIT_BEFORE_OPPOSITE_AVAILABLE")
            if status=="CLOSED_STOP" and first not in ("","NONE") and r["exit_utc"]:
                if dt(first)<=dt(r["exit_utc"]): issues.append("STOP_ORDER_UNPROVEN")
        else:
            if any(r[k].strip() for k in ("exit_utc","exit_price","exit_reason")):
                issues.append("CENSORED_HAS_FABRICATED_EXIT")
            if status=="OPEN_AT_CUTOFF" and first!="NONE":
                issues.append("OPEN_WITH_KNOWN_OPPOSITE")
        for k in ("quote_coverage","mark_coverage"):
            if r[k]!="COMPLETE": issues.append("UNKNOWN_"+k.upper())
        if status=="OPEN_AT_CUTOFF":
            for k in ("last_bid","last_ask","last_mark"):
                if not positive(r[k]): issues.append("MISSING_MTM_"+k.upper())
            for k in ("last_bid_utc","last_ask_utc","last_mark_utc"):
                if not r[k] or dt(r[k])>t["observation_cutoff_utc"]:
                    issues.append("INVALID_MTM_TIMESTAMP_"+k.upper())
    except (KeyError,ValueError,TypeError,OverflowError) as e:
        issues.append("INVALID_FIELD_"+type(e).__name__)
    return sorted(set(issues))
def run(rows):
    seen=set(); findings=[]
    for r in rows:
        problems=audit(r)
        sid=r.get("signal_id","")
        if not sid or sid in seen: problems.append("DUPLICATE_OR_EMPTY_SIGNAL_ID")
        seen.add(sid)
        findings.append({"signal_id":sid,"status":r.get("status"),"side":r.get("side"),
                         "gate":"BLOCKED" if problems else "MANIFEST_ELIGIBLE_NOT_VERIFIED",
                         "reasons":sorted(set(problems))})
    counts=Counter(r.get("status","MISSING") for r in rows)
    return {"type":"FROZEN_D250_COHORT_MANIFEST_ONLY","rows":len(rows),
            "cohort_size_71":len(rows)==71,"status_counts":dict(counts),
            "blocked":sum(f["reasons"]!=[] for f in findings),
            "findings":findings,
            "warning":"No raw exchange tape verification, PnL, liquidation, or execution authorization"}
def selftest():
    from datetime import timedelta
    base=datetime(2026,7,12,tzinfo=timezone.utc)
    fmt=lambda t:t.isoformat()
    row={k:"" for k in REQUIRED}
    row.update(signal_id="a",side="LONG",local_kind="LOW",local_extreme_utc=fmt(base),
      h1_confirmed_utc=fmt(base+timedelta(hours=3)),d250_signal_utc=fmt(base+timedelta(minutes=250)),
      feature_available_utc=fmt(base+timedelta(minutes=250)),
      entry_utc=fmt(base+timedelta(minutes=251)),observation_cutoff_utc=fmt(base+timedelta(hours=10)),
      rev_atr="2.2",trade_ratio5="0.3",flow15="0.2",entry_price="100",
      source_sha256="a"*64,status="OPEN_AT_CUTOFF",opposite_ledger_first_utc="NONE",
      opposite_ledger_start_utc=fmt(base+timedelta(minutes=250)),
      opposite_ledger_end_utc=fmt(base+timedelta(hours=10)),
      same_side_ledger_coverage="COMPLETE",opposite_ledger_coverage="COMPLETE",
      quote_coverage="COMPLETE",mark_coverage="COMPLETE",last_bid="102",
      last_ask="102.1",last_mark="102.05")
    for k in ("rev_atr_asof_utc","trade_ratio5_asof_utc","flow15_asof_utc"):
        row[k]=fmt(base+timedelta(minutes=250))
    for k in ("last_bid_utc","last_ask_utc","last_mark_utc"):
        row[k]=fmt(base+timedelta(hours=10))
    assert not audit(row),audit(row)
    r=dict(row,exit_utc=fmt(base+timedelta(hours=10)))
    assert "CENSORED_HAS_FABRICATED_EXIT" in audit(r)
    r=dict(row,feature_available_utc=fmt(base+timedelta(hours=5)))
    assert "ENTRY_BEFORE_CAUSAL_AVAILABILITY" in audit(r)
    r=dict(row,side="SHORT")
    assert "SIDE_LOCAL_MISMATCH" in audit(r)
    r=dict(row,status="UNKNOWN_DATA")
    assert "UNKNOWN_DATA_NOT_EXECUTION_ELIGIBLE" in audit(r)
    r=dict(row,feature_available_utc=fmt(base+timedelta(minutes=251)))
    assert "FEATURE_NOT_AVAILABLE_AT_SIGNAL" in audit(r)
    r=dict(row,opposite_ledger_first_utc=fmt(base+timedelta(hours=11)))
    assert "OPPOSITE_EVENT_AFTER_CUTOFF" in audit(r)
    print("PASS: 7 deterministic schema/causality checks (synthetic only)")
def main():
    p=argparse.ArgumentParser();p.add_argument("csv",nargs="?");p.add_argument("--out");p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test: selftest();return
    if not a.csv or not a.out: p.error("CSV and --out required")
    with open(a.csv,newline="",encoding="utf-8") as f:
        rd=csv.DictReader(f); missing=REQUIRED-set(rd.fieldnames or [])
        if missing: p.error("Missing columns: "+",".join(sorted(missing)))
        result=run(list(rd))
    with open(a.out,"w",encoding="utf-8") as f:json.dump(result,f,indent=2)
    print(json.dumps({"rows":result["rows"],"blocked":result["blocked"],"cohort_size_71":result["cohort_size_71"]}))
if __name__=="__main__":main()
