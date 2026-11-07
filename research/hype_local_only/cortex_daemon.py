#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,time
from pathlib import Path
import requests

def json_object(text):
    text=str(text or "").strip()
    a=text.find("{");b=text.rfind("}")
    if a<0 or b<=a:raise ValueError("no JSON object")
    return json.loads(text[a:b+1])

def compact_memory(memory,side):
    out={"micro":{},"h1":{}}
    for stage in (60,180,300):
        key=f"{side}_{stage}s";h=(memory.get("heads") or {}).get(key) or {}
        out["micro"][key]={
            "baseline_positive_rate":h.get("baseline_positive_rate"),
            "top_feature_relationships":(h.get("top_feature_relationships") or [])[:12],
            "top_pair_relationships":(h.get("top_pair_relationships") or [])[:8],
            "true_examples":h.get("true_examples"),"false_examples":h.get("false_examples")
        }
    h=(memory.get("h1_heads") or {}).get(side) or {}
    out["h1"][side]={
        "baseline_positive_rate":h.get("baseline_positive_rate"),
        "top_feature_relationships":(h.get("top_feature_relationships") or [])[:16],
        "top_pair_relationships":(h.get("top_pair_relationships") or [])[:10],
        "true_examples":h.get("true_examples"),"false_examples":h.get("false_examples")
    }
    return out

def call_cortex(url,model,payload,timeout):
    system=(
      "You are HYPE Local Cortex. Your only task is to analyze whether the current market state "
      "is consistent with a forming Local HIGH or Local LOW. You are not a trading strategy. "
      "Use the supplied 30-day relationship memory, matured live discovery relationships, and current Quant probabilities. "
      "Never invent unavailable inputs. Return strict JSON with keys verdict, confidence, "
      "supporting_relationships, contradicting_relationships, missing_live_evidence, summary. "
      "verdict must be FORMING_HIGH, FORMING_LOW, CONFIRMED_HIGH, CONFIRMED_LOW, or WAIT."
    )
    base={"model":model,"messages":[{"role":"system","content":system},{"role":"user","content":json.dumps(payload,separators=(",",":"))}],
          "temperature":0.05,"max_tokens":1200}
    last=None
    for with_json_mode in (True,False):
        req=dict(base)
        if with_json_mode:
            req["response_format"]={"type":"json_object"}
        r=requests.post(url.rstrip("/")+"/v1/chat/completions",json=req,timeout=timeout)
        if r.status_code==400 and with_json_mode:
            last=RuntimeError("local_cortex_json_mode_unsupported: "+r.text[:300])
            continue
        r.raise_for_status()
        obj=r.json();msg=((obj.get("choices") or [{}])[0].get("message") or {})
        return json_object(msg.get("content") or msg.get("reasoning_content") or "")
    raise last or RuntimeError("local_cortex_request_failed")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--checkpoint-dir",type=Path,required=True)
    ap.add_argument("--minutes",type=int,required=True)
    ap.add_argument("--interval-seconds",type=int,default=300)
    args=ap.parse_args()
    memory=json.loads((args.checkpoint_dir/"LOCAL_RELATIONSHIP_MEMORY.json").read_text())
    status_path=args.checkpoint_dir/"LOCAL_ONLY_STATUS.json"
    live_memory_path=args.checkpoint_dir/"LIVE_DISCOVERY_RELATIONSHIPS.json"
    out=args.checkpoint_dir/"CORTEX_LOCAL_ONLY_STATUS.json"
    url=os.getenv("CORTEX_LOCAL_URL","http://127.0.0.1:8081")
    model=os.getenv("ASTRA_CORTEX_MODEL","gpt-oss-20b-local")
    deadline=time.time()+args.minutes*60;calls=errors=0;last={}
    while time.time()<deadline:
        try:
            status=json.loads(status_path.read_text()) if status_path.exists() else {}
            candidate=status.get("candidate") or {}
            side=candidate.get("side") or status.get("expected_side") or "HIGH"
            if side not in ("LOW","HIGH"):side="HIGH"
            live_memory={}
            if live_memory_path.exists():
                try: live_memory=json.loads(live_memory_path.read_text())
                except Exception: live_memory={}
            payload={
              "historical_relationship_memory":compact_memory(memory,side),
              "live_discovery_relationship_memory":compact_memory(live_memory,side),
              "expected_next_local":status.get("expected_side"),
              "last_teacher_local":status.get("last_teacher_local"),
              "candidate":candidate,
              "h1_baseline":status.get("h1_baseline"),
              "h1_training":status.get("h1_training"),
              "last_signal":status.get("last_signal"),
              "input_coverage":(status.get("feature_contract") or {}).get("seen_input_ids"),
              "missing_inputs":(status.get("feature_contract") or {}).get("missing_seen_input_ids"),
              "discovery_feature_count":status.get("discovery_feature_count"),
              "instruction":"Compare current evidence with the 30-day true-vs-false Local relationships. Do not make trading decisions."
            }
            decision=call_cortex(url,model,payload,180)
            calls+=1
            last={"state":"OK","updated_ts_ms":int(time.time()*1000),"calls":calls,"errors":errors,
                  "decision":decision,"candidate_side":side,"memory_version":memory.get("version")}
        except Exception as exc:
            errors+=1
            # Boot/restart races are expected while llama.cpp is starting. Retry
            # quickly instead of freezing Cortex evidence for the full 5m cadence.
            last={"state":"BOOTING" if "Connection" in type(exc).__name__ or "connection" in repr(exc).lower() else "DEGRADED",
                  "updated_ts_ms":int(time.time()*1000),"calls":calls,"errors":errors,
                  "error":repr(exc)[:500],"decision":last.get("decision")}
        out.write_text(json.dumps(last,indent=2,ensure_ascii=False)+"\n")
        time.sleep(20 if last.get("state")=="BOOTING" else max(30,args.interval_seconds))
    print("LOCAL_CORTEX="+json.dumps(last,separators=(",",":"),ensure_ascii=False))

if __name__=="__main__":main()
