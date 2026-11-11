#!/usr/bin/env python3
"""Ultra Survival V2 trade geometry and stop/MFE audit.

This does NOT fit a new local detector. It replays the frozen
HYPE_LOCAL_ULTRA_SURVIVAL_V2 rules unchanged, then measures what happens AFTER
a signal:
- next-minute-open paper entry;
- MAE before the next reference opposite Local;
- MFE and remaining move;
- stop survival grid;
- signal-to-next-opposite-signal realized move;
- approximate leverage/liq cushion scenarios.

Teacher/next Local is EVALUATION ONLY. No future information enters a signal.
No broker or real orders.
"""
from __future__ import annotations
import argparse,bisect,gzip,json,math,statistics
from pathlib import Path
from research.hype_local_only.replay_ultra_survival_v2 import replay,read_jsonl_gz,load_labels

STOP_GRID_PCT=(0.25,0.35,0.50,0.65,0.80,1.00,1.25,1.50,2.00,2.50,3.00)
LEVERS=(3,5,10,15,20,25)

def q(vals,p):
    if not vals:return None
    z=sorted(float(x) for x in vals)
    if len(z)==1:return z[0]
    pos=(len(z)-1)*p;lo=int(pos);hi=min(lo+1,len(z)-1);w=pos-lo
    return z[lo]*(1-w)+z[hi]*w

def safe_div(a,b):
    return a/b if b else None

def next_open_index(bars,signal_ts):
    starts=[int(x["start_ms"]) for x in bars]
    i=bisect.bisect_left(starts,int(signal_ts))
    while i<len(bars) and int(starts[i])<int(signal_ts):i+=1
    return i if i<len(bars) else None

def path_until(bars,i0,deadline_ms,entry,side):
    sign=1 if side=="LOW" else -1
    mfe=mae=0.;mae_before_050=0.;hit050=False;hit100=False;hit200=False
    max_recoil=0.
    for i in range(i0,len(bars)):
        b=bars[i]
        if int(b["start_ms"])>=int(deadline_ms):break
        if bool(b.get("gap",False)):break
        hi=float(b["high"]);lo=float(b["low"]);cl=float(b["close"])
        favorable=(hi/entry-1) if sign==1 else (1-lo/entry)
        adverse=(1-lo/entry) if sign==1 else (hi/entry-1)
        mfe=max(mfe,favorable,0.);mae=max(mae,adverse,0.)
        if not hit050:mae_before_050=max(mae_before_050,adverse,0.)
        if mfe>=.005:hit050=True
        if mfe>=.010:hit100=True
        if mfe>=.020:hit200=True
        mark=sign*(cl/entry-1)
        max_recoil=max(max_recoil,max(0.,mfe-mark))
    return dict(mfe_pct=100*mfe,mae_pct=100*mae,
                mae_before_050_pct=100*mae_before_050,
                hit_050=hit050,hit_100=hit100,hit_200=hit200,
                max_recoil_pct=100*max_recoil)

def block(compact,labels_path,name):
    bars=read_jsonl_gz(compact)
    labels,_=load_labels(labels_path,bars)
    labels=sorted(labels,key=lambda x:int(x["extreme_interval_start_ms"]))
    score=replay(compact,labels_path)
    rows=[]
    for r in score["episode_rows"]:
        if not r.get("accepted"):continue
        j=int(r["episode"])
        if j<=0 or j>=len(labels)-1:continue
        target=labels[j];nxt=labels[j+1]
        i=next_open_index(bars,int(r["signal_ts_ms"]))
        if i is None:continue
        entry=float(bars[i]["open"])
        if entry<=0:continue
        deadline=int(nxt["extreme_interval_start_ms"])
        p=path_until(bars,i,deadline,entry,r["side"])
        true=bool(r.get("true_first"))
        target_price=float(target["extreme_price"]);next_price=float(nxt["extreme_price"])
        sign=1 if r["side"]=="LOW" else -1
        oracle_return=sign*(next_price/entry-1)
        full_swing=abs(next_price/target_price-1)
        row={
          "block":name,"episode":j,"side":r["side"],"true_first":true,
          "signal_ts_ms":int(r["signal_ts_ms"]),"entry_ts_ms":int(bars[i]["start_ms"]),
          "entry":entry,"signal_mark":float(r["mark_price"]),
          "entry_distance_from_true_local_pct":(
             100*abs(entry/target_price-1) if true else None),
          "oracle_to_next_opposite_local_pct":100*oracle_return,
          "full_teacher_swing_pct":100*full_swing,
          "remaining_teacher_swing_fraction":(
             max(0.,sign*(next_price-entry))/max(abs(next_price-target_price),1e-12)
             if true else None),
          **p
        }
        rows.append(row)
    # Realized signal-to-next-opposite-accepted-signal
    accepted=sorted(rows,key=lambda x:x["entry_ts_ms"])
    for k,r in enumerate(accepted):
        exitrow=next((z for z in accepted[k+1:] if z["side"]!=r["side"]),None)
        if exitrow:
            sign=1 if r["side"]=="LOW" else -1
            r["next_opposite_signal_ts_ms"]=exitrow["entry_ts_ms"]
            r["model_flip_return_pct"]=100*sign*(exitrow["entry"]/r["entry"]-1)
        else:
            r["next_opposite_signal_ts_ms"]=None;r["model_flip_return_pct"]=None
    return score,rows

