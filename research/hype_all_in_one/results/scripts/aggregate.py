"""Aggregate frozen walk-forward results -> metrics, Pareto, per-Local distances, PROTECT/REVERSE MFE simulation, CSV."""
import json,pickle,csv,math,collections,sys
import numpy as np,torch
from core import *
from train_walkforward import FOLDS,BUDGETS,POLICIES,evaluate,summarize,B as SEGB
DATA_=DATA
import os
OUT_=Path(os.environ.get('OUTDIR',str(DATA)))
import __main__,train_walkforward as _W
__main__.Norm=_W.Norm;__main__.CortexEarly=_W.CortexEarly
TRANSFER=["WF_Jul","WF_Aug","WF_Sep","WF_Oct"];FWD="FINAL_FORWARD"
PRIMARY="B0.4_SAFE_MAX_OOF_CAL";FALLBACKS=["B0.7_SAFE_MAX_OOF_CAL","B1.0_SAFE_MAX_OOF_CAL","B99.0_SAFE_MAX_OOF_CAL"]
PROTECT_CFG="B0.7_CAL_Q995";REVERSE_CFG="B1.0_SAFE_MAX_OOF_CAL"
CFGS=[f"B{b}_{p}" for b in BUDGETS for p in POLICIES]
MSK=3*3600
def iso(ts):return datetime.fromtimestamp(ts,timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
def iso_msk(ts):return datetime.fromtimestamp(ts+MSK,timezone.utc).strftime("%Y-%m-%d %H:%M MSK")
def cfg_parse(c):
    b,p=c.split("_",1);return float(b[1:]),p

def load_all():
    d=pickle.load(open(DATA_/"dataset.pkl","rb"));rows=d["rows"];eps=d["episodes"]
    teach={r["target_label_id"]:r for r in json.load(open(DATA_/"teacher_continuous.json"))}
    F={}
    for f in FOLDS:
        p=OUT_/f"bundle_{f['name']}.pt"
        if p.exists():F[f["name"]]=torch.load(p,weights_only=False)
    return rows,eps,teach,F

def fold_records(rows,eps,F,fname,cfg,seg="test"):
    out=[]
    b,pol=cfg_parse(cfg)
    for side in ("LOW","HIGH"):
        S=F[fname]["sides"][side];idx,sc=S["scores"][seg];th=S["thresholds"][b][pol]
        recs=evaluate(rows,idx,np.array(sc),th,b,eps)
        for r in recs:r["fold"]=fname;r["config"]=cfg;r["threshold"]=th
        out+=recs
    return out

def teacher_records(teach,eids):
    out=[]
    for e in eids:
        t=teach.get(e)
        if t is None:continue
        r={"episode_id":e,"side":t["side"],"accepted":t["accepted"],"true_first":t.get("true_first",False)}
        if t["accepted"] and t.get("true_first"):
            r.update(dist_pct=t["entry_distance_pct"],delay_s=t["entry_delay_s"],captured_mfe_ratio=t["captured_fraction"],remaining_move_pct=t["remaining_move_pct"])
        out.append(r)
    return out

def side_split(recs):
    return {"LOW":summarize([r for r in recs if r["side"]=="LOW"]),"HIGH":summarize([r for r in recs if r["side"]=="HIGH"]),"COMBINED":summarize(recs)}

def regime_of_episode(rows):
    reg={}
    for r in rows:
        if r["y"] and r["kind"]=="T0":
            s=r["features"].get("reg_score");reg[r["episode_id"]]="UNKNOWN" if s is None else ("BULL" if s>.18 else "BEAR" if s<-.18 else "TRANSITION")
    return reg

def pareto(points):
    keep=[]
    for i,a in enumerate(points):
        dom=False
        for j,b in enumerate(points):
            if i==j:continue
            if (b["false_first"]<=a["false_first"] and b["coverage"]>=a["coverage"] and (b["median_dist_pct"] or 99)<=(a["median_dist_pct"] or 99)
                and (b["median_captured_mfe_ratio"] or 0)>=(a["median_captured_mfe_ratio"] or 0) and
                (b["false_first"]<a["false_first"] or b["coverage"]>a["coverage"] or (b["median_dist_pct"] or 99)<(a["median_dist_pct"] or 99) or (b["median_captured_mfe_ratio"] or 0)>(a["median_captured_mfe_ratio"] or 0))):
                dom=True;break
        if not dom:keep.append(a)
    return keep

def oracle_frontier(rows,eps,F,fnames,budget):
    """DIAGNOSTIC ONLY: sweep threshold directly on test scores (not a valid detector) to show achievable limit."""
    res=[]
    allsc=[]
    for fn in fnames:
        for side in ("LOW","HIGH"):
            idx,sc=F[fn]["sides"][side]["scores"]["test"];allsc.append((fn,side,idx,np.array(sc)))
    for q in (0.5,0.8,0.9,0.95,0.98,0.99,0.995,0.998,0.999,0.9995,0.9999,1.0):
        recs=[]
        for fn,side,idx,sc in allsc:
            fsc=[sc[a] for a,i in enumerate(idx) if not rows[i]["y"] and rows[i]["dist_pct"]<=budget]
            th=(np.quantile(fsc,q) if q<1 else max(fsc)+1e-9) if fsc else 1.0
            recs+=evaluate(rows,idx,sc,th,budget,eps)
        s=summarize(recs);s["test_false_quantile"]=q;res.append(s)
    return res

# ---------------- PROTECT / REVERSE simulation ----------------
def member_events(rows,eps,F,fname,cfg,seg="test"):
    b,pol=cfg_parse(cfg);ev=[]
    for side in ("LOW","HIGH"):
        S=F[fname]["sides"][side];idx,sc=S["scores"][seg];th=S["thresholds"][b][pol]
        first={}
        for a,i in enumerate(idx):
            r=rows[i]
            if r["dist_pct"]<=b and sc[a]>=th:
                k=(side,r["member_g"])
                if k not in first or r["t"]<first[k][0]:first[k]=(r["t"],r)
        for (sd,g),(t,r) in first.items():
            ev.append({"t":t,"side":sd,"member_g":g,"member_price":r["member_price"],"entry":r["entry"],"y":r["y"],"src":cfg,"episode_id":r["episode_id"]})
    return ev

def teacher_events(teach,eids):
    ev=[]
    for e in eids:
        t=teach.get(e)
        if t and t["accepted"]:
            ev.append({"t":t["signal_ts_ms"]//1000-T0,"side":t["side"],"member_g":None,"member_price":t["target_price"] if t.get("true_first") else None,
                       "entry":t["entry_price"],"y":int(bool(t.get("true_first"))),"src":"TEACHER_V1","episode_id":e})
    return ev

def simulate(tp,period,rev_events,prot_events,fee_side=0.00055):
    a,b=period
    evs=sorted([dict(e,kind="REV") for e in rev_events]+[dict(e,kind="PROT") for e in prot_events],key=lambda e:(e["t"],0 if e["kind"]=="REV" else 1))
    pos=0;entry=None;stop=None;t_open=None;trades=[];false_prot=0;false_rev=0;n_prot=0;n_rev=0
    def close(t_exit,px,reason):
        nonlocal pos,entry,stop,t_open
        seg_hi=tp.high[t_open:t_exit].max() if t_exit>t_open else px;seg_lo=tp.low[t_open:t_exit].min() if t_exit>t_open else px
        mfe=((seg_hi/entry-1) if pos==1 else (entry/seg_lo-1))*100
        pnl=(px/entry-1)*100*pos
        trades.append({"dir":pos,"open_t":t_open+T0,"close_t":t_exit+T0,"entry":entry,"exit":px,"pnl_pct":pnl,"net_pct":pnl-2*fee_side*100,"mfe_pct":mfe,"giveback_pct":mfe-pnl,"reason":reason})
        pos=0;entry=None;stop=None;t_open=None
    for e in evs:
        t=e["t"]
        if t<a or t>=b:continue
        # check invalidation (lineage reset) between last time and t
        if pos!=0 and stop is not None:
            seg=tp.low[t_open:t] if pos==1 else tp.high[t_open:t]
            hit=np.nonzero(seg<stop)[0] if pos==1 else np.nonzero(seg>stop)[0]
            if len(hit):
                close(t_open+int(hit[0])+1,stop,"FALSE_RESET_invalidation")
        want=1 if e["side"]=="LOW" else -1
        if e["kind"]=="REV":
            if pos!=want:
                n_rev+=1
                if not e["y"]:false_rev+=1
                if pos!=0:close(t,e["entry"],"REVERSE")
                pos=want;entry=e["entry"];t_open=t
                stop=e["member_price"]*(0.9999 if want==1 else 1.0001) if e["member_price"] else None
        else:
            if pos==-want:
                n_prot+=1
                if not e["y"]:false_prot+=1
                close(t,e["entry"],"PROTECT")
    if pos!=0:close(min(b,tp.N)-1,float(tp.closef[min(b,tp.N)-2]),"PERIOD_END")
    return {"trades":trades,"n_trades":len(trades),"gross_pnl_pct_sum":float(sum(x["pnl_pct"] for x in trades)),
            "net_pnl_pct_sum_fee0.11rt":float(sum(x["net_pct"] for x in trades)),
            "mfe_sum_pct":float(sum(x["mfe_pct"] for x in trades)),"giveback_sum_pct":float(sum(x["giveback_pct"] for x in trades)),
            "mfe_preserved_ratio":float(sum(x["pnl_pct"] for x in trades)/max(1e-9,sum(x["mfe_pct"] for x in trades))),
            "protect_exits":n_prot,"false_protective_exits":false_prot,"reversals":n_rev,"false_full_reversals":false_rev,
            "invalidation_exits":sum(x["reason"]=="FALSE_RESET_invalidation" for x in trades)}

def ideal_capture(eps,period):
    a,b=period;E=sorted([e for e in eps if a<=e["tmin_s"]<b],key=lambda e:e["tmin_s"])
    return float(sum(abs(e["next_price"]/e["target_price"]-1)*100 for e in E if e["next_tmin_s"]<b))

if __name__=="__main__":
    rows,eps,teach,F=load_all()
    regmap=regime_of_episode(rows)
    M={"folds":{},"transfer_aggregate":{},"forward":{},"pareto_transfer":[],"oracle_frontier_diagnostic":{},"regime_breakdown":{}}
    per_cfg_transfer={c:[] for c in CFGS}
    for fn in TRANSFER+[FWD]:
        if fn not in F:continue
        M["folds"][fn]={}
        for c in CFGS:
            recs=fold_records(rows,eps,F,fn,c)
            M["folds"][fn][c]=side_split(recs)
            if fn in TRANSFER:per_cfg_transfer[c]+=recs
            if fn==FWD:M["forward"][c]=side_split(recs)
        eids=sorted({r["episode_id"] for r in fold_records(rows,eps,F,fn,PRIMARY)})
        M["folds"][fn]["TEACHER_V1_same_episodes"]=side_split(teacher_records(teach,eids))
        if fn==FWD:M["forward"]["TEACHER_V1_same_episodes"]=M["folds"][fn]["TEACHER_V1_same_episodes"]
    tr_eids=sorted({r["episode_id"] for r in per_cfg_transfer[PRIMARY]})
    M["transfer_aggregate"]={c:side_split(v) for c,v in per_cfg_transfer.items()}
    M["transfer_aggregate"]["TEACHER_V1_same_episodes"]=side_split(teacher_records(teach,tr_eids))
    pts=[]
    for c in CFGS:
        s=M["transfer_aggregate"][c]["COMBINED"];pts.append({"config":c,**s})
    t=M["transfer_aggregate"]["TEACHER_V1_same_episodes"]["COMBINED"];pts.append({"config":"TEACHER_V1",**t})
    for p in pts:
        p["coverage"]=p["coverage"] or 0.0
    M["pareto_transfer_all_points"]=pts
    M["pareto_transfer"]=[p["config"] for p in pareto([p for p in pts if p["accepted"]>0])]
    for bud in (0.4,0.7,1.0):
        M["oracle_frontier_diagnostic"][f"B{bud}"]=oracle_frontier(rows,eps,F,[f for f in TRANSFER if f in F],bud)
    # regime breakdown for primary + fallbacks + teacher
    for c in [PRIMARY]+FALLBACKS:
        recs=per_cfg_transfer[c];out={}
        for g in ("BULL","BEAR","TRANSITION","UNKNOWN"):
            sub=[r for r in recs if regmap.get(r["episode_id"])==g]
            if sub:out[g]=side_split(sub)
        M["regime_breakdown"][c]=out
    tre=teacher_records(teach,tr_eids);out={}
    for g in ("BULL","BEAR","TRANSITION","UNKNOWN"):
        sub=[r for r in tre if regmap.get(r["episode_id"])==g]
        if sub:out[g]=side_split(sub)
    M["regime_breakdown"]["TEACHER_V1"]=out
    # per-Local entry distance table
    epi={e["episode_id"]:e for e in eps}
    first_anchor={}
    for r in rows:
        if r["y"] and r["kind"] in ("A25","A40"):first_anchor[(r["episode_id"],r["kind"])]=r["dist_pct"]
    table=[]
    for fn in TRANSFER+[FWD]:
        if fn not in F:continue
        recs={c:{r["episode_id"]:r for r in fold_records(rows,eps,F,fn,c)} for c in [PRIMARY]+FALLBACKS}
        for e,r in recs[PRIMARY].items():
            E=epi[e];t=teach.get(e,{})
            row={"fold":fn,"period_type":"FORWARD_post_freeze" if fn==FWD else "historical_transfer","episode_id":e,"side":E["side"],
                 "local_time_utc":iso(E["tmin_s"]+T0),"local_time_msk":iso_msk(E["tmin_s"]+T0),"local_price":E["target_price"],
                 "next_opposite_price":E["next_price"],"swing_pct":abs(E["next_price"]/E["target_price"]-1)*100,"regime":regmap.get(e),
                 "first_0.25pct_anchor_dist":first_anchor.get((e,"A25")),"first_0.40pct_anchor_dist":first_anchor.get((e,"A40")),
                 "teacher_accepted_true":bool(t.get("accepted") and t.get("true_first")),"teacher_dist_pct":t.get("entry_distance_pct") if t.get("true_first") else None,
                 "teacher_captured_mfe":t.get("captured_fraction") if t.get("true_first") else None}
            for c in [PRIMARY]+FALLBACKS:
                x=recs[c][e];key=c.replace("_SAFE_MAX_OOF_CAL","")
                row[f"{key}_outcome"]="TRUE_FIRST" if x["accepted"] and x["true_first"] else ("FALSE_FIRST" if x["accepted"] else "NO_SIGNAL")
                row[f"{key}_dist_pct"]=x.get("dist_pct");row[f"{key}_delay_s"]=x.get("delay_s");row[f"{key}_captured_mfe"]=x.get("captured_mfe_ratio")
            table.append(row)
    pickle.dump(table,open(OUT_/"per_local_table.pkl","wb"))
    # replay signals CSV: every first signal per episode for primary/fallback configs + teacher
    sig=[]
    for fn in TRANSFER+[FWD]:
        if fn not in F:continue
        for c in [PRIMARY]+FALLBACKS+[PROTECT_CFG]:
            for r in fold_records(rows,eps,F,fn,c):
                if r["accepted"]:
                    sig.append({"fold":fn,"period_type":"FORWARD_post_freeze" if fn==FWD else "historical_transfer","config":c,"side":r["side"],"episode_id":r["episode_id"],
                        "signal_time_utc":iso(r["signal_ts"]),"signal_time_msk":iso_msk(r["signal_ts"]),"decision_point":r["kind"],"entry_price":r["entry"],
                        "score":r["score"],"threshold":r["threshold"],"true_first":r["true_first"],"dist_from_member_extreme_pct":r["member_dist_pct"],
                        "dist_from_true_local_pct":r.get("dist_pct"),"delay_s":r.get("delay_s"),"captured_mfe_ratio":r.get("captured_mfe_ratio"),
                        "local_time_utc":iso(r["target_ts"]),"local_price":r["target_price"]})
        eids=sorted({r["episode_id"] for r in fold_records(rows,eps,F,fn,PRIMARY)})
        for e in eids:
            t=teach.get(e)
            if t and t["accepted"]:
                sig.append({"fold":fn,"period_type":"FORWARD_post_freeze" if fn==FWD else "historical_transfer","config":"TEACHER_V1_285m_130bps","side":t["side"],"episode_id":e,
                    "signal_time_utc":iso(t["signal_ts_ms"]//1000),"signal_time_msk":iso_msk(t["signal_ts_ms"]//1000),"decision_point":"CHECKPOINT_285m","entry_price":t["entry_price"],
                    "score":None,"threshold":None,"true_first":t["true_first"],"dist_from_member_extreme_pct":None,"dist_from_true_local_pct":t.get("entry_distance_pct"),
                    "delay_s":t.get("entry_delay_s"),"captured_mfe_ratio":t.get("captured_fraction"),"local_time_utc":iso(t["target_ts_ms"]//1000),"local_price":t["target_price"]})
    pickle.dump(sig,open(OUT_/"signals.pkl","wb"))
    # MFE simulation
    tp=Tape();MF={}
    periods={"WF_Jul":(SEGB["Jul"],SEGB["Aug"]),"WF_Aug":(SEGB["Aug"],SEGB["Sep"]),"WF_Sep":(SEGB["Sep"],SEGB["Oct"]),"WF_Oct":(SEGB["Oct"],SEGB["Nov4"]),FWD:(SEGB["Nov4"],SEGB["END"])}
    for fn,per in periods.items():
        if fn not in F:continue
        eids=sorted({r["episode_id"] for r in fold_records(rows,eps,F,fn,PRIMARY)})
        te=teacher_events(teach,eids)
        rev_e=member_events(rows,eps,F,fn,REVERSE_CFG);prot_e=member_events(rows,eps,F,fn,PROTECT_CFG)
        prim_e=member_events(rows,eps,F,fn,PRIMARY)
        ideal=ideal_capture(eps,per)
        sims={"TEACHER_ONLY":simulate(tp,per,te,[]),
              "EARLY_PRIMARY_B0.4_ONLY":simulate(tp,per,prim_e,[]),
              "EARLY_REVERSE_B1.0_ONLY":simulate(tp,per,rev_e,[]),
              "TWO_STAGE_PROTECT_B0.7Q995+REVERSE(B1.0_SAFE|TEACHER)":simulate(tp,per,rev_e+te,prot_e),
              "TEACHER_REVERSE+EARLY_PROTECT":simulate(tp,per,te,prot_e)}
        for k,v in sims.items():
            v["ideal_local_to_local_sum_pct"]=ideal;v["net_local_to_local_capture_ratio"]=v["gross_pnl_pct_sum"]/max(ideal,1e-9)
        MF[fn]={k:{kk:vv for kk,vv in v.items() if kk!="trades"} for k,v in sims.items()}
        MF[fn]["_trades"]={k:v["trades"] for k,v in sims.items()}
    agg={}
    for k in MF.get("WF_Oct",{}):
        if k.startswith("_"):continue
        vals=[MF[f][k] for f in TRANSFER if f in MF]
        agg[k]={m:float(sum(v[m] for v in vals)) for m in ("n_trades","gross_pnl_pct_sum","net_pnl_pct_sum_fee0.11rt","mfe_sum_pct","giveback_sum_pct","protect_exits","false_protective_exits","reversals","false_full_reversals","invalidation_exits","ideal_local_to_local_sum_pct")}
        agg[k]["net_local_to_local_capture_ratio"]=agg[k]["gross_pnl_pct_sum"]/max(agg[k]["ideal_local_to_local_sum_pct"],1e-9)
        agg[k]["mfe_preserved_ratio"]=agg[k]["gross_pnl_pct_sum"]/max(agg[k]["mfe_sum_pct"],1e-9)
    MF["transfer_aggregate"]=agg
    json.dump(M,open(OUT_/"metrics_raw.json","w"),default=float,indent=1)
    json.dump(MF,open(OUT_/"mfe_raw.json","w"),default=float,indent=1)
    print("PRIMARY transfer",json.dumps(M["transfer_aggregate"][PRIMARY],default=float))
    for c in FALLBACKS:print(c,json.dumps(M["transfer_aggregate"][c]["COMBINED"],default=float))
    print("TEACHER",json.dumps(M["transfer_aggregate"]["TEACHER_V1_same_episodes"]["COMBINED"],default=float))
    print("PARETO",M["pareto_transfer"])
    print("MFE agg",json.dumps(agg,indent=0,default=float))
