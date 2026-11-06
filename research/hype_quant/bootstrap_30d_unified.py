from __future__ import annotations
"""Unified HYPE 30D replay: causal agents + Quant + dynamic compound policy.

Research only. No order placement. Historical inputs unavailable in the 30D
archive (L50/OI/liquidation) stay unavailable/neutral; live forward fills them.
"""
import argparse, copy, gzip, json, math, pickle
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .agents import augment_with_agents, ROLES
from .learner import OnlineQuantLearner, load_config

DISCOVERY=int(datetime(2026,10,11,tzinfo=timezone.utc).timestamp()*1000)
TRAIN_END=int(datetime(2026,10,23,tzinfo=timezone.utc).timestamp()*1000)
OOS=int(datetime(2026,10,27,tzinfo=timezone.utc).timestamp()*1000)
END=int(datetime(2026,11,3,tzinfo=timezone.utc).timestamp()*1000)
START_EQUITY=100.0

def load_jsonl_gz(path):
    out=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip(): out.append(json.loads(line))
    return out

def finite(v): return isinstance(v,(int,float)) and math.isfinite(v)
def clamp(v,a,b): return max(a,min(b,v))

def latest_candidate_map(rows):
    by_min={}
    for r in rows:
        ts=int(r["snapshot_ts_ms"])
        minute=ts//60_000
        prev=by_min.get(minute)
        if prev is None or ts>prev["snapshot_ts_ms"]:
            by_min[minute]=r
    return by_min

