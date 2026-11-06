from __future__ import annotations

"""GPT-6 Astra reasoning overlay for HYPE Quant research.

Research/PAPER only. No Bybit private endpoints or live order placement.
The monitor exposes concise thesis/evidence/invalidation summaries, never private
chain-of-thought.
"""
from collections import deque
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import json, math, os, time
import requests

from .learner import clean_features

DECISIONS=("WAIT","HOLD","ENTER_LONG","ENTER_SHORT","EXIT")
HORIZONS=(60,180,300)
US_TZ=ZoneInfo("America/New_York")

def us_market_session(ts_ms:int)->str:
    dt=datetime.fromtimestamp(int(ts_ms)/1000.0,tz=timezone.utc).astimezone(US_TZ)
    if dt.weekday()>=5:return "US_WEEKEND"
    t=dt.time().replace(tzinfo=None)
    if dtime(4,0)<=t<dtime(9,30):return "US_PREMARKET"
    if dtime(9,30)<=t<dtime(16,0):return "US_CASH"
    if dtime(16,0)<=t<dtime(20,0):return "US_AFTER_HOURS"
    return "US_OVERNIGHT"

def _json_object(text):
    text=str(text or "").strip()
    try:
        obj=json.loads(text)
        if isinstance(obj,dict):return obj
    except Exception:pass
    a=text.find("{");b=text.rfind("}")
    if a>=0 and b>a:
        obj=json.loads(text[a:b+1])
        if isinstance(obj,dict):return obj
    raise ValueError("cortex_response_has_no_json_object")

DECISION_SCHEMA={
    "type":"object","additionalProperties":False,
    "properties":{
        "decision":{"type":"string","enum":list(DECISIONS)},
        "confidence":{"type":"number","minimum":0,"maximum":1},
        "market_regime":{"type":"string"},
        "thesis":{"type":"string"},
        "evidence_for":{"type":"array","items":{"type":"string"},"maxItems":5},
        "evidence_against":{"type":"array","items":{"type":"string"},"maxItems":5},
        "invalidation":{"type":"string"},
        "expected_path_60s":{"type":"string"},
        "expected_path_180s":{"type":"string"},
        "expected_path_300s":{"type":"string"},
        "risk_level":{"type":"string","enum":["LOW","MEDIUM","HIGH","EXTREME"]},
        "leverage":{"type":"integer","minimum":1,"maximum":25},
        "margin_fraction":{"type":"number","minimum":0.02,"maximum":0.20},
        "learning_note":{"type":"string"},
    },
    "required":["decision","confidence","market_regime","thesis","evidence_for",
                "evidence_against","invalidation","expected_path_60s",
                "expected_path_180s","expected_path_300s","risk_level",
                "leverage","margin_fraction","learning_note"],
}

def finite(v:Any)->bool:
    return isinstance(v,(int,float)) and math.isfinite(v)

def clip(v,lo,hi):
    return max(lo,min(hi,float(v)))

def _output_text(payload):
    for item in payload.get("output") or []:
        if not isinstance(item,dict) or item.get("type")!="message": continue
        for part in item.get("content") or []:
            if isinstance(part,dict) and part.get("type")=="output_text":
                text=part.get("text")
                if isinstance(text,str) and text.strip(): return text
    return ""

