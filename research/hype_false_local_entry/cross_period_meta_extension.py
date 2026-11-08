#!/usr/bin/env python3
"""Cross-period meta-extension research for frozen HYPE HARD120.

Four already-open development regimes are used ONLY in leave-one-period-out
(LOPO) selection. A fifth June tape is deliberately absent from this script.

Architecture:
- frozen HARD120 primary is never vetoed or modified;
- meta model may only add +120m near-miss candidates:
    retrace >= 40 bps and 0.20 <= retrace/pre_move_180 < 0.45;
- LOW and HIGH use separate models/calibration;
- inner calibration uses OOF predictions only;
- a threshold is eligible only if EVERY inner regime keeps >=80% first-signal
  precision for that side and never reduces primary true-first detections;
- outer holdout is never used to fit model or threshold;
- ranking is by number of side×holdout 80/40 gates, then worst-case precision
  and recall. No real orders. No core flip authorization.

This is development selection, NOT untouched evidence. The next sealed evidence
is the independently built June 2026 tape.
"""
from __future__ import annotations

import argparse,bisect,gzip,json,math
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from research.hype_local_v5.labels import structural_labels

PRIMARY_RETRACE=40.0
PRIMARY_FRAC=0.45
NEAR_MIN_FRAC=0.20

FEATURE_SETS={
  "minimal":[
    "frac120","trendvol","cand_range","cand_rej",
    "pre_flow60","pre_flow180",
    "persist15","flow15","persist30","flow30","persist60","flow60",
    "persist120","flow120",
  ],
  "path_flow":[
    "frac120","trendvol","cand_range","cand_rej",
    "pre_flow15","pre_flow60","pre_flow180",
    "retr15","persist15","flow15","retr30","persist30","flow30",
    "retr60","persist60","flow60","retr90","persist90","flow90",
    "persist120","flow120","vol15","vol30","vol60","vol90","vol120",
  ],
  "full_causal":[
    "pre_move180","retr120","frac120","pretrend180","prevol60","prevol180","trendvol",
    "cand_range","cand_rej",
    "pre_flow15","pre_trades15","pre_turn15",
    "pre_flow60","pre_trades60","pre_turn60",
    "pre_flow180","pre_trades180","pre_turn180",
    "retr15","persist15","flow15","trades15","turn15","vol15",
    "retr30","persist30","flow30","trades30","turn30","vol30",
    "retr60","persist60","flow60","trades60","turn60","vol60",
    "retr90","persist90","flow90","vol90",
    "persist120","flow120","trades120","turn120","vol120",
  ],
}

MODEL_CONFIGS=[
  {"name":"log_c005","kind":"log","C":0.05},
  {"name":"log_c015","kind":"log","C":0.15},
  {"name":"hgb5","kind":"hgb","leaves":5,"leaf":10,"l2":3.0},
  {"name":"hgb7","kind":"hgb","leaves":7,"leaf":10,"l2":5.0},
  {"name":"extra3","kind":"extra","depth":3,"leaf":5},
  {"name":"extra4","kind":"extra","depth":4,"leaf":5},
]


def read_bars(path:Path)->list[dict[str,Any]]:
    out=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():out.append(json.loads(line))
    return out


def read_labels(path:Path,bars:list[dict[str,Any]])->list[dict[str,Any]]:
    with gzip.open(path,"rt",encoding="utf-8") as f:doc=json.load(f)
    internal=doc.get("internal") or []
    if not internal:
        internal,_=structural_labels(bars,lookback=3,lookahead=1)
    return sorted((dict(x) for x in internal if bool(x.get("reference_finalized"))),
                  key=lambda x:int(x["extreme_interval_start_ms"]))


def reversal_bps(side:str,p:float,mark:float)->float:
    if p<=0 or mark<=0:return 0.0
    return ((mark/p-1.0) if side=="LOW" else (p/mark-1.0))*10_000.0


def flow_rev(side:str,rows:list[dict[str,Any]])->float:
    buy=sum(float(x.get("buy_notional") or 0.0) for x in rows)
    sell=sum(float(x.get("sell_notional") or 0.0) for x in rows)
    raw=(buy-sell)/(buy+sell) if buy+sell else 0.0
    return raw if side=="LOW" else -raw


