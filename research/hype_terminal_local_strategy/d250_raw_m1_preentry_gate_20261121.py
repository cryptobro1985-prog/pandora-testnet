#!/usr/bin/env python3
"""Fail-closed raw M1 price-extreme audit for frozen D250 trade manifests.
Research only. Not an execution replay or detector. Input M1 CSV must have
utc,high,low,closed_utc; each row is a completed one-minute candle.
Manifest columns: trade_id,side,local_type,local_extreme_utc,local_extreme_price,
h1_confirmed_utc,d250_signal_utc,entry_utc.
Uses only M1 candles CLOSED by the entry timestamp; an intra-minute entry
without tick tape is INDETERMINATE, not PASS.
"""
import argparse,csv,json,math
from datetime import datetime,timezone,timedelta
def dt(x):
    d=datetime.fromisoformat(x.replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError("timezone required")
    return d.astimezone(timezone.utc)
def finite(x):
    v=float(x)
    if not math.isfinite(v) or v<=0: raise ValueError("invalid price")
    return v
def audit(trade,bars):
    reasons=[]
    try:
        side=trade["side"]; assert side in ("LONG","SHORT")
        local_type=trade["local_type"].upper()
        if local_type not in ("LOW","HIGH"): reasons.append("INVALID_LOCAL_TYPE")
        elif (side=="LONG" and local_type!="LOW") or (side=="SHORT" and local_type!="HIGH"):
            reasons.append("LOCAL_SIDE_MISMATCH")
        t0=dt(trade["local_extreme_utc"]); tc=dt(trade["h1_confirmed_utc"])
        ts=dt(trade["d250_signal_utc"]); te=dt(trade["entry_utc"])
        p=finite(trade["local_extreme_price"])
        if not t0<=tc<=ts<=te: reasons.append("NONCAUSAL_ORDER")
        if ts<t0+timedelta(minutes=250): reasons.append("BEFORE_D250")
        # Normalize UTC chronology. Require full closed-minute coverage from anchor minute
        # through the last minute before entry; never use future candle data.
        if te.second or te.microsecond:
            reasons.append("INTRAMINUTE_ENTRY_NEEDS_TICKS")
        anchor_minute=t0.replace(second=0,microsecond=0)
        entry_minute=te.replace(second=0,microsecond=0)
        indexed=[]
        for bar in bars:
            start=dt(bar["utc"])
            if anchor_minute<=start<te:
                indexed.append((start,bar))
        indexed.sort(key=lambda item:item[0])
        expected=anchor_minute
        for start,bar in indexed:
            close=dt(bar["closed_utc"])
            if close!=start+timedelta(minutes=1):
                reasons.append("BAD_BAR_INTERVAL")
            if close>te:
                reasons.append("UNCLOSED_BAR_AT_ENTRY")
            if start!=expected:
                reasons.append("M1_GAP_OR_DUPLICATE")
            expected=start+timedelta(minutes=1)
            hi=finite(bar["high"]);lo=finite(bar["low"])
            if lo>hi: reasons.append("BAD_OHLC")
            extended=(side=="LONG" and lo<p) or (side=="SHORT" and hi>p)
            if extended:
                if start==anchor_minute:
                    # OHLC cannot determine whether the extension preceded or
                    # followed the exact local print. Never classify as PASS.
                    reasons.append("INDETERMINATE_ANCHOR_TICK_ORDER")
                else:
                    reasons.append("LOW_EXTENDED_BEFORE_ENTRY" if side=="LONG" else "HIGH_EXTENDED_BEFORE_ENTRY")
        if expected!=entry_minute:
            reasons.append("M1_GAP_OR_PARTIAL_ENTRY")
        if not indexed:
            reasons.append("NO_M1_COVERAGE")
        # M1 can establish absence of a same-side price extension in fully
        # covered minutes, but cannot prove tick-level fill or stop execution.
        # Even full M1 cannot establish actual fill, exchange mark or liquidity.
    except (KeyError,ValueError,TypeError,AssertionError,OverflowError):
        reasons.append("INVALID_INPUT")
    return sorted(set(reasons))
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("manifest");ap.add_argument("m1_csv");ap.add_argument("--out",required=True)
    a=ap.parse_args()
    with open(a.manifest,newline="",encoding="utf-8") as f: trades=list(csv.DictReader(f))
    with open(a.m1_csv,newline="",encoding="utf-8") as f: bars=list(csv.DictReader(f))
    findings=[{"trade_id":t.get("trade_id"),"reasons":audit(t,bars)} for t in trades]
    output={"status":"RAW_M1_PREENTRY_AUDIT_NOT_EXECUTION_REPLAY",
      "count":len(findings),"blocked_or_indeterminate":sum(bool(x["reasons"]) for x in findings),
      "findings":findings,
      "limitations":["M1 alone cannot verify tick-level intraminute entry or stop fills",
      "Candle completeness/source authenticity requires independent provenance",
      "No inference of profitability, MTM, liquidation, funding, or MFE"]}
    with open(a.out,"w",encoding="utf-8") as f:json.dump(output,f,indent=2)
    print(json.dumps({"count":len(findings),"blocked_or_indeterminate":output["blocked_or_indeterminate"]}))
if __name__=="__main__":main()
