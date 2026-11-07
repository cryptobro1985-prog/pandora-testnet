from __future__ import annotations
import argparse,gzip,json,math
from pathlib import Path
import numpy as np
from sklearn.metrics import roc_auc_score,average_precision_score

WINDOWS=(15,30,60,180,300)

def finite(v): return isinstance(v,(int,float,np.number)) and math.isfinite(float(v))
def load(path):
    out=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r=json.loads(line)
                if int(r["delay_s"])==0: out.append(r)
    return sorted(out,key=lambda r:int(r["candidate_ts_ms"]))

def mirrored(r):
    f=r["features"]; side=r["side"]; rev=1 if side=="LOW" else -1
    o={}
    for w in WINDOWS:
        buy=math.expm1(float(f.get(f"buy_{w}s_log",0.0))); sell=math.expm1(float(f.get(f"sell_{w}s_log",0.0)))
        trend=sell if side=="LOW" else buy
        counter=buy if side=="LOW" else sell
        ret=f.get(f"ret_{w}s")
        if finite(ret):
            tr=(-float(ret) if side=="LOW" else float(ret))
            o[f"trend_return_{w}s"]=tr
            o[f"trend_efficiency_{w}s"]=max(tr,0)/(trend+1e-12)*1e6
        o[f"counter_to_trend_flow_{w}s"]=counter/(trend+1e-12)
        o[f"counter_flow_share_{w}s"]=counter/(counter+trend+1e-12)
        tc=f.get(f"trade_count_{w}s")
        if finite(tc): o[f"trade_count_{w}s"]=float(tc)
    for a,b in ((15,300),(30,300),(30,180),(60,300)):
        x=o.get(f"counter_to_trend_flow_{a}s"); y=o.get(f"counter_to_trend_flow_{b}s")
        if finite(x) and finite(y): o[f"counterflow_acceleration_{a}_{b}"]=x/(y+1e-9)
        x=o.get(f"trend_efficiency_{a}s"); y=o.get(f"trend_efficiency_{b}s")
        if finite(x) and finite(y): o[f"trend_efficiency_ratio_{a}_{b}"]=x/(y+1e-9)
    for name in ("60m","6h","24h"):
        dl=f.get(f"distance_low_{name}_bps"); dh=f.get(f"distance_high_{name}_bps"); pos=f.get(f"position_{name}")
        if finite(dl) and finite(dh):
            o[f"extreme_penetration_{name}"]=-float(dl) if side=="LOW" else -float(dh)
            o[f"opposite_side_distance_{name}"]=float(dh) if side=="LOW" else float(dl)
        if finite(pos): o[f"extreme_position_{name}"]=-float(pos) if side=="LOW" else float(pos)-1.0
    for n in (5,10,25,50):
        k=f"fullmicro_book_imbalance_{n}"
        if finite(f.get(k)): o[f"support_book_imbalance_{n}"]=float(f[k])*rev
        b=[];a=[]
        for i in range(1,n+1):
            bv=f.get(f"fullmicro_bid_{i:02d}_log_qty"); av=f.get(f"fullmicro_ask_{i:02d}_log_qty")
            if not finite(bv) or not finite(av): b=[];a=[];break
            b.append(math.expm1(float(bv)));a.append(math.expm1(float(av)))
        if b:
            bs,as_=sum(b),sum(a)
            support=bs if side=="LOW" else as_
            pressure=as_ if side=="LOW" else bs
            o[f"support_to_pressure_depth_{n}"]=support/(pressure+1e-12)
            o[f"total_depth_{n}"]=support+pressure
    for i in range(1,51):
        b=f.get(f"fullmicro_bid_{i:02d}_log_qty"); a=f.get(f"fullmicro_ask_{i:02d}_log_qty")
        if finite(b) and finite(a):
            o[f"support_qty_{i:02d}"]=float(b) if side=="LOW" else float(a)
            o[f"pressure_qty_{i:02d}"]=float(a) if side=="LOW" else float(b)
            o[f"support_minus_pressure_qty_{i:02d}"]=(float(b)-float(a))*rev
    if finite(f.get("fullmicro_spread_bps")): o["spread_bps"]=float(f["fullmicro_spread_bps"])
    for w in (15,60,180,300):
        l=f.get(f"fullmicro_long_liq_notional_{w}s"); s=f.get(f"fullmicro_short_liq_notional_{w}s")
        if finite(l) and finite(s):
            trend=float(l) if side=="LOW" else float(s)
            counter=float(s) if side=="LOW" else float(l)
            o[f"trend_liquidation_share_{w}s"]=trend/(trend+counter+1e-12)
    for k,v in f.items():
        if k.startswith("fullmicro_open_interest_") and finite(v): o[k]=float(v)
    mp=f.get("fullmicro_mark_price_mark_price"); ip=f.get("fullmicro_mark_price_index_price")
    if finite(mp) and finite(ip) and float(ip)!=0: o["basis_bps"]=(float(mp)/float(ip)-1)*10000
    if finite(f.get("fullmicro_mark_price_funding_rate")): o["funding_rate"]=float(f["fullmicro_mark_price_funding_rate"])
    return o