def popvol(rows:list[dict[str,Any]])->float:
    vals=[]
    for a,b in zip(rows,rows[1:]):
        ca=float(a["close"]);cb=float(b["close"])
        if ca>0:vals.append((cb/ca-1.0)*10_000.0)
    return float(np.std(vals)) if vals else 0.0


def generate_6h_candidates(bars:list[dict[str,Any]])->list[dict[str,Any]]:
    hist=deque(maxlen=360);out=[]
    for idx,b in enumerate(bars):
        prior=list(hist)
        if len(prior)>=360:
            lo=float(b["low"]);hi=float(b["high"])
            if lo<=min(float(x["low"]) for x in prior[-360:]):
                opp=max(float(x["high"]) for x in prior[-180:])
                pm=max(0.0,(opp/lo-1.0)*10_000.0)
                if pm>0:
                    out.append({"side":"LOW","extreme_ts_ms":int(b.get("low_ts_ms") or b["start_ms"]),
                                "bar_idx":idx,"bar_start_ms":int(b["start_ms"]),"extreme_price":lo,
                                "pre_move_180_bps":pm})
            if hi>=max(float(x["high"]) for x in prior[-360:]):
                opp=min(float(x["low"]) for x in prior[-180:])
                pm=max(0.0,(hi/opp-1.0)*10_000.0) if opp>0 else 0.0
                if pm>0:
                    out.append({"side":"HIGH","extreme_ts_ms":int(b.get("high_ts_ms") or b["start_ms"]),
                                "bar_idx":idx,"bar_start_ms":int(b["start_ms"]),"extreme_price":hi,
                                "pre_move_180_bps":pm})
        hist.append(b)
    return out


def checkpoint_idx(cand:dict[str,Any],end_ms:int,ends:list[int])->int|None:
    target=int(cand["extreme_ts_ms"])+7_200_000
    k=bisect.bisect_left(ends,target)
    if k>=len(ends) or ends[k]>=int(end_ms):return None
    return k


def feature_row(period:str,episode:int,side:str,cand:dict[str,Any],k:int,
                bars:list[dict[str,Any]],target:dict[str,Any])->dict[str,Any]|None:
    p=float(cand["extreme_price"]);mark=float(bars[k]["close"])
    retr=reversal_bps(side,p,mark);frac=retr/max(float(cand["pre_move_180_bps"]),1e-12)
    idx=int(cand["bar_idx"]);cb=bars[idx]
    pre180=bars[max(0,idx-180):idx];pre60=bars[max(0,idx-60):idx]
    if len(pre180)<180 or len(pre60)<60:return None
    op=float(pre180[0]["open"]);lc=float(pre180[-1]["close"])
    pretrend=((lc/op-1.0)*10_000.0 if side=="HIGH" else (op/lc-1.0)*10_000.0) if op>0 and lc>0 else 0.0
    vol60=popvol(pre60);vol180=popvol(pre180)
    lo=float(cb["low"]);hi=float(cb["high"])
    d={
      "period":period,"episode":episode,"side":side,
      "signal_ts_ms":int(bars[k]["bar_end_ms"]),"candidate_ts_ms":int(cand["extreme_ts_ms"]),
      "true":int(target["extreme_interval_start_ms"])<=int(cand["extreme_ts_ms"])<=int(target["extreme_interval_end_ms"]),
      "pre_move180":float(cand["pre_move_180_bps"]),"retr120":retr,"frac120":frac,
      "pretrend180":pretrend,"prevol60":vol60,"prevol180":vol180,
      "trendvol":max(0.0,pretrend)/max(vol60,1e-9),
      "cand_range":(hi/lo-1.0)*10_000.0 if lo>0 else 0.0,
      "cand_rej":reversal_bps(side,p,float(cb["close"])),
    }
    for m in (15,60,180):
        rr=bars[max(0,idx-m):idx]
        buy=sum(float(x.get("buy_notional") or 0.0) for x in rr)
        sell=sum(float(x.get("sell_notional") or 0.0) for x in rr)
        d[f"pre_flow{m}"]=flow_rev(side,rr)
        d[f"pre_trades{m}"]=math.log1p(sum(int(x.get("trade_count") or 0) for x in rr))
        d[f"pre_turn{m}"]=math.log1p(buy+sell)
    for m in (15,30,60,90,120):
        rr=bars[idx+1:idx+1+m]
        if len(rr)<m:return None
        rb=reversal_bps(side,p,float(rr[-1]["close"]))
        if side=="LOW":
            maxrev=(max(float(x["high"]) for x in rr)/p-1.0)*10_000.0
        else:
            best=min(float(x["low"]) for x in rr);maxrev=(p/best-1.0)*10_000.0
        d[f"retr{m}"]=rb
        d[f"persist{m}"]=max(0.0,min(1.0,rb/max(maxrev,1e-9)))
        d[f"flow{m}"]=flow_rev(side,rr)
        d[f"trades{m}"]=math.log1p(sum(int(x.get("trade_count") or 0) for x in rr))
        d[f"turn{m}"]=math.log1p(sum(float(x.get("buy_notional") or 0)+float(x.get("sell_notional") or 0) for x in rr))
        d[f"vol{m}"]=popvol(rr)
    return d


