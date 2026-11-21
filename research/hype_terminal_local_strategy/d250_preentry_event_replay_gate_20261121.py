#!/usr/bin/env python3
"""Research-only D250 pre-entry event gate. Requires independently supplied UTC local events.
Does not validate exchange fills, price stops, or profitability.
Usage: python d250_preentry_event_replay_gate_20261121.py manifest.csv local_events.json --out audit.json
local_events.json: [{"kind":"LOW"|"HIGH","extreme_utc":"...Z","confirmed_utc":"...Z","event_id":"..."}].
Events must be chronologically complete; absence is not independently provable by this file.
"""
import argparse,csv,json
from datetime import datetime,timezone,timedelta
from collections import Counter

def utc(v):
    t=datetime.fromisoformat(v.replace("Z","+00:00"))
    if t.tzinfo is None: raise ValueError("naive UTC")
    return t.astimezone(timezone.utc)

def check(row,events):
    reasons=[]
    try:
        side=row["side"]; kind=row["local_kind"]
        if (side,kind) not in (("LONG","LOW"),("SHORT","HIGH")): reasons.append("SIDE_MISMATCH")
        extreme=utc(row["local_extreme_utc"]); confirm=utc(row["h1_confirmed_utc"])
        signal=utc(row["d250_signal_utc"]); entry=utc(row["entry_utc"])
        if not extreme<=confirm<=signal<=entry: reasons.append("NONCAUSAL_TIMES")
        if signal<extreme+timedelta(minutes=250): reasons.append("BEFORE_D250")
        if row.get("preentry_event_coverage")!="COMPLETE": reasons.append("EVENT_COVERAGE_UNPROVEN")
        if utc(row["preentry_event_start_utc"])>extreme or utc(row["preentry_event_end_utc"])<entry:
            reasons.append("EVENT_WINDOW_INCOMPLETE")
        matches=[e for e in events if e["kind"]==kind and utc(e["extreme_utc"])==extreme and utc(e["confirmed_utc"])==confirm]
        if len(matches)!=1: reasons.append("ANCHOR_NOT_UNIQUE")
        # An H1 pivot is actionable only after its confirmation; later extrema cannot
        # be excluded merely because their eventual pivot confirmation is in the future.
        for e in events:
            ex=utc(e["extreme_utc"]); co=utc(e["confirmed_utc"])
            if co<ex: reasons.append("BAD_EVENT_CHRONOLOGY")
            if extreme<ex<=signal and e["kind"]==kind: reasons.append("SAME_SIDE_EXTENSION_BEFORE_SIGNAL")
            if extreme<ex<=signal and e["kind"]!=kind and co<=signal: reasons.append("OPPOSITE_CONFIRMED_BEFORE_SIGNAL")
            if extreme<ex<=entry and e["kind"]==kind: reasons.append("SAME_SIDE_EXTENSION_BEFORE_ENTRY")
            if extreme<ex<=entry and e["kind"]!=kind and co<=entry: reasons.append("OPPOSITE_CONFIRMED_BEFORE_ENTRY")
        if not row.get("event_source_sha256","").strip(): reasons.append("MISSING_EVENT_PROVENANCE")
    except (KeyError,ValueError,TypeError,OverflowError) as exc:
        reasons.append("INVALID_INPUT_"+type(exc).__name__)
    return sorted(set(reasons))

def main():
    p=argparse.ArgumentParser();p.add_argument("manifest_csv");p.add_argument("events_json");p.add_argument("--out",required=True);a=p.parse_args()
    with open(a.manifest_csv,encoding="utf-8",newline="") as f: rows=list(csv.DictReader(f))
    with open(a.events_json,encoding="utf-8") as f: events=json.load(f)
    if not isinstance(events,list): raise SystemExit("EVENTS_MUST_BE_LIST")
    findings=[{"trade_id":r.get("trade_id"),"reasons":check(r,events)} for r in rows]
    result={"status":"PREENTRY_MANIFEST_AUDIT_NOT_EXECUTION_REPLAY","count":len(findings),
            "blocked":sum(bool(f["reasons"]) for f in findings),"findings":findings,
            "limitations":["COMPLETE and SHA256 are manifest assertions until independently checked",
            "Confirmed-pivot event lists may omit unconfirmed same-side price extensions; raw M1 extrema must be separately verified",
            "No fills, funding, liquidation, MTM drawdown or performance validated"]}
    with open(a.out,"w",encoding="utf-8") as f:json.dump(result,f,indent=2)
    print(json.dumps({"count":result["count"],"blocked":result["blocked"]}))
if __name__=="__main__":main()