def historical_states(bars,candidates):
    bars=sorted(bars,key=lambda r:r["bar_end_ms"])
    cand=latest_candidate_map(candidates)
    closes=[]; buys=[]; sells=[]; highs=[]; lows=[]; states=[]
    for i,r in enumerate(bars):
        ts=int(r["bar_end_ms"]); px=float(r["close"])
        closes.append(px);buys.append(float(r.get("buy_notional",0)));sells.append(float(r.get("sell_notional",0)))
        highs.append(float(r["high"]));lows.append(float(r["low"]))
        x={
            "last_price":px,"log_last_price":math.log(px),
            "m1_close_return_1bar":(px/closes[-2]-1) if len(closes)>1 else 0.0,
            "spread_bps":0.0,
            "micro_gap_seconds":0.0,
            "receipt_sequence_gaps":0.0,
            "book_invalidations_raw":0.0,
            "raw_age_ms":0.0,
        }
        for n,sec,name in ((1,60,"m1"),(3,180,"m3"),(5,300,"m5"),(15,900,"m15"),(30,1800,"m30"),(60,3600,"h1")):
            if len(closes)>n:
                ret=px/closes[-n-1]-1
                x[f"ret_{sec}s"]=ret
                if name in ("m3","m5","h1"): x[f"{name}_close_return_1bar"]=ret
            else:
                x[f"ret_{sec}s"]=0.0
        for n,sec in ((1,60),(3,180),(5,300),(15,900),(30,1800)):
            a=max(0,len(buys)-n)
            bn=sum(buys[a:]);sn=sum(sells[a:]);tot=bn+sn
            imb=(bn-sn)/tot if tot else 0.0
            x[f"flow_imbalance_raw_{sec}s"]=imb
            ret=x.get(f"ret_{sec}s",0.0)
            x[f"buy_efficiency_{sec}s"]=max(ret,0.0)/(bn+1e-12)
            x[f"sell_efficiency_{sec}s"]=max(-ret,0.0)/(sn+1e-12)
            x[f"trade_buy_notional_{sec}s"]=bn
            x[f"trade_sell_notional_{sec}s"]=sn
        for n,label in ((60,"60m"),(360,"6h"),(1440,"24h")):
            a=max(0,len(closes)-n)
            hi=max(highs[a:]);lo=min(lows[a:]);span=max(hi-lo,1e-12)
            x[f"rolling_{label}_high"]=hi;x[f"rolling_{label}_low"]=lo
            x[f"dist_rolling_{label}_high"]=px/hi-1
            x[f"dist_rolling_{label}_low"]=px/lo-1
            x[f"retracement_from_high_{min(n,900)}s"]=(hi-px)/span
            x[f"retracement_from_low_{min(n,900)}s"]=(px-lo)/span
        # persistence and survival are reconstructed causally from minute closes.
        for n,sec in ((1,60),(5,300),(15,900)):
            a=max(0,len(closes)-n-1); part=closes[a:]
            diffs=[b/a-1 for a,b in zip(part,part[1:]) if a>0]
            if diffs:
                x[f"positive_persistence_{sec}s"]=sum(d>0 for d in diffs)/len(diffs)
                x[f"negative_persistence_{sec}s"]=sum(d<0 for d in diffs)/len(diffs)
            hh=max(part);ll=min(part);span=max(hh-ll,1e-12)
            hi_rev=next((j for j,v in enumerate(reversed(part)) if v==hh),0)
            lo_rev=next((j for j,v in enumerate(reversed(part)) if v==ll),0)
            x[f"survival_since_high_{sec}s"]=float(hi_rev*60)
            x[f"survival_since_low_{sec}s"]=float(lo_rev*60)
            x[f"retracement_from_high_{sec}s"]=(hh-px)/span
            x[f"retracement_from_low_{sec}s"]=(px-ll)/span
        c=cand.get(ts//60_000)
        if c and int(c["snapshot_ts_ms"])<=ts:
            x["local116_candidate_side"]=1.0 if c["side"]=="LOW" else -1.0
            x["local116_delay_s"]=float(c["delay_s"])
            for k,v in c.get("features",{}).items():
                if finite(v): x["local116_"+k]=float(v)
            # bridge the richer local snapshot into generic agent inputs.
            side=1.0 if c["side"]=="LOW" else -1.0
            if finite(c["features"].get("retrace_bps")):
                rr=float(c["features"]["retrace_bps"])/10000.0
                if side>0:x["retracement_from_low_900s"]=max(x.get("retracement_from_low_900s",0),rr)
                else:x["retracement_from_high_900s"]=max(x.get("retracement_from_high_900s",0),rr)
            x["local116_snapshot_available"]=1.0
        else:
            x["local116_snapshot_available"]=0.0
        x=augment_with_agents(x)
        states.append((ts,px,x,r))
    return states

def model_action(learner,x):
    models=learner.champion if learner.champion_ready else learner.challenger
    preds={h:models[h].predict(x) for h in learner.horizons}
    return learner.choose_action(x,preds)

def close_position(pos,px,equity,cost,reason,ts):
    price_ret=pos["side"]*(px/pos["entry"]-1)
    pnl=pos["notional"]*price_ret-pos["notional"]*cost
    before=equity
    equity+=pnl
    return equity,{
        "entry_ts":pos["entry_ts"],"exit_ts":ts,"side":"LONG" if pos["side"]>0 else "SHORT",
        "entry":pos["entry"],"exit":px,"leverage":pos["leverage"],"margin_fraction":pos["margin_fraction"],
        "notional":pos["notional"],"price_return":price_ret,"pnl":pnl,
        "equity_before":before,"equity_after":equity,"reason":reason,
        "mfe_price_return":pos["best_ret"],"mae_price_return":pos["worst_ret"],
    }

def simulate(learner,states,start,end,profile):
    cfg=learner.config
    old=copy.deepcopy(cfg)
    cfg["risk"]["min_confidence_to_act"]=profile["min_conf"]
    cfg["risk"]["drawdown_penalty"]=profile["drawdown_penalty"]
    cfg["action_space"]["leverage"]=profile["leverage"]
    cfg["action_space"]["margin_fraction"]=profile["margin_fraction"]
    equity=START_EQUITY;peak=equity;maxdd=0.0;pos=None;trades=[];liqs=0
    cost=learner.cost_floor
    for ts,px,x,bar in states:
        if not start<=ts<end: continue
        d=model_action(learner,x)
        if pos is not None:
            side_ret=pos["side"]*(px/pos["entry"]-1)
            pos["best_ret"]=max(pos["best_ret"],side_ret)
            pos["worst_ret"]=min(pos["worst_ret"],side_ret)
            lev=pos["leverage"];liq_dist=max(0.0,1.0/lev-0.005)
            adverse_intrabar=(pos["entry"]-float(bar["low"]))/pos["entry"] if pos["side"]>0 else (float(bar["high"])-pos["entry"])/pos["entry"]
            if adverse_intrabar>=liq_dist:
                # conservative isolated-margin liquidation approximation
                loss=pos["margin"]+pos["notional"]*cost
                before=equity;equity=max(0.0,equity-loss);liqs+=1
                trades.append({"entry_ts":pos["entry_ts"],"exit_ts":ts,"side":"LONG" if pos["side"]>0 else "SHORT",
                               "entry":pos["entry"],"exit":px,"leverage":lev,"margin_fraction":pos["margin_fraction"],
                               "notional":pos["notional"],"pnl":equity-before,"equity_before":before,"equity_after":equity,
                               "reason":"simulated_liquidation","mfe_price_return":pos["best_ret"],"mae_price_return":-adverse_intrabar})
                pos=None
            else:
                same=(d.get("action")=="LONG" and pos["side"]>0) or (d.get("action")=="SHORT" and pos["side"]<0)
                opposite=(d.get("action")=="LONG" and pos["side"]<0) or (d.get("action")=="SHORT" and pos["side"]>0)
                adv=float(d.get("expected_adverse",0.0) or 0.0)
                giveback=max(0.0,pos["best_ret"]-side_ret)
                risk_guard=adverse_intrabar>=liq_dist*0.55 and not same
                edge_lost=(d.get("action")=="FLAT" and pos["age"]>=2)
                dynamic_mfe=(pos["best_ret"]>0 and giveback>max(adv,1e-6) and not same)
                if opposite or risk_guard or edge_lost or dynamic_mfe:
                    reason="model_flip" if opposite else "risk_guard" if risk_guard else "dynamic_mfe" if dynamic_mfe else "edge_lost"
                    equity,t=close_position(pos,px,equity,cost,reason,ts);trades.append(t);pos=None
                else:
                    pos["age"]+=1
        if pos is None and equity>0 and d.get("action") in ("LONG","SHORT") and float(d.get("score",0))>0:
            lev=float(d["leverage"]);frac=float(d["margin_fraction"])
            margin=equity*frac;notional=margin*lev
            pos={"side":1 if d["action"]=="LONG" else -1,"entry":px,"entry_ts":ts,"margin":margin,
                 "notional":notional,"leverage":lev,"margin_fraction":frac,"best_ret":0.0,"worst_ret":0.0,"age":0}
        peak=max(peak,equity);maxdd=max(maxdd,(peak-equity)/peak if peak>0 else 1.0)
        if equity<=0:break
    if pos is not None:
        last=next((z for z in reversed(states) if start<=z[0]<end),None)
        if last:
            equity,t=close_position(pos,last[1],equity,cost,"period_end",last[0]);trades.append(t)
    cfg.clear();cfg.update(old)
    wins=sum(t["pnl"]>0 for t in trades);gp=sum(max(0,t["pnl"]) for t in trades);gl=-sum(min(0,t["pnl"]) for t in trades)
    objective=(-999.0 if equity<=0 else math.log(equity/START_EQUITY))-3.0*maxdd-12.0*liqs
    if len(trades)<5: objective-=2.0
    return {"final":equity,"return_pct":(equity/START_EQUITY-1)*100,"trades":len(trades),"wins":wins,
            "win_rate":wins/len(trades)*100 if trades else 0.0,"max_dd_pct":maxdd*100,
            "profit_factor":gp/gl if gl>0 else None,"liquidations":liqs,"objective":objective,"detail":trades}

def agent_audit(states,start,end):
    rows=[s for s in states if start<=s[0]<end]
    by_ts={ts:i for i,(ts,px,x,b) in enumerate(rows)}
    out={}
    for name in ROLES:
        if name=="adversary":continue
        signed=[];correct=[]
        for i,(ts,px,x,b) in enumerate(rows[:-5]):
            d=x.get(f"agent_{name}_direction");c=x.get(f"agent_{name}_confidence")
            if not finite(d) or not finite(c) or c<=0.2 or abs(d)<0.05:continue
            fut=rows[i+5][1]/px-1
            signed.append((1 if d>0 else -1)*fut)
            correct.append(1 if d*fut>0 else 0)
        out[name]={"n":len(signed),"mean_signed_5m_return":sum(signed)/len(signed) if signed else None,
                   "direction_precision_5m":sum(correct)/len(correct) if correct else None}
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--artifact-root",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--config",type=Path,default=Path("research/hype_quant/config.json"))
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    bars=load_jsonl_gz(args.artifact_root/"compact_1m.jsonl.gz")
    candidates=load_jsonl_gz(args.artifact_root/"candidate_snapshots.jsonl.gz")
    states=historical_states(bars,candidates)
    cfg=load_config(args.config)
    learner=OnlineQuantLearner(copy.deepcopy(cfg))
    full_action_space=copy.deepcopy(learner.config["action_space"])
    # During fitting the action grid does not affect labels or model updates.
    # Keep a tiny grid here; restore the full high-growth grid for policy search.
    learner.config["action_space"]["leverage"]=[1]
    learner.config["action_space"]["margin_fraction"]=[0.02]

    # Discovery/pretrain only. Last 4 validation days and final 7 OOS days stay unseen.
    for ts,px,x,b in states:
        if DISCOVERY<=ts<TRAIN_END:
            learner.observe(ts,px,x)
    learner.pending.clear()
    pretrain_report=learner.report()
    learner.config["action_space"]=copy.deepcopy(full_action_space)
    # Avoid re-querying thousands of nearest-neighbor memories for every
    # validation risk profile. Historical selection uses the parametric Quant
    # + causal agents; PatternMemory remains available for live forward learning.
    saved_neighbors=learner.memory.neighbors
    learner.memory.neighbors=10**9

    profiles=[]
    for min_conf in (.57,.62,.67):
      for ddp in (4.0,8.0,12.0):
        profiles.append({"min_conf":min_conf,"drawdown_penalty":ddp,
                         "leverage":[5,8,10,15,20,25],"margin_fraction":[.05,.10,.15,.20]})
    validation=[]
    for p in profiles:
        r=simulate(learner,states,TRAIN_END,OOS,p)
        validation.append({"profile":p,**{k:v for k,v in r.items() if k!="detail"}})
    validation.sort(key=lambda z:(z["liquidations"]==0,z["objective"],z["final"]),reverse=True)
    best=validation[0]["profile"]
    val_full=simulate(learner,states,TRAIN_END,OOS,best)
    oos=simulate(learner,states,OOS,END,best)
    learner.memory.neighbors=saved_neighbors

    # Freeze evidence first; only now absorb validation+OOS into the historical warmstart.
    learner.config["action_space"]["leverage"]=[1]
    learner.config["action_space"]["margin_fraction"]=[0.02]
    for ts,px,x,b in states:
        if TRAIN_END<=ts<END:
            learner.observe(ts,px,x)
    learner.pending.clear()
    learner.config["action_space"]=copy.deepcopy(full_action_space)
    learner.save(args.output/"quant_learner.pkl")

    report={
      "research_only":True,"real_orders":False,"symbol":"HYPEUSDT",
      "source":{"minute_bars":len(bars),"candidate_snapshots":len(candidates),
                "period":["2026-10-04","2026-11-02"],"historical_116_note":"availability-aware; no fabricated historical L50/OI/liquidation"},
      "split":{"discovery_train":["2026-10-11","2026-10-22"],"validation":["2026-10-23","2026-10-26"],"untouched_oos":["2026-10-27","2026-11-02"]},
      "pretrain":pretrain_report,
      "agent_audit":{"train":agent_audit(states,DISCOVERY,TRAIN_END),
                     "validation":agent_audit(states,TRAIN_END,OOS),
                     "oos":agent_audit(states,OOS,END)},
      "policy":{"type":"dynamic Quant+agent state policy; no fixed TP/SL",
                "entry":"Quant LONG/SHORT only when modeled positive edge survives committee/adversary scoring",
                "hold":"same-side edge remains active",
                "exit":["model side flip","edge lost","dynamic MFE giveback relative to predicted adverse","liquidation safety guard"],
                "reentry":"new positive edge after flat",
                "candidate_profiles":validation,"selected_on_validation_only":best},
      "validation":{k:v for k,v in val_full.items() if k!="detail"},
      "oos":{k:v for k,v in oos.items() if k!="detail"},
      "oos_trades":oos["detail"],
      "compound_note":"equity and next margin are recomputed from current equity after every closed trade",
      "objective":"maximize log compound growth subject to strong drawdown/liquidation penalties; extreme return is not treated as proof of robustness",
      "final_historical_warmstart":learner.report(),
    }
    (args.output/"UNIFIED_30D_REPORT.json").write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n")
    (args.output/"UNIFIED_POLICY.json").write_text(json.dumps({"selected_profile":best,"policy":report["policy"]},indent=2,sort_keys=True)+"\n")
    print("HYPE_UNIFIED_30D="+json.dumps({"validation":report["validation"],"oos":report["oos"],
          "selected_profile":best,"agent_oos":report["agent_audit"]["oos"],
          "labels":report["final_historical_warmstart"]["labels"]},separators=(",",":"),sort_keys=True))

if __name__=="__main__":
    main()