def build_period(name:str,compact:Path,labels_path:Path)->tuple[pd.DataFrame,dict[str,int],int]:
    bars=read_bars(compact);ends=[int(b["bar_end_ms"]) for b in bars];labels=read_labels(labels_path,bars)
    candidates=generate_6h_candidates(bars);by={"LOW":[],"HIGH":[]}
    for x in candidates:by[x["side"]].append(x)
    rows=[];counts={"LOW":0,"HIGH":0}
    for j in range(1,len(labels)-1):
        prev,target,nxt=labels[j-1],labels[j],labels[j+1]
        side=str(target["side"]);counts[side]+=1
        start=int(prev["extreme_interval_start_ms"]);target_end=int(target["extreme_interval_end_ms"]);deadline=int(nxt["extreme_interval_start_ms"])
        evs=sorted((x for x in by[side] if start<int(x["extreme_ts_ms"])<=target_end),
                   key=lambda x:int(x["extreme_ts_ms"]))
        current=None
        def evaluate(c,end_ms):
            if c is None:return
            k=checkpoint_idx(c,end_ms,ends)
            if k is None:return
            r=feature_row(name,j,side,c,k,bars,target)
            if r is not None:rows.append(r)
        for e in evs:
            if current is None:
                current=e;continue
            more=float(e["extreme_price"])<float(current["extreme_price"]) if side=="LOW" else float(e["extreme_price"])>float(current["extreme_price"])
            if not more:continue
            evaluate(current,int(e["extreme_ts_ms"]));current=e
        evaluate(current,deadline)
    return pd.DataFrame(rows),counts,len(labels)


def primary_mask(df:pd.DataFrame)->pd.Series:
    return (df["retr120"]>=PRIMARY_RETRACE)&(df["frac120"]>=PRIMARY_FRAC)


def near_mask(df:pd.DataFrame)->pd.Series:
    return (df["retr120"]>=PRIMARY_RETRACE)&(df["frac120"]>=NEAR_MIN_FRAC)&(df["frac120"]<PRIMARY_FRAC)


def make_model(cfg:dict[str,Any]):
    if cfg["kind"]=="log":
        return make_pipeline(SimpleImputer(strategy="median"),StandardScaler(),
            LogisticRegression(C=float(cfg["C"]),class_weight="balanced",max_iter=3000,solver="liblinear"))
    if cfg["kind"]=="hgb":
        return make_pipeline(SimpleImputer(strategy="median"),
            HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=int(cfg["leaves"]),
                min_samples_leaf=int(cfg["leaf"]),learning_rate=.05,l2_regularization=float(cfg["l2"]),random_state=17))
    if cfg["kind"]=="extra":
        return make_pipeline(SimpleImputer(strategy="median"),
            ExtraTreesClassifier(n_estimators=100,max_depth=int(cfg["depth"]),min_samples_leaf=int(cfg["leaf"]),
                max_features="sqrt",class_weight="balanced",random_state=17,n_jobs=2))
    raise ValueError(cfg)