def auc(part,k):
    z=[(int(r["y"]),r["x"].get(k)) for r in part if finite(r["x"].get(k))]
    if len(z)<20 or len({y for y,_ in z})<2 or len({v for _,v in z})<2:return None
    return float(roc_auc_score([y for y,_ in z],[v for _,v in z]))

def score_rows(part,base,weights):
    bases={}
    for k,w in weights.items():
        if not w:continue
        arr=sorted(float(r["x"][k]) for r in base if finite(r["x"].get(k)))
        if len(arr)>=20:bases[k]=arr
    out=[]
    for r in part:
        s=0.;den=0.
        for k,w in weights.items():
            if not w or k not in bases or not finite(r["x"].get(k)):continue
            arr=bases[k];v=float(r["x"][k])
            import bisect
            pct=bisect.bisect_right(arr,v)/len(arr)
            s+=(pct-.5)*2*(1 if w>0 else -1)*abs(w);den+=abs(w)
        out.append(s/den if den else 0.)
    return np.asarray(out,dtype=float)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--snapshots",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    raw=load(a.snapshots)
    rows=[{"ts":int(r["candidate_ts_ms"]),"y":bool(r["strict_true"]),"side":r["side"],"x":mirrored(r)} for r in raw]
    n=len(rows);c1=int(n*.55);c2=int(n*.70);c3=int(n*.85)
    train,tune,calib,test=rows[:c1],rows[c1:c2],rows[c2:c3],rows[c3:]
    names=sorted({k for r in rows for k in r["x"]})
    weights={};detail=[]
    for k in names:
        a1=auc(train,k);a2=auc(tune,k)
        w=0.
        if a1 is not None and a2 is not None:
            d1=a1-.5;d2=a2-.5
            if d1*d2>0:w=(1 if d1>0 else -1)*min(abs(d1),abs(d2))
        weights[k]=w
        detail.append({"feature":k,"train_auc":a1,"tune_auc":a2,"weight":w})
    base=train+tune
    cal=score_rows(calib,base,weights);tst=score_rows(test,base,weights)
    cy=np.asarray([int(r["y"]) for r in calib]);ty=np.asarray([int(r["y"]) for r in test])
    result={
      "objective":"ONE mirrored global Local relation; all available causal groups scanned simultaneously, future labels excluded from X.",
      "rows":{"train":len(train),"tune":len(tune),"calibration":len(calib),"frozen_test":len(test)},
      "true_locals":{"train":sum(r["y"] for r in train),"tune":sum(r["y"] for r in tune),"calibration":sum(r["y"] for r in calib),"frozen_test":sum(r["y"] for r in test)},
      "candidate_derived_dimensions_scanned":len(names),
      "nonzero_stable_dimensions":sum(bool(w) for w in weights.values()),
      "calibration":{"roc_auc":float(roc_auc_score(cy,cal)),"average_precision":float(average_precision_score(cy,cal))},
      "frozen_test":{"roc_auc":float(roc_auc_score(ty,tst)),"average_precision":float(average_precision_score(ty,tst))},
      "relationship":"A real Local is the terminal exhaustion state of the active swing: structural penetration is extreme, counter-flow rises relative to continuation flow, and the order-book/depth state shifts toward the reversal side while continuation price-impact/efficiency loses persistence. LOW/HIGH are mirror images under side normalization.",
      "weights":sorted(detail,key=lambda z:abs(z["weight"]),reverse=True),
      "note":"This is one composite relation learned across the full available causal feature space. Unstable/noisy dimensions receive zero weight rather than being cherry-picked as separate rules."
    }
    (a.out/"GLOBAL_LOCAL_RELATION_LATEST.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({k:result[k] for k in ("candidate_derived_dimensions_scanned","nonzero_stable_dimensions","calibration","frozen_test")},separators=(",",":")))
if __name__=="__main__":main()
