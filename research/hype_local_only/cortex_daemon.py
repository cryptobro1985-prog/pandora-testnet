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

def _rel_trim(rows,n):
    out=[]
    for r in (rows or [])[:n]:
        if not isinstance(r,dict):continue
        out.append({k:r.get(k) for k in ("feature","effect","median","lift","support","a","b")
                    if r.get(k) is not None})
    return out

def compact_memory(memory,side):
    """Keep Cortex prompt comfortably below the 4k llama.cpp context."""
    out={"micro":{},"internal_tactical":{},"h1":{}}
    for stage in (60,180,300):
        key=f"{side}_{stage}s";h=(memory.get("heads") or {}).get(key) or {}
        out["micro"][key]={
            "rate":h.get("baseline_positive_rate"),
            "features":_rel_trim(h.get("top_feature_relationships"),4),
            "pairs":_rel_trim(h.get("top_pair_relationships"),2),
            "n":[h.get("true_examples"),h.get("false_examples")]
        }
        ih=(memory.get("internal_heads") or {}).get(key) or {}
        out["internal_tactical"][key]={
            "rate":ih.get("baseline_positive_rate"),
            "features":_rel_trim(ih.get("top_feature_relationships"),4),
            "pairs":_rel_trim(ih.get("top_pair_relationships"),2),
            "n":[ih.get("true_examples"),ih.get("false_examples")]
        }
    h=(memory.get("h1_heads") or {}).get(side) or {}
    out["h1"][side]={
        "rate":h.get("baseline_positive_rate"),
        "features":_rel_trim(h.get("top_feature_relationships"),6),
        "pairs":_rel_trim(h.get("top_pair_relationships"),3),
        "n":[h.get("true_examples"),h.get("false_examples")]
    }
    return out

def compact_candidate(candidate):
    c=candidate or {};ev=c.get("evidence") or {};rel=c.get("relationship_evidence") or {}
    return {
        "id":c.get("candidate_id"),"side":c.get("side"),"price":c.get("extreme_price"),
        "age_s":c.get("age_s"),"stage":c.get("stage"),"h1_prior":c.get("h1_prior"),
        "probabilities":c.get("probabilities"),
        "internal_probabilities":c.get("internal_probabilities"),
        "internal_accepted":c.get("internal_accepted"),
        "windows":ev.get("windows"),"proposal":ev.get("proposal"),
        "relationship_supports":_rel_trim(rel.get("supports"),5),
        "relationship_contradicts":_rel_trim(rel.get("contradicts"),5),
    }

def discover_model_id(url,preferred,timeout=10):
    """Use the actual model id exposed by llama.cpp; never invent an alias."""
    try:
        r=requests.get(url.rstrip("/")+"/v1/models",timeout=timeout)
        r.raise_for_status()
        ids=[str(x.get("id")) for x in (r.json().get("data") or []) if x.get("id")]
        if preferred in ids:return preferred
        if ids:return ids[0]
    except Exception:
        pass
    return preferred

def call_cortex(url,model,payload,timeout):
    system=(
      "Analyze HYPE Local HIGH/LOW evidence only. No trading decisions. "
      "Use only supplied causal evidence; never invent missing inputs. "
      "Return one JSON object: verdict, confidence, supporting_relationships, "
      "contradicting_relationships, missing_live_evidence, summary. "
      "verdict: FORMING_HIGH|FORMING_LOW|CONFIRMED_HIGH|CONFIRMED_LOW|WAIT."
    )
    actual_model=discover_model_id(url,model)
    base={"model":actual_model,
          "messages":[{"role":"system","content":system},
                      {"role":"user","content":json.dumps(payload,separators=(",",":"),ensure_ascii=False)}],
          "temperature":0.0,"max_tokens":500}
    errors=[]
    for with_json_mode in (True,False):
        req=dict(base)
        if with_json_mode:req["response_format"]={"type":"json_object"}
        r=requests.post(url.rstrip("/")+"/v1/chat/completions",json=req,timeout=timeout)
        if r.status_code>=400:
            body=(r.text or "")[:1200]
            errors.append(f"http={r.status_code} json_mode={with_json_mode} model={actual_model} body={body}")
            if r.status_code==400 and with_json_mode:
                continue
            raise RuntimeError("local_cortex_request_failed: "+" | ".join(errors))
        obj=r.json();msg=((obj.get("choices") or [{}])[0].get("message") or {})
        parsed=json_object(msg.get("content") or msg.get("reasoning_content") or "")
        parsed["_model_id"]=actual_model
        return parsed
    raise RuntimeError("local_cortex_request_failed: "+" | ".join(errors))


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
              "candidate":compact_candidate(candidate),
              "h1_baseline":status.get("h1_baseline"),
              "last_signal":status.get("last_signal"),
              "input_coverage_count":(status.get("feature_contract") or {}).get("seen_input_count"),
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