def prepare_episode_maps(df:pd.DataFrame,counts:dict[str,dict[str,int]]):
    primary={};near={}
    for (p,side,ep),g in df.groupby(["period","side","episode"]):
        pg=g[primary_mask(g)].sort_values(["signal_ts_ms","candidate_ts_ms"])
        primary[(p,side,int(ep))]=None if pg.empty else (int(pg.iloc[0]["signal_ts_ms"]),bool(pg.iloc[0]["true"]),int(pg.index[0]))
        ng=g[near_mask(g)].sort_values(["signal_ts_ms","candidate_ts_ms"])
        near[(p,side,int(ep))]=[(int(r["signal_ts_ms"]),bool(r["true"]),int(idx)) for idx,r in ng.iterrows()]
    ids={(p,s):sorted(set(df[(df.period==p)&(df.side==s)].episode.astype(int))) for p in counts for s in ("LOW","HIGH")}
    return primary,near,ids


def side_metrics(periods:list[str],side:str,scores:dict[int,float],threshold:float,
                 counts,primary,near,ids)->dict[str,Any]:
    tp=fp=accepted=0
    for p in periods:
        for ep in ids[(p,side)]:
            best=primary.get((p,side,ep))
            for ts,true,idx in near.get((p,side,ep),[]):
                sc=scores.get(idx,float("nan"))
                if math.isfinite(sc) and sc>=threshold:
                    cand=(ts,true,idx)
                    if best is None or ts<best[0]:best=cand
                    break
            if best is not None:
                accepted+=1
                if best[1]:tp+=1
                else:fp+=1
    den=sum(counts[p][side] for p in periods)
    return {"episodes":den,"accepted_first":accepted,"true_first":tp,"false_first":fp,
            "precision":tp/accepted if accepted else 0.0,"recall":tp/den if den else 0.0}


def choose_threshold(oof:dict[int,float],train_periods:list[str],side:str,
                     counts,primary,near,ids,min_precision=.80)->tuple[float,dict]:
    vals=np.array([x for x in oof.values() if math.isfinite(x)],dtype=float)
    grid=np.unique(np.r_[1.01,np.linspace(.45,.995,56),
                         np.quantile(vals,np.linspace(.05,.99,40)) if len(vals) else []])
    base={p:side_metrics([p],side,{},2.0,counts,primary,near,ids) for p in train_periods}
    best=None
    for th in grid:
        per={p:side_metrics([p],side,oof,float(th),counts,primary,near,ids) for p in train_periods}
        if any(m["precision"]+1e-12<min_precision for m in per.values()):continue
        if any(per[p]["true_first"]<base[p]["true_first"] for p in train_periods):continue
        key=(min(m["recall"] for m in per.values()),
             float(np.mean([m["recall"] for m in per.values()])),
             min(m["precision"] for m in per.values()),float(th))
        if best is None or key>best[0]:best=(key,float(th),per)
    if best is None:return 1.01,base
    return best[1],best[2]


def evaluate_config(df,counts,cfg,features,primary,near,ids)->dict[str,Any]:
    periods=list(counts)
    outer={}
    for hold in periods:
        train=[p for p in periods if p!=hold]
        thresholds={};side_out={}
        for side in ("LOW","HIGH"):
            oof={}
            for val in train:
                tr=[p for p in train if p!=val]
                trr=df[df.period.isin(tr)&(df.side==side)&near_mask(df)]
                vr=df[(df.period==val)&(df.side==side)&near_mask(df)]
                if len(trr) and trr.true.nunique()>1 and len(vr):
                    model=make_model(cfg);model.fit(trr[features],trr.true.astype(int))
                    oof.update(dict(zip(vr.index.astype(int),model.predict_proba(vr[features])[:,1])))
            th,inner=choose_threshold(oof,train,side,counts,primary,near,ids)
            thresholds[side]=th
            trr=df[df.period.isin(train)&(df.side==side)&near_mask(df)]
            hr=df[(df.period==hold)&(df.side==side)&near_mask(df)]
            hs={}
            if len(trr) and trr.true.nunique()>1 and len(hr):
                model=make_model(cfg);model.fit(trr[features],trr.true.astype(int))
                hs=dict(zip(hr.index.astype(int),model.predict_proba(hr[features])[:,1]))
            side_out[side]=side_metrics([hold],side,hs,th,counts,primary,near,ids)
            side_out[side]["inner_threshold"]=th
            side_out[side]["inner_periods"]=inner
        tp=sum(side_out[s]["true_first"] for s in ("LOW","HIGH"))
        fp=sum(side_out[s]["false_first"] for s in ("LOW","HIGH"))
        den=sum(counts[hold].values())
        outer[hold]={"LOW":side_out["LOW"],"HIGH":side_out["HIGH"],
                     "ALL":{"episodes":den,"accepted_first":tp+fp,"true_first":tp,"false_first":fp,
                            "precision":tp/(tp+fp) if tp+fp else 0.0,"recall":tp/den if den else 0.0}}
    side_cells=[outer[p][s] for p in periods for s in ("LOW","HIGH")]
    summary={
      "side_gate_passes":sum(m["precision"]>=.80 and m["recall"]>=.40 for m in side_cells),
      "side_cells":len(side_cells),
      "overall_gate_passes":sum(outer[p]["ALL"]["precision"]>=.80 and outer[p]["ALL"]["recall"]>=.40 for p in periods),
      "worst_side_precision":min(m["precision"] for m in side_cells),
      "worst_side_recall":min(m["recall"] for m in side_cells),
      "mean_side_precision":float(np.mean([m["precision"] for m in side_cells])),
      "mean_side_recall":float(np.mean([m["recall"] for m in side_cells])),
    }
    return {"summary":summary,"outer":outer}