class AstraCortex:
    VERSION="cortex-20b-v2"

    def __init__(self,checkpoint_dir:Path):
        self.checkpoint_dir=Path(checkpoint_dir)
        self.state_path=self.checkpoint_dir/"astra_cortex_state.json"
        self.backend=os.getenv("CORTEX_BACKEND","local_llama").strip() or "local_llama"
        self.local_url=os.getenv("CORTEX_LOCAL_URL","http://127.0.0.1:8081").strip().rstrip("/")
        self.model=os.getenv("ASTRA_CORTEX_MODEL","gpt-oss-20b-local").strip() or "gpt-oss-20b-local"
        self.reasoning_effort=os.getenv("ASTRA_CORTEX_REASONING_EFFORT","high").strip() or "high"
        self.normal_interval_s=max(120.0,float(os.getenv("ASTRA_CORTEX_INTERVAL_SECONDS","300")))
        self.urgent_interval_s=max(30.0,float(os.getenv("ASTRA_CORTEX_URGENT_INTERVAL_SECONDS","60")))
        self.timeout_s=max(30.0,float(os.getenv("ASTRA_CORTEX_TIMEOUT_SECONDS","150")))
        self.enabled=os.getenv("ASTRA_CORTEX_ENABLED","1").strip().lower() not in ("0","false","no")
        self.api_key=os.getenv("OPENAI_API_KEY","").strip()
        self.training_target_matured=max(120,int(os.getenv("CORTEX_24H_TARGET_MATURED","600")))
        self.training_target_decisions=max(60,int(os.getenv("CORTEX_24H_TARGET_DECISIONS","240")))
        self.sprint_hours=max(1.0,float(os.getenv("CORTEX_SPRINT_HOURS","24")))
        self.sprint_started_ts_ms=None
        self.last_call_ts_ms=None; self.last_decision=None
        self.last_base_action=None; self.last_local_key=None; self.last_error=None
        self.calls=0; self.api_errors=0; self.matured_episodes=0
        self.directional_checks=0; self.directional_correct=0
        self.net_returns=deque(maxlen=500)
        self.episodes=[]; self.pending=[]; self.last_critique=None
        self.usage={"input_tokens":0,"output_tokens":0,"total_tokens":0}
        self._load()
        if self.sprint_started_ts_ms is None:self.sprint_started_ts_ms=int(time.time()*1000)

    @property
    def available(self):
        if not self.enabled:return False
        return True if self.backend=="local_llama" else bool(self.api_key)

    def _load(self):
        if not self.state_path.exists(): return
        try:
            obj=json.loads(self.state_path.read_text(encoding="utf-8"))
            self.sprint_started_ts_ms=obj.get("sprint_started_ts_ms")
            self.last_call_ts_ms=obj.get("last_call_ts_ms")
            self.last_decision=obj.get("last_decision")
            self.last_base_action=obj.get("last_base_action")
            self.last_local_key=obj.get("last_local_key")
            self.calls=int(obj.get("calls",0)); self.api_errors=int(obj.get("api_errors",0))
            self.matured_episodes=int(obj.get("matured_episodes",0))
            self.directional_checks=int(obj.get("directional_checks",0))
            self.directional_correct=int(obj.get("directional_correct",0))
            self.episodes=list(obj.get("episodes") or [])[-200:]
            self.pending=list(obj.get("pending") or [])[-200:]
            self.last_critique=obj.get("last_critique")
            self.usage.update(obj.get("usage") or {})
            for x in obj.get("net_returns") or []:
                if finite(x): self.net_returns.append(float(x))
        except Exception as exc:
            self.last_error=f"state_load:{type(exc).__name__}"

    def save(self):
        self.checkpoint_dir.mkdir(parents=True,exist_ok=True)
        obj={"version":self.VERSION,"backend":self.backend,"sprint_started_ts_ms":self.sprint_started_ts_ms,
             "last_call_ts_ms":self.last_call_ts_ms,
             "last_decision":self.last_decision,"last_base_action":self.last_base_action,
             "last_local_key":self.last_local_key,"calls":self.calls,
             "api_errors":self.api_errors,"matured_episodes":self.matured_episodes,
             "directional_checks":self.directional_checks,
             "directional_correct":self.directional_correct,
             "episodes":self.episodes[-200:],"pending":self.pending[-200:],
             "last_critique":self.last_critique,"usage":self.usage,
             "net_returns":list(self.net_returns)}
        tmp=self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
        tmp.replace(self.state_path)

    def _local_key(self,base_report):
        local=base_report.get("active_local")
        if not isinstance(local,dict): return None
        return f"{local.get('side')}:{local.get('price')}:{local.get('stage')}"

    def _urgent(self,features,base_decision,base_report):
        q=base_decision.get("quant") or {}
        base_action=str(q.get("action") or "FLAT")
        local_key=self._local_key(base_report)
        events=base_decision.get("events") or []
        names={str(e.get("event")) for e in events if isinstance(e,dict)}
        disagreement=float(features.get("agent_disagreement",0.0) or 0.0)
        adversary=float(features.get("agent_adversary_risk",0.0) or 0.0)
        return (base_action!=self.last_base_action or local_key!=self.last_local_key
                or bool(names & {"ENTER","EXIT","REENTER","STRICT_H1_LOCAL_SYNC"})
                or disagreement>=0.35 or adversary>=0.55)

    def due(self,ts_ms,features,base_decision,base_report):
        if not self.available: return False
        if self.last_call_ts_ms is None: return True
        elapsed=max(0.0,(ts_ms-self.last_call_ts_ms)/1000.0)
        interval=self.urgent_interval_s if self._urgent(features,base_decision,base_report) else self.normal_interval_s
        return elapsed>=interval

    def _session_stats(self):
        buckets={}
        for e in self.episodes:
            key=str(e.get("us_session") or "UNKNOWN")
            b=buckets.setdefault(key,{"matured":0,"directional_checks":0,"directional_correct":0,
                                      "net_sum":0.0,"abs_return_sum":0.0,"range_sum":0.0})
            b["matured"]+=1
            b["abs_return_sum"]+=abs(float(e.get("future_return") or 0.0))
            b["range_sum"]+=float(e.get("max_up") or 0.0)+float(e.get("max_down") or 0.0)
            if e.get("success") is not None:
                b["directional_checks"]+=1
                b["directional_correct"]+=int(bool(e.get("success")))
                b["net_sum"]+=float(e.get("directional_net") or 0.0)
        out={}
        for k,b in buckets.items():
            n=max(1,b["matured"]);d=b["directional_checks"]
            out[k]={"matured":b["matured"],"directional_checks":d,
                    "directional_accuracy":b["directional_correct"]/d if d else None,
                    "mean_directional_net":b["net_sum"]/d if d else None,
                    "mean_abs_return":b["abs_return_sum"]/n,
                    "mean_path_range":b["range_sum"]/n}
        return out

    def _training_progress(self,now_ms=None):
        now_ms=int(now_ms or time.time()*1000)
        elapsed_h=max(0.0,(now_ms-int(self.sprint_started_ts_ms or now_ms))/3_600_000.0)
        elapsed_pct=min(100.0,100.0*elapsed_h/self.sprint_hours)
        evidence_pct=min(100.0,100.0*self.matured_episodes/self.training_target_matured)
        decision_pct=min(100.0,100.0*self.calls/self.training_target_decisions)
        overall=min(100.0,.35*elapsed_pct+.45*evidence_pct+.20*decision_pct)
        if elapsed_pct>=100 and evidence_pct>=100:state="24H_EVIDENCE_READY"
        elif overall>=60:state="VALIDATING"
        elif overall>=10:state="LEARNING"
        else:state="WARMING_UP"
        return {"overall_percent":overall,"elapsed_percent":elapsed_pct,
                "evidence_percent":evidence_pct,"decision_percent":decision_pct,
                "elapsed_hours":elapsed_h,"target_hours":self.sprint_hours,
                "matured_episodes":self.matured_episodes,
                "target_matured_episodes":self.training_target_matured,
                "decisions":self.calls,"target_decisions":self.training_target_decisions,
                "status":state,
                "meaning":"24h evidence maturity; not guaranteed accuracy or profitability"}

    def _advance_pending(self,ts_ms,price):
        keep=[]
        for p in self.pending:
            p["high"]=max(float(p.get("high",price)),price)
            p["low"]=min(float(p.get("low",price)),price)
            elapsed=(ts_ms-int(p["ts_ms"]))/1000.0
            done=set(int(x) for x in p.get("done") or [])
            for h in HORIZONS:
                if h in done or elapsed<h: continue
                ret=price/float(p["price"])-1.0
                decision=str(p.get("decision") or "WAIT")
                direction=1 if decision=="ENTER_LONG" else -1 if decision=="ENTER_SHORT" else 0
                net=direction*ret-float(p.get("cost_floor",0.0)) if direction else 0.0
                success=None
                if direction:
                    success=net>0
                    self.directional_checks+=1
                    self.directional_correct+=int(success)
                    self.net_returns.append(net)
                episode={"decision_ts_ms":p["ts_ms"],"mature_ts_ms":ts_ms,"horizon_s":h,
                         "us_session":p.get("us_session"),"decision":decision,"confidence":p.get("confidence"),
                         "entry_price":p["price"],"close_price":price,"future_return":ret,
                         "max_up":float(p["high"])/float(p["price"])-1.0,
                         "max_down":1.0-float(p["low"])/float(p["price"]),
                         "directional_net":net if direction else None,
                         "success":success,"thesis":p.get("thesis")}
                self.episodes.append(episode); self.episodes=self.episodes[-200:]
                self.matured_episodes+=1
                self.last_critique={"decision":decision,"horizon_s":h,"success":success,
                    "us_session":p.get("us_session"),"future_return":ret,
                    "lesson":("Directional thesis was confirmed after modeled cost." if success is True
                              else "Directional thesis failed after modeled cost; reduce weight on this state." if success is False
                              else "Non-directional decision matured; retain as context, not an accuracy check.")}
                done.add(h)
            p["done"]=sorted(done)
            if len(done)<len(HORIZONS): keep.append(p)
        self.pending=keep

    def _memory_for_prompt(self):
        return [{"horizon_s":e.get("horizon_s"),"us_session":e.get("us_session"),
                 "decision":e.get("decision"),
                 "confidence":e.get("confidence"),"future_return":e.get("future_return"),
                 "directional_net":e.get("directional_net"),"success":e.get("success")}
                for e in self.episodes[-18:]]

    def _prompt(self,state):
        system=(f"Reasoning: {self.reasoning_effort}. "
                "You are CORTEX 20B, an independent reasoning layer in a research-only HYPEUSDT system. "
                "Use only the supplied causal state; future target/evaluation labels are excluded. "
                "Compare LONG, SHORT, HOLD, EXIT and WAIT. Explicitly test contradictions between "
                "H1 local structure, executed flow, price response, L50 book, OI, liquidations and Quant. "
                "Pay special attention to US premarket, US cash and US after-hours behavior, "
                "but never assume a session is profitable by itself. Return ONLY compact JSON. "
                "Do not expose private chain-of-thought; use short audit summaries.")
        shape={"decision":"WAIT","confidence":0.0,"market_regime":"string","thesis":"short audit thesis",
               "evidence_for":["feature/value"],"evidence_against":["feature/value"],"invalidation":"condition",
               "expected_path_60s":"string","expected_path_180s":"string","expected_path_300s":"string",
               "risk_level":"LOW|MEDIUM|HIGH|EXTREME","leverage":1,"margin_fraction":0.02,
               "learning_note":"short hypothesis/lesson"}
        user=("Emit one JSON object matching this shape:\n"+json.dumps(shape,separators=(",",":"))+
              "\nSTATE_JSON\n"+json.dumps(state,ensure_ascii=False,separators=(",",":")))
        return system,user

    def _normalize_decision(self,d):
        out=dict(d or {})
        action=str(out.get("decision") or "WAIT").upper()
        out["decision"]=action if action in DECISIONS else "WAIT"
        out["confidence"]=clip(out.get("confidence",0.0) or 0.0,0,1)
        risk=str(out.get("risk_level") or "HIGH").upper()
        out["risk_level"]=risk if risk in ("LOW","MEDIUM","HIGH","EXTREME") else "HIGH"
        out["leverage"]=int(clip(out.get("leverage",1) or 1,1,25))
        out["margin_fraction"]=clip(out.get("margin_fraction",0.02) or 0.02,0.02,0.20)
        for k in ("market_regime","thesis","invalidation","expected_path_60s",
                  "expected_path_180s","expected_path_300s","learning_note"):
            out[k]=str(out.get(k) or "")[:700]
        for k in ("evidence_for","evidence_against"):
            v=out.get(k)
            if not isinstance(v,list):v=[]
            out[k]=[str(x)[:260] for x in v[:5]]
        return out

    def _request_local(self,state):
        system,user=self._prompt(state)
        r=requests.post(self.local_url+"/v1/chat/completions",
            json={"model":self.model,
                  "messages":[{"role":"system","content":system},{"role":"user","content":user}],
                  "temperature":0.15,"max_tokens":520,"response_format":{"type":"json_object"}},
            timeout=self.timeout_s)
        r.raise_for_status()
        obj=r.json();choices=obj.get("choices") or []
        if not choices:raise RuntimeError("local_cortex_no_choices")
        msg=(choices[0] or {}).get("message") or {}
        decision=self._normalize_decision(_json_object(msg.get("content") or ""))
        usage=obj.get("usage") or {}
        self.usage["input_tokens"]+=int(usage.get("prompt_tokens") or 0)
        self.usage["output_tokens"]+=int(usage.get("completion_tokens") or 0)
        self.usage["total_tokens"]+=int(usage.get("total_tokens") or 0)
        return decision

    def _request_openai(self,state):
        system,user=self._prompt(state)
        payload={"model":self.model,"reasoning":{"effort":self.reasoning_effort},
                 "max_output_tokens":1200,
                 "input":[{"role":"system","content":system},{"role":"user","content":user}],
                 "text":{"format":{"type":"json_schema","name":"cortex_market_decision",
                                   "strict":True,"schema":DECISION_SCHEMA}}}
        r=requests.post("https://api.openai.com/v1/responses",
            headers={"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"},
            json=payload,timeout=self.timeout_s)
        r.raise_for_status()
        obj=r.json();text=_output_text(obj)
        if not text:raise RuntimeError("cortex_response_has_no_output_text")
        return self._normalize_decision(_json_object(text))

    def _request(self,state):
        return self._request_local(state) if self.backend=="local_llama" else self._request_openai(state)

    def observe(self,ts_ms,price,features,base_decision,base_report,cost_floor):
        self._advance_pending(ts_ms,price)
        if not self.due(ts_ms,features,base_decision,base_report):
            return {"new_decision":False,"decision":self.last_decision,"status":self.status(ts_ms)}
        causal=clean_features(features); q=base_decision.get("quant") or {}
        session=us_market_session(ts_ms)
        state={"ts_ms":int(ts_ms),"price":float(price),"us_market_session":session,
               "causal_features":causal,
               "quant":q,"caterpillar_events":(base_decision.get("events") or [])[-12:],
               "base_paper":base_decision.get("paper") or {},
               "active_local":base_report.get("active_local"),
               "policy_state":base_report.get("policy_state"),
               "training_progress":base_report.get("training_progress"),
               "episodic_memory":self._memory_for_prompt(),
               "cortex_us_session_stats":self._session_stats(),
               "cortex_24h_progress":self._training_progress(ts_ms),
               "constraints":{"research_only":True,"real_orders":False,"max_leverage":25,
                              "max_margin_fraction":0.20,"modeled_round_trip_cost":float(cost_floor)}}
        try:
            decision=self._request(state)
            decision.update({"ts_ms":int(ts_ms),"price":float(price),"model":self.model,
                             "backend":self.backend,"reasoning_effort":self.reasoning_effort,
                             "us_market_session":session,
                             "base_quant_action":q.get("action"),
                             "base_quant_score":q.get("score"),
                             "audit_note":"Concise rationale summary; not hidden chain-of-thought."})
            self.last_decision=decision; self.last_call_ts_ms=int(ts_ms)
            self.last_base_action=str(q.get("action") or "FLAT")
            self.last_local_key=self._local_key(base_report); self.last_error=None; self.calls+=1
            self.pending.append({"ts_ms":int(ts_ms),"price":float(price),"high":float(price),"low":float(price),
                                 "us_session":session,
                                 "decision":decision.get("decision"),"confidence":decision.get("confidence"),
                                 "thesis":decision.get("thesis"),"cost_floor":float(cost_floor),"done":[]})
            self.pending=self.pending[-200:]; self.save()
            return {"new_decision":True,"decision":decision,"status":self.status(ts_ms)}
        except Exception as exc:
            self.api_errors+=1
            self.last_error=f"{type(exc).__name__}: {str(exc)[:240]}"
            self.last_call_ts_ms=int(ts_ms); self.save()
            return {"new_decision":False,"decision":self.last_decision,"status":self.status(ts_ms)}

    def status(self,ts_ms=None):
        now_ms=int(ts_ms or time.time()*1000)
        state=("DISABLED" if not self.enabled
               else "LOCAL_MODEL_DEGRADED" if self.backend=="local_llama" and self.last_error
               else "WAITING_FOR_API_KEY" if self.backend!="local_llama" and not self.api_key
               else "CORTEX_LIVE" if self.last_decision
               else "LOCAL_MODEL_READY" if self.backend=="local_llama" else "READY")
        age=None if self.last_call_ts_ms is None else max(0.0,(now_ms-self.last_call_ts_ms)/1000.0)
        avg=sum(self.net_returns)/len(self.net_returns) if self.net_returns else None
        return {"version":self.VERSION,"state":state,"enabled":self.enabled,
                "backend":self.backend,"api_key_present":bool(self.api_key),"model":self.model,
                "reasoning_effort":self.reasoning_effort,"calls":self.calls,
                "api_errors":self.api_errors,"last_error":self.last_error,
                "last_call_age_seconds":age,"normal_interval_seconds":self.normal_interval_s,
                "urgent_interval_seconds":self.urgent_interval_s,
                "matured_episodes":self.matured_episodes,"memory_episodes":len(self.episodes),
                "pending_episodes":len(self.pending),"directional_checks":self.directional_checks,
                "directional_accuracy":self.directional_correct/self.directional_checks if self.directional_checks else None,
                "mean_directional_net":avg,"current_us_session":us_market_session(now_ms),
                "us_session_stats":self._session_stats(),
                "training_progress":self._training_progress(now_ms),
                "last_decision":self.last_decision,
                "last_critique":self.last_critique,"usage":dict(self.usage),
                "research_only":True,"real_orders":False}

