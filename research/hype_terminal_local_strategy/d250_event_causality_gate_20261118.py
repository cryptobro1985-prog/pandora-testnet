#!/usr/bin/env python3
"""Frozen D250 strict causal evidence preflight; research only, no orders."""
import csv,json,hashlib,argparse
from pathlib import Path
from datetime import datetime,timedelta,timezone
def utc(s):
 t=datetime.fromisoformat(s.replace("Z","+00:00"))
 if t.tzinfo is None or t.utcoffset()!=timedelta(0): raise ValueError("UTC required")
 return t.astimezone(timezone.utc)
def check(r,e,root):
 errors=[]
 try:
  x,c,s,n=[utc(r[k]) for k in ("local_extreme_utc","h1_confirmed_utc","d250_signal_utc","entry_utc")]
  if (r["side"],r["local_kind"]) not in (("LONG","LOW"),("SHORT","HIGH")): errors.append("SIDE_MISMATCH")
  if not x<=c<=s<=n or s-x<timedelta(minutes=250): errors.append("NONCAUSAL_D250")
  for k in ("rev_atr","trade_ratio5","flow15"):
   if utc(r[k+"_asof_utc"])>s: errors.append("FUTURE_"+k)
  if not(float(r["rev_atr"])>2.0840049433824706 and float(r["trade_ratio5"])>0.2727842248141979 and float(r["flow15"])<0.4504731635235635): errors.append("FROZEN_RULE_FAIL")
  if e["trade_id"]!=r["trade_id"]: errors.append("ID_MISMATCH")
  if utc(e["event_scan_start_utc"])>x or utc(e["event_scan_end_utc"])<n or not e.get("scan_includes_both_endpoints"): errors.append("SCAN_INCOMPLETE")
  if e.get("same_side_new_extreme_utc") and x<utc(e["same_side_new_extreme_utc"])<=n: errors.append("SAME_SIDE_INVALIDATED")
  if e.get("opposite_confirmed_utc") and utc(e["opposite_confirmed_utc"])<=n: errors.append("OPPOSITE_ALREADY_CONFIRMED")
  for name in ("m1","public_trades","mark"):
   item=e["sources"][name];p=(root/item["path"]).resolve()
   if not p.is_relative_to(root.resolve()) or not p.is_file(): errors.append("SOURCE_MISSING_"+name);continue
   if hashlib.sha256(p.read_bytes()).hexdigest()!=item["sha256"]: errors.append("HASH_MISMATCH_"+name)
   if utc(item["first_utc"])>x or utc(item["last_utc"])<n or not item.get("continuous"): errors.append("COVERAGE_UNPROVEN_"+name)
  if not e.get("independent_event_extractor_version") or not e.get("raw_tape_validated"): errors.append("PROVENANCE_UNPROVEN")
 except (KeyError,ValueError,TypeError,OverflowError) as exc: errors.append("BAD_EVIDENCE_"+type(exc).__name__)
 return sorted(set(errors))
def main():
 p=argparse.ArgumentParser();p.add_argument("manifest");p.add_argument("evidence");p.add_argument("--root",required=True);p.add_argument("--out",required=True);a=p.parse_args()
 with open(a.manifest,newline="") as f: rows=list(csv.DictReader(f))
 ev={};duplicates=set()
 with open(a.evidence) as f:
  for line in f:
   obj=json.loads(line);key=obj["trade_id"]
   if key in ev:duplicates.add(key)
   ev[key]=obj
 seen=set();results=[]
 for r in rows:
  key=r.get("trade_id","");issues=[]
  if not key or key in seen: issues.append("DUPLICATE_OR_EMPTY_ID")
  seen.add(key)
  if key in duplicates: issues.append("DUPLICATE_EVIDENCE")
  if key not in ev: issues.append("NO_EVENT_EVIDENCE")
  else: issues+=check(r,ev[key],Path(a.root))
  results.append({"trade_id":key,"status":"PRELIMINARY_CAUSAL_PASS" if not issues else "BLOCKED","issues":sorted(set(issues))})
 out={"status":"NOT_EXECUTION_REPLAY","results":results,"limitations":["Evidence provenance/continuity assertions still need independent verification","No fills, PnL, funding, liquidation or MFE computed"]}
 Path(a.out).write_text(json.dumps(out,indent=2));print(json.dumps({"rows":len(rows),"passed":sum(x["status"]=="PRELIMINARY_CAUSAL_PASS" for x in results)}))
if __name__=="__main__":main()