def main():
    ap=argparse.ArgumentParser()
    for p in ("julaug","lateaug","sep","octnov"):
        ap.add_argument(f"--{p}-compact",type=Path,required=True)
        ap.add_argument(f"--{p}-labels",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()

    frames=[];counts={};label_counts={}
    for p in ("julaug","lateaug","sep","octnov"):
        frame,c,n=build_period(p,getattr(args,f"{p}_compact"),getattr(args,f"{p}_labels"))
        frames.append(frame);counts[p]=c;label_counts[p]=n
    df=pd.concat(frames,ignore_index=True)
    primary,near,ids=prepare_episode_maps(df,counts)

    # Exact production-semantics primary sanity table.
    baseline={}
    for p in counts:
        baseline[p]={s:side_metrics([p],s,{},2.0,counts,primary,near,ids) for s in ("LOW","HIGH")}
        tp=sum(baseline[p][s]["true_first"] for s in ("LOW","HIGH"))
        fp=sum(baseline[p][s]["false_first"] for s in ("LOW","HIGH"))
        den=sum(counts[p].values())
        baseline[p]["ALL"]={"episodes":den,"accepted_first":tp+fp,"true_first":tp,"false_first":fp,
                              "precision":tp/(tp+fp),"recall":tp/den}

    results=[]
    for fs,features in FEATURE_SETS.items():
        for cfg in MODEL_CONFIGS:
            r=evaluate_config(df,counts,cfg,features,primary,near,ids)
            results.append({"feature_set":fs,"model":cfg,**r})
    results.sort(key=lambda r:(
        r["summary"]["side_gate_passes"],
        r["summary"]["overall_gate_passes"],
        r["summary"]["worst_side_precision"],
        r["summary"]["worst_side_recall"],
        r["summary"]["mean_side_recall"],
    ),reverse=True)
    out={
      "version":"HYPE_CROSS_PERIOD_META_EXTENSION_SELECTION_V1",
      "research_only":True,"real_orders":False,"core_flip_authorized":False,
      "primary":"INTERNAL_HARD120_CHECKPOINT_V2_UNCHANGED",
      "extension_domain":{"retrace_min_bps":PRIMARY_RETRACE,"frac_min":NEAR_MIN_FRAC,"frac_max_exclusive":PRIMARY_FRAC},
      "development_periods":["2026-07-12..2026-08-07","2026-08-08..2026-09-01","2026-09-01..2026-10-01","2026-10-04..2026-11-03"],
      "sealed_june_excluded_from_selection":True,
      "label_counts":label_counts,"episode_counts":counts,"checkpoint_rows":len(df),
      "baseline":baseline,"configs":results,"best":results[0],
      "promotion":"NONE_SELECTION_ONLY_UNTIL_SEALED_JUNE",
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("META_SELECTION="+json.dumps({
        "best_feature_set":results[0]["feature_set"],"best_model":results[0]["model"],
        "best_summary":results[0]["summary"],"baseline":baseline,
    },separators=(",",":"),ensure_ascii=False))

if __name__=="__main__":
    main()