class AstraPaperBook:
    VERSION="astra-paper-v1"
    def __init__(self,checkpoint_dir:Path,cost_floor:float):
        self.path=Path(checkpoint_dir)/"astra_paper_state.json"; self.cost_floor=float(cost_floor)
        self.equity=100.0; self.peak_equity=100.0; self.max_drawdown=0.0
        self.position=None; self.trades=[]; self.decisions_applied=0; self.last_event=None
        self._load()
    def _load(self):
        if not self.path.exists(): return
        try:
            obj=json.loads(self.path.read_text(encoding="utf-8"))
            self.equity=float(obj.get("equity",100.0)); self.peak_equity=float(obj.get("peak_equity",self.equity))
            self.max_drawdown=float(obj.get("max_drawdown",0.0)); self.position=obj.get("position")
            self.trades=list(obj.get("trades") or [])[-500:]
            self.decisions_applied=int(obj.get("decisions_applied",0)); self.last_event=obj.get("last_event")
        except Exception: pass
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        obj={"version":self.VERSION,"equity":self.equity,"peak_equity":self.peak_equity,
             "max_drawdown":self.max_drawdown,"position":self.position,"trades":self.trades[-500:],
             "decisions_applied":self.decisions_applied,"last_event":self.last_event}
        tmp=self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj,ensure_ascii=False,separators=(",",":")),encoding="utf-8"); tmp.replace(self.path)
    def mark(self,ts_ms,price):
        p=self.position
        if p is None: return
        side=int(p["side"]); cur=side*(price/float(p["entry_price"])-1.0)
        p["mark_price"]=float(price); p["current_return"]=cur
        p["mfe"]=max(float(p.get("mfe",0.0)),cur); p["mae"]=min(float(p.get("mae",0.0)),cur)
        p["last_ts_ms"]=int(ts_ms)
        lev=float(p["leverage"]); approx=max(0.0,1.0/lev-0.005)
        if cur<=-max(0.005,0.55*approx): self._close(ts_ms,price,"ASTRA_RISK_GUARD")
    def _close(self,ts_ms,price,reason):
        p=self.position
        if p is None: return
        gross=int(p["side"])*(price/float(p["entry_price"])-1.0); net=gross-self.cost_floor
        pnl=float(p["notional"])*net; before=self.equity; self.equity=max(0.0,self.equity+pnl)
        self.peak_equity=max(self.peak_equity,self.equity)
        self.max_drawdown=max(self.max_drawdown,(self.peak_equity-self.equity)/max(self.peak_equity,1e-9))
        row={"entry_ts_ms":p["entry_ts_ms"],"exit_ts_ms":int(ts_ms),
             "side":"LONG" if int(p["side"])>0 else "SHORT","entry_price":p["entry_price"],
             "exit_price":float(price),"gross_return":gross,"net_return":net,"pnl":pnl,
             "equity_before":before,"equity_after":self.equity,"mfe":p.get("mfe"),"mae":p.get("mae"),
             "leverage":p.get("leverage"),"margin_fraction":p.get("margin_fraction"),"reason":reason}
        self.trades.append(row); self.trades=self.trades[-500:]; self.last_event={"event":"EXIT",**row}; self.position=None
    def _open(self,ts_ms,price,side,leverage,margin_fraction,reason):
        lev=clip(leverage,1,25); frac=clip(margin_fraction,0.02,0.20); margin=self.equity*frac
        self.position={"side":int(side),"entry_ts_ms":int(ts_ms),"entry_price":float(price),
                       "mark_price":float(price),"current_return":0.0,"mfe":0.0,"mae":0.0,
                       "leverage":lev,"margin_fraction":frac,"margin":margin,"notional":margin*lev,"reason":reason}
        self.last_event={"event":"ENTER","side":"LONG" if side>0 else "SHORT","ts_ms":int(ts_ms),
                         "price":float(price),"leverage":lev,"margin_fraction":frac,"equity":self.equity}
    def apply(self,ts_ms,price,decision):
        self.mark(ts_ms,price); action=str(decision.get("decision") or "WAIT"); self.decisions_applied+=1
        if action=="EXIT": self._close(ts_ms,price,"ASTRA_EXIT")
        elif action in ("ENTER_LONG","ENTER_SHORT"):
            side=1 if action=="ENTER_LONG" else -1
            if self.position is not None and int(self.position["side"])!=side: self._close(ts_ms,price,"ASTRA_FLIP")
            if self.position is None:
                self._open(ts_ms,price,side,float(decision.get("leverage") or 1),
                           float(decision.get("margin_fraction") or 0.02),action)
        self.save()
    def report(self):
        wins=sum(float(t.get("pnl") or 0.0)>0 for t in self.trades)
        return {"version":self.VERSION,"equity":self.equity,"return_pct":(self.equity/100.0-1.0)*100.0,
                "peak_equity":self.peak_equity,"max_drawdown_pct":self.max_drawdown*100.0,
                "closed_trades":len(self.trades),"wins":wins,
                "win_rate":wins/len(self.trades) if self.trades else None,
                "decisions_applied":self.decisions_applied,"open_position":self.position,
                "last_event":self.last_event,"research_only":True,"real_orders":False}

def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        book=AstraPaperBook(Path(td),0.001)
        book.apply(1_000,100.0,{"decision":"ENTER_LONG","leverage":2,"margin_fraction":0.1})
        book.mark(61_000,101.0); book.apply(62_000,101.0,{"decision":"EXIT"})
        assert book.report()["closed_trades"]==1 and book.report()["equity"]>100.0
        c=AstraCortex(Path(td)); c.enabled=True; c.api_key=""
        assert c.status(2_000)["state"]=="WAITING_FOR_API_KEY"
