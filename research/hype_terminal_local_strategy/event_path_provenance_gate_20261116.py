"""Research-only event/path provenance guard. Synthetic checks, not real fills."""
import hashlib
from pathlib import Path

EVENTS={"entry_fill_source":"entry_fill_ts_ms","exit_fill_source":"exit_ts_ms",
        "protective_stop_order_source":"stop_order_accepted_ts_ms",
        "stop_fill_source":"stop_fill_ts_ms"}
PATHS={"mark_path_source","l50_path_source","public_trades_source","event_sequence_source"}

def check(row,root,max_gap_ms=60000):
    entry,exit_=row.get("entry_fill_ts_ms"),row.get("exit_ts_ms")
    if type(entry)!=int or type(exit_)!=int or entry>=exit_: return "INVALID_TRADE_TIME"
    ack=row.get("stop_order_accepted_ts_ms")
    if type(ack)!=int or ack>entry: return "UNPROTECTED_ENTRY_TO_ACK"
    if row.get("exit_reason")=="STOP":
        trigger=row.get("stop_trigger_ts_ms")
        if type(trigger)!=int or not entry<trigger<=exit_: return "INVALID_STOP_TRIGGER"
    fields=PATHS|(set(EVENTS) if row.get("exit_reason")=="STOP" else set(EVENTS)-{"stop_fill_source"})
    evidence=row.get("evidence")
    if not isinstance(evidence,dict): return "MISSING_MANIFEST"
    root=Path(root).resolve()
    for field in sorted(fields):
        record=evidence.get(field)
        if not isinstance(record,dict): return "MISSING_"+field
        rel,digest=record.get("path"),record.get("sha256")
        if not isinstance(rel,str) or not isinstance(digest,str) or len(digest)!=64: return "INVALID_HASH_"+field
        path=(root/rel).resolve()
        if not path.is_relative_to(root) or not path.is_file(): return "UNAVAILABLE_"+field
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest.lower(): return "HASH_MISMATCH_"+field
        a,b=record.get("start_ts_ms"),record.get("end_ts_ms")
        if type(a)!=int or type(b)!=int or a>b: return "INVALID_INTERVAL_"+field
        if field in EVENTS:
            t=row.get(EVENTS[field])
            if type(t)!=int or not a<=t<=b: return "EVENT_TIMESTAMP_MISMATCH_"+field
            if any(not isinstance(record.get(k),str) or not record[k] for k in ("event_id","symbol","order_id")): return "MISSING_EVENT_IDENTITY_"+field
            if record["symbol"]!="HYPEUSDT": return "WRONG_SYMBOL_"+field
        else:
            if a>entry or b<exit_: return "PATH_COVERAGE_"+field
            stamps=record.get("timestamps_ms")
            if not isinstance(stamps,list) or len(stamps)<2 or any(type(t)!=int for t in stamps): return "MISSING_TIMESTAMPS_"+field
            if stamps[0]>entry or stamps[-1]<exit_ or any(y<=x or y-x>max_gap_ms for x,y in zip(stamps,stamps[1:])): return "PATH_GAP_"+field
    return "HASHED_METADATA_ONLY_NOT_EXECUTION_VERIFIED"

def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/"source";p.write_bytes(b"synthetic")
        sha=hashlib.sha256(b"synthetic").hexdigest()
        row=dict(entry_fill_ts_ms=100,exit_ts_ms=200,stop_order_accepted_ts_ms=100,stop_trigger_ts_ms=190,stop_fill_ts_ms=195,exit_reason="STOP")
        evidence={}
        for field,key in EVENTS.items():
            t=row[key]
            evidence[field]=dict(path="source",sha256=sha,start_ts_ms=t,end_ts_ms=t,event_id=field,symbol="HYPEUSDT",order_id="o1")
        for field in PATHS:
            evidence[field]=dict(path="source",sha256=sha,start_ts_ms=90,end_ts_ms=210,timestamps_ms=[90,100,150,200,210])
        row["evidence"]=evidence
        assert check(row,tmp)=="HASHED_METADATA_ONLY_NOT_EXECUTION_VERIFIED"
        row["stop_order_accepted_ts_ms"]=101
        assert check(row,tmp)=="UNPROTECTED_ENTRY_TO_ACK"
        row["stop_order_accepted_ts_ms"]=100
        evidence["entry_fill_source"]["start_ts_ms"]=200
        evidence["entry_fill_source"]["end_ts_ms"]=200
        assert check(row,tmp)=="EVENT_TIMESTAMP_MISMATCH_entry_fill_source"
        evidence["entry_fill_source"]["start_ts_ms"]=100
        evidence["entry_fill_source"]["end_ts_ms"]=100
        evidence["mark_path_source"]["timestamps_ms"]=[90,100,180,200,210]
        assert check(row,tmp,max_gap_ms=60)=="PATH_GAP_mark_path_source"
        evidence["mark_path_source"]["timestamps_ms"]=[90,100,150,200,210]
        evidence["exit_fill_source"]["symbol"]="BTCUSDT"
        assert check(row,tmp)=="WRONG_SYMBOL_exit_fill_source"
    return "PASS 5 synthetic tests"
if __name__=="__main__": print(self_test())