def summarize(rows):
    true=[r for r in rows if r["true_first"]]
    false=[r for r in rows if not r["true_first"]]
    mae=[r["mae_pct"] for r in true];pre=[r["mae_before_050_pct"] for r in true]
    mfe=[r["mfe_pct"] for r in true];rem=[r["remaining_teacher_swing_fraction"] for r in true]
    dist=[r["entry_distance_from_true_local_pct"] for r in true]
    flips=[r["model_flip_return_pct"] for r in true if r["model_flip_return_pct"] is not None]
    stop={}
    for sp in STOP_GRID_PCT:
        kept=[r for r in true if r["mae_pct"]<sp]
        kept050=[r for r in true if r["mae_before_050_pct"]<sp]
        stop[str(sp)]={
          "true_trade_survival_to_opposite_local":safe_div(len(kept),len(true)),
          "true_trade_survival_until_first_0p5_mfe":safe_div(len(kept050),len(true)),
          "true_trades_stopped_by_full_path_mae":len(true)-len(kept),
          "true_trades_stopped_before_0p5_mfe":len(true)-len(kept050)
        }
    return {
      "accepted":len(rows),"true_first":len(true),"false_first":len(false),
      "precision":safe_div(len(true),len(rows)),
      "entry_distance_pct":{"median":q(dist,.5),"p90":q(dist,.9),"max":max(dist) if dist else None},
      "remaining_teacher_swing_fraction":{"median":q(rem,.5),"p10":q(rem,.1)},
      "mfe_pct":{"median":q(mfe,.5),"p10":q(mfe,.1),"p90":q(mfe,.9)},
      "mae_pct":{"median":q(mae,.5),"p90":q(mae,.9),"p95":q(mae,.95),"p99":q(mae,.99),"max":max(mae) if mae else None},
      "mae_before_first_0p5_mfe_pct":{"median":q(pre,.5),"p90":q(pre,.9),"p95":q(pre,.95),"p99":q(pre,.99),"max":max(pre) if pre else None},
      "hit_rate":{"mfe_0p5":safe_div(sum(r["hit_050"] for r in true),len(true)),
                  "mfe_1p0":safe_div(sum(r["hit_100"] for r in true),len(true)),
                  "mfe_2p0":safe_div(sum(r["hit_200"] for r in true),len(true))},
      "model_opposite_signal_flip_return_pct":{"count":len(flips),"median":q(flips,.5),"p10":q(flips,.1),"p90":q(flips,.9),
          "positive_fraction":safe_div(sum(x>0 for x in flips),len(flips))},
      "stop_grid":stop
    }

def leverage(stop_pct,shock_pct=.75,maintenance=.005):
    # Bounded approximation only. Require liquidation distance >= 2.5*(stop+shock)
    out={}
    total=(stop_pct+shock_pct)/100
    for L in LEVERS:
        liq=max(0.,1/L-maintenance)
        out[str(L)]={
          "approx_liq_distance_pct":100*liq,
          "stop_plus_shock_pct":stop_pct+shock_pct,
          "cushion_multiple":liq/total if total>0 else None,
          "passes_2p5x_cushion":bool(total>0 and liq/total>=2.5)
        }
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--block",action="append",nargs=3,metavar=("NAME","COMPACT","LABELS"),required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    allrows=[];blocks={}
    for name,compact,labels in a.block:
        sc,rr=block(Path(compact),Path(labels),name)
        blocks[name]={"signal_score":sc["evaluation"],"geometry":summarize(rr)}
        allrows.extend(rr)
    agg=summarize(allrows)
    # Data-derived paper stop candidates: protect 95%/99% of TRUE trades before 0.5% MFE.
    pre=[r["mae_before_050_pct"] for r in allrows if r["true_first"]]
    stop95=q(pre,.95);stop99=q(pre,.99)
    result={
      "version":"HYPE-ULTRA-SURVIVAL-V2-ENTRY-EXIT-STOP-GEOMETRY-v1",
      "detector":"FROZEN HYPE_LOCAL_ULTRA_SURVIVAL_V2 unchanged",
      "research_only":True,"real_orders":False,
      "blocks":blocks,"aggregate":agg,
      "paper_stop_candidates_pct":{"p95_mae_before_0p5_mfe":stop95,"p99_mae_before_0p5_mfe":stop99},
      "leverage_cushion_for_p95_stop":leverage(stop95) if stop95 is not None else {},
      "limitations":[
        "Teacher next Local is evaluation-only upper-bound geometry, not runtime knowledge.",
        "May entry detector was frozen and sealed; exit/stop analysis is retrospective.",
        "Signal-to-opposite-signal exits may skip unaccepted intermediate locals.",
        "OHLC does not reproduce exact mark-price liquidation or stop execution.",
        "Bounded leverage cushion cannot guarantee non-liquidation in gaps/outages."
      ]
    }
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print(json.dumps({"aggregate":agg,"stop":result["paper_stop_candidates_pct"],
      "leverage":result["leverage_cushion_for_p95_stop"]},ensure_ascii=False))
if __name__=="__main__":main()
