from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

from research.caterpillar.caterpillar.sources import Archives
from research.caterpillar.caterpillar.model import SYMBOLS
from research.hype_local_v5.labels import structural_labels
from research.hype_quant.feature_contract import POINTS, INPUT_IDS, TARGET_IDS

START=datetime(2026,10,4,tzinfo=timezone.utc)
DISCOVERY=datetime(2026,10,11,tzinfo=timezone.utc)
TRAIN_END=datetime(2026,10,23,tzinfo=timezone.utc)
OOS=datetime(2026,10,27,tzinfo=timezone.utc)
END=datetime(2026,11,3,tzinfo=timezone.utc)
DELAYS=(0,30,60,180,300)
WINDOWS=(5,15,30,60,180,300)
EPS=1e-12

HISTORICAL_OBSERVED_IDS=set(range(1,44))|{63,64,79,80,81,82,116}
HISTORICAL_UNAVAILABLE={
    2:"mark price history not present in executed-trade archive",
    3:"index price history not present in executed-trade archive",
    **{i:"historical L50 order-book replay was not recorded" for i in range(44,58)},
    **{i:"historical OI/funding source not present in this archive-only pass" for i in range(58,63)},
    **{i:"historical liquidation WS events were not recorded" for i in range(65,77)},
    77:"receive timestamp does not exist in exchange daily archive",
    78:"live microstructure snapshot timestamp does not exist historically",
    111:"historical runner/server clock offset is not reconstructable",
    112:"instrument metadata is metadata-only for this study, not a fitted local feature",
    113:"historical public holder ratio not present in archive-only pass",
    114:"historical mark-index basis not present in archive-only pass",
    115:"OI notional unavailable without historical OI",
}
# Point 1 and 4..43,63,64,79,80,116 are supported in this archive pass.
HISTORICAL_OBSERVED_IDS-=set(HISTORICAL_UNAVAILABLE)

def stamp(dt):
    return int(dt.timestamp()*1000)

def finite(x):
    return isinstance(x,(int,float)) and math.isfinite(x)

def write_json(path,obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")

def write_json_gz(path,obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(path,"wt",encoding="utf-8",compresslevel=9) as f:
        json.dump(obj,f,separators=(",",":"),sort_keys=True,allow_nan=False)

def write_jsonl_gz(path,rows):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(path,"wt",encoding="utf-8",compresslevel=9) as f:
        for row in rows:
            f.write(json.dumps(row,separators=(",",":"),sort_keys=True,allow_nan=False)+"\n")

def read_jsonl_gz(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def new_bucket(start_ms,price):
    return dict(start_ms=start_ms,bar_end_ms=None,open=price,high=price,low=price,close=price,
                high_ts_ms=start_ms,low_ts_ms=start_ms,buy_notional=0.0,sell_notional=0.0,
                buy_count=0,sell_count=0,trade_count=0,quantity=0.0,max_trade_notional=0.0)

def add_trade(b,ts_ms,price,qty,side):
    n=price*qty
    if price>b["high"]:
        b["high"]=price;b["high_ts_ms"]=ts_ms
    if price<b["low"]:
        b["low"]=price;b["low_ts_ms"]=ts_ms
    b["close"]=price;b["trade_count"]+=1;b["quantity"]+=qty
    b["max_trade_notional"]=max(b["max_trade_notional"],n)
    if side==1:
        b["buy_notional"]+=n;b["buy_count"]+=1
    else:
        b["sell_notional"]+=n;b["sell_count"]+=1

def finalize_bucket(b,interval_ms):
    b["bar_end_ms"]=b["start_ms"]+interval_ms
    b["ts_ms"]=b["bar_end_ms"]
    total=b["buy_notional"]+b["sell_notional"]
    b["turnover"]=total
    b["volume"]=b["quantity"]
    b["flow_imbalance"]=(b["buy_notional"]-b["sell_notional"])/total if total else 0.0
    b["flow_observed"]=True
    b["interval_ms"]=interval_ms
    b["gap"]=False
    return b

def aggregate_symbol(symbol,cache):
    source=Archives(cache)
    sec5=[]
    mins=[]
    daily=[]
    previous_trade_ts=None
    previous_close=None
    current5=current1=None
    total_trades=0
    max_gap=0.0
    cross_day_gaps=[]

    def flush5():
        nonlocal current5
        if current5 is not None:
            sec5.append(finalize_bucket(current5,5000)); current5=None
    def flush1():
        nonlocal current1
        if current1 is not None:
            mins.append(finalize_bucket(current1,60000)); current1=None

    day=START
    while day<END:
        day_rows=0;duplicates=0;seen=set();first_ts=None;last_ts=None;day_max_gap=0.0
        iterator,meta=source.trades(symbol,day)
        for t in iterator:
            ts_ms=int(round(t.ts*1000))
            if first_ts is None:first_ts=ts_ms
            last_ts=ts_ms
            if t.trade_id in seen:
                duplicates+=1
                continue
            seen.add(t.trade_id)
            if previous_trade_ts is not None:
                gap=(ts_ms-previous_trade_ts)/1000
                if gap<0:
                    raise RuntimeError("reordered trade")
                day_max_gap=max(day_max_gap,gap);max_gap=max(max_gap,gap)
                if gap>300:
                    cross_day_gaps.append({"from_ms":previous_trade_ts,"to_ms":ts_ms,"seconds":gap})
            previous_trade_ts=ts_ms
            k5=(ts_ms//5000)*5000
            k1=(ts_ms//60000)*60000
            if current5 is None or current5["start_ms"]!=k5:
                flush5();current5=new_bucket(k5,t.price)
            if current1 is None or current1["start_ms"]!=k1:
                flush1();current1=new_bucket(k1,t.price)
            add_trade(current5,ts_ms,t.price,t.quantity,t.side)
            add_trade(current1,ts_ms,t.price,t.quantity,t.side)
            previous_close=t.price
            day_rows+=1;total_trades+=1
        if duplicates:
            raise RuntimeError(f"{symbol} {day.date()} duplicate trade IDs: {duplicates}")
        if day_rows==0:
            raise RuntimeError(f"{symbol} {day.date()} empty archive")
        daily.append({"date":day.date().isoformat(),"rows":day_rows,"first_ts_ms":first_ts,"last_ts_ms":last_ts,
                      "max_intertrade_gap_s":day_max_gap,"archive_sha256":meta.get("sha256"),
                      "archive_bytes":meta.get("bytes"),"archive_url":meta.get("url")})
        # Raw data is intentionally ephemeral: keep only copied provenance.
        name=f"{symbol}USDT{day:%Y-%m-%d}.csv.gz"
        raw=Path(cache)/name;manifest=Path(cache)/(name+".json")
        raw.unlink(missing_ok=True);manifest.unlink(missing_ok=True)
        seen.clear()
        print(json.dumps({"symbol":symbol,"day":day.date().isoformat(),"rows":day_rows,
                          "total_rows":total_trades,"raw_deleted":not raw.exists()}),flush=True)
        day+=timedelta(days=1)
    flush5();flush1()
    if len(daily)!=(END-START).days:
        raise RuntimeError("not all requested days processed")
    return sec5,mins,dict(days=daily,total_trades=total_trades,max_intertrade_gap_s=max_gap,
                          suspicious_gaps_over_300s=cross_day_gaps)

def aggregate_h1(mins):
    out=[]
    groups=defaultdict(list)
    for r in mins:
        groups[r["start_ms"]//3_600_000*3_600_000].append(r)
    for h,rows in sorted(groups.items()):
        rows.sort(key=lambda x:x["start_ms"])
        if rows[0]["start_ms"]!=h or rows[-1]["bar_end_ms"]!=h+3_600_000:
            continue
        if any(b["start_ms"]!=a["bar_end_ms"] for a,b in zip(rows,rows[1:])):
            continue
        out.append({"start_ms":h,"end_ms":h+3_600_000,"open":rows[0]["open"],"high":max(x["high"] for x in rows),
                    "low":min(x["low"] for x in rows),"close":rows[-1]["close"]})
    return out

def rolling_extreme(values,start,end,fn):
    xs=values[start:end]
    return fn(xs) if xs else None

def label_maps(labels):
    by_side={"HIGH":[],"LOW":[]}
    for x in labels:
        by_side[x["side"]].append(x)
    return by_side

def matches_label(candidate,labels):
    for x in labels:
        if x["side"]!=candidate["side"]:continue
        if not (x["extreme_interval_start_ms"]<=candidate["extreme_ts_ms"]<=x["extreme_interval_end_ms"]):
            continue
        if math.isclose(float(x["extreme_price"]),float(candidate["extreme_price"]),rel_tol=1e-12,abs_tol=1e-10):
            return x["label_id"]
    return None

def build_candidates(mins,strict_labels,internal_labels):
    out=[]
    lows=[];highs=[]
    for i,r in enumerate(mins):
        if i>=360:
            prev_low=min(lows[-360:]);prev_high=max(highs[-360:])
            if r["low"]<prev_low:
                c={"side":"LOW","extreme_price":r["low"],"extreme_ts_ms":r["low_ts_ms"],
                   "minute_start_ms":r["start_ms"],"candidate_id":f"L-{r['low_ts_ms']}"}
                c["strict_label_id"]=matches_label(c,strict_labels)
                c["internal_label_id"]=matches_label(c,internal_labels);out.append(c)
            if r["high"]>prev_high:
                c={"side":"HIGH","extreme_price":r["high"],"extreme_ts_ms":r["high_ts_ms"],
                   "minute_start_ms":r["start_ms"],"candidate_id":f"H-{r['high_ts_ms']}"}
                c["strict_label_id"]=matches_label(c,strict_labels)
                c["internal_label_id"]=matches_label(c,internal_labels);out.append(c)
        lows.append(r["low"]);highs.append(r["high"])
    return out

def sec_window(sec5,starts,end_ms,seconds):
    begin=end_ms-seconds*1000
    i=bisect.bisect_left(starts,begin)
    j=bisect.bisect_right(starts,end_ms-1)
    return sec5[i:j]

def aggregate_window(rows,reversal_sign):
    if not rows:return {}
    buy=sum(x["buy_notional"] for x in rows);sell=sum(x["sell_notional"] for x in rows)
    total=buy+sell
    raw_ret=rows[-1]["close"]/rows[0]["open"]-1 if rows[0]["open"] else 0.0
    imb=(buy-sell)/total if total else 0.0
    rev_ret=raw_ret*reversal_sign
    rev_flow=imb*reversal_sign
    # Reversal-side efficiency: LOW expects buy response, HIGH expects sell response.
    rev_notional=buy if reversal_sign==1 else sell
    old_notional=sell if reversal_sign==1 else buy
    return {"imbalance":imb,"rev_flow":rev_flow,"ret":raw_ret,"rev_ret":rev_ret,
            "buy":buy,"sell":sell,"total":total,
            "trade_count":sum(x["trade_count"] for x in rows),
            "max_trade":max(x["max_trade_notional"] for x in rows),
            "rev_eff":max(rev_ret,0)/(rev_notional+EPS)*1e6,
            "old_eff":max(-rev_ret,0)/(old_notional+EPS)*1e6}

def recent_minute_index(min_starts,t):
    return bisect.bisect_right(min_starts,t)-1

def snapshot_features(candidate,t_ms,sec5,sec_starts,mins,min_starts,h1):
    side=candidate["side"];rev=1 if side=="LOW" else -1
    px=candidate["extreme_price"]
    out={"age_s":max(0,(t_ms-candidate["extreme_ts_ms"])/1000)}
    last5=sec_window(sec5,sec_starts,t_ms,5)
    current=last5[-1]["close"] if last5 else px
    out["retrace_bps"]=(current/px-1)*rev*10000
    for w in WINDOWS:
        a=aggregate_window(sec_window(sec5,sec_starts,t_ms,w),rev)
        for k,v in a.items():
            if k in ("buy","sell","total","max_trade"):
                out[f"{k}_{w}s_log"]=math.log1p(max(0.0,v))
            else:
                out[f"{k}_{w}s"]=v
    mi=recent_minute_index(min_starts,t_ms)
    if mi>=0:
        cur=mins[mi]
        for n,name in ((60,"60m"),(360,"6h"),(1440,"24h")):
            lo=max(0,mi-n+1);part=mins[lo:mi+1]
            low=min(x["low"] for x in part);high=max(x["high"] for x in part)
            rng=max(high-low,EPS)
            out[f"position_{name}"]=(current-low)/rng
            out[f"distance_low_{name}_bps"]=(current/low-1)*10000 if low else 0.0
            out[f"distance_high_{name}_bps"]=(high/current-1)*10000 if current else 0.0
        returns=[]
        for x in mins[max(1,mi-60):mi+1]:
            prev=mins[mins.index(x)-1]["close"] if False else None
        part=mins[max(0,mi-60):mi+1]
        if len(part)>=2:
            rr=[part[k]["close"]/part[k-1]["close"]-1 for k in range(1,len(part))]
            out["volatility_60m"]=math.sqrt(sum(x*x for x in rr)/len(rr))
        else:out["volatility_60m"]=0.0
        out["volume_24h_log"]=math.log1p(sum(x["volume"] for x in mins[max(0,mi-1439):mi+1]))
        out["turnover_24h_log"]=math.log1p(sum(x["turnover"] for x in mins[max(0,mi-1439):mi+1]))
    # H1 completed strictly before snapshot.
    hh=[x for x in h1 if x["end_ms"]<=t_ms]
    if hh:
        ranges=[(x["high"]-x["low"])/x["close"] for x in hh[-14:] if x["close"]]
        out["atr_h1_frac"]=sum(ranges)/len(ranges) if ranges else 0.0
        for n in (3,6):
            p=hh[-n:]
            out[f"directional_{n}h_rev"]=(p[-1]["close"]/p[0]["open"]-1)*rev if len(p)==n else 0.0
    else:
        out["atr_h1_frac"]=0.0;out["directional_3h_rev"]=0.0;out["directional_6h_rev"]=0.0
    # Count alternating 5s price-direction changes since the candidate.
    rows=sec_window(sec5,sec_starts,t_ms,int(max(5,out["age_s"])))
    signs=[]
    for a,b in zip(rows,rows[1:]):
        d=b["close"]-a["close"]
        s=1 if d>0 else -1 if d<0 else 0
        if s:signs.append(s)
    out["reversal_attempts"]=sum(a!=b for a,b in zip(signs,signs[1:]))
    return {k:float(v) for k,v in out.items() if finite(v)}

def build_snapshots(symbol,candidates,sec5,mins,h1):
    sec_starts=[x["start_ms"] for x in sec5];min_starts=[x["start_ms"] for x in mins]
    rows=[]
    for c in candidates:
        invalidated_at=None
        for d in DELAYS:
            t=c["extreme_ts_ms"]+d*1000
            # Same-side extension before this causal snapshot invalidates it.
            window=sec_window(sec5,sec_starts,t,max(5,d))
            if c["side"]=="LOW" and any(x["low"]<c["extreme_price"]-1e-12 for x in window):
                invalidated_at=t;break
            if c["side"]=="HIGH" and any(x["high"]>c["extreme_price"]+1e-12 for x in window):
                invalidated_at=t;break
            feats=snapshot_features(c,t,sec5,sec_starts,mins,min_starts,h1)
            rows.append({"symbol":symbol,"candidate_id":c["candidate_id"],"side":c["side"],
                         "candidate_ts_ms":c["extreme_ts_ms"],"snapshot_ts_ms":t,"delay_s":d,
                         "extreme_price":c["extreme_price"],"strict_true":bool(c["strict_label_id"]),
                         "strict_label_id":c["strict_label_id"],"internal_true":bool(c["internal_label_id"]),
                         "internal_label_id":c["internal_label_id"],"features":feats})
    return rows

def robust_stats(vals):
    if not vals:return 0.0,1.0
    m=median(vals);mad=median(abs(x-m) for x in vals)
    return m,max(1.4826*mad,abs(m)*0.05,1e-9)

def candidate_first_accept(records,model,start_ms,end_ms):
    grouped=defaultdict(list);true_ids=set()
    for r in records:
        if not start_ms<=r["candidate_ts_ms"]<end_ms:continue
        grouped[r["candidate_id"]].append(r)
        if r["strict_true"]:true_ids.add(r["candidate_id"])
    accepted=[]
    for cid,rr in grouped.items():
        rr.sort(key=lambda x:x["snapshot_ts_ms"])
        for r in rr:
            s=score_record(r,model)
            if s>=model["threshold"]:
                accepted.append((r,s));break
    tp=sum(r["strict_true"] for r,_ in accepted)
    precision=tp/len(accepted) if accepted else 0.0
    recall=tp/len(true_ids) if true_ids else 0.0
    delays=[r["delay_s"] for r,_ in accepted if r["strict_true"]]
    return {"accepted":len(accepted),"true":tp,"false":len(accepted)-tp,
            "precision":precision,"recall":recall,"false_local_rate":1-precision if accepted else None,
            "median_delay_s":median(delays) if delays else None,
            "reference_true_candidates":len(true_ids)}

def score_record(r,model):
    s=0.0;w=0.0
    f=r["features"]
    for name,row in model["features"].items():
        if name not in f:continue
        z=max(-6.0,min(6.0,(f[name]-row["median"])/row["scale"]))
        s+=row["weight"]*z;w+=abs(row["weight"])
    return s/w if w else -999.0

def fit_model(records):
    train=[r for r in records if stamp(DISCOVERY)<=r["candidate_ts_ms"]<stamp(TRAIN_END)]
    valid=[r for r in records if stamp(TRAIN_END)<=r["candidate_ts_ms"]<stamp(OOS)]
    names=sorted({k for r in train for k in r["features"]})
    features={}
    # Sign-stability: feature direction must agree in first and second chronological halves.
    midpoint=(stamp(DISCOVERY)+stamp(TRAIN_END))//2
    halves=[(stamp(DISCOVERY),midpoint),(midpoint,stamp(TRAIN_END))]
    for name in names:
        allv=[r["features"][name] for r in train if name in r["features"]]
        med,scale=robust_stats(allv)
        effects=[]
        for a,b in halves:
            pos=[r["features"][name] for r in train if a<=r["candidate_ts_ms"]<b and r["strict_true"] and name in r["features"]]
            neg=[r["features"][name] for r in train if a<=r["candidate_ts_ms"]<b and not r["strict_true"] and name in r["features"]]
            effects.append((median(pos)-median(neg))/scale if pos and neg else 0.0)
        if effects[0]*effects[1]<=0:continue
        effect=sum(effects)/2
        if abs(effect)<0.05:continue
        features[name]={"median":med,"scale":scale,"weight":max(-3.0,min(3.0,effect)),
                        "half_effects":effects}
    features=dict(sorted(features.items(),key=lambda kv:abs(kv[1]["weight"]),reverse=True)[:20])
    temp={"features":features,"threshold":0.0}
    scores=sorted(score_record(r,temp) for r in valid if score_record(r,temp)>-900)
    thresholds=sorted(set(scores))
    if len(thresholds)>60:
        thresholds=[thresholds[int(i*(len(thresholds)-1)/59)] for i in range(60)]
    best=None
    for th in thresholds:
        temp["threshold"]=th
        m=candidate_first_accept(valid,temp,stamp(TRAIN_END),stamp(OOS))
        if m["accepted"]<3:continue
        delay=(m["median_delay_s"] or 300)/300
        objective=.60*m["precision"]+.35*m["recall"]-.05*delay
        row=(objective,m["precision"],m["recall"],th,m)
        if best is None or row[:3]>best[:3]:best=row
    if best is None:
        th=median(scores) if scores else 0.0
        temp["threshold"]=th
        vm=candidate_first_accept(valid,temp,stamp(TRAIN_END),stamp(OOS))
    else:
        _,_,_,th,vm=best;temp["threshold"]=th
    temp["validation"]=vm
    temp["training_records"]=len(train);temp["validation_records"]=len(valid)
    return temp

def run(symbol,out,cache):
    if symbol not in SYMBOLS:raise ValueError("unsupported symbol")
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    sec5,mins,integrity=aggregate_symbol(symbol,cache)
    if integrity["suspicious_gaps_over_300s"]:
        # Complete official archives can legitimately contain no trades, but long gaps
        # are surfaced and candidate windows that span them are not trusted.
        print(json.dumps({"warning":"long inter-trade gaps observed","count":len(integrity["suspicious_gaps_over_300s"])}),flush=True)
    strict,strict_excl=structural_labels(mins,lookback=6,lookahead=2)
    internal,internal_excl=structural_labels(mins,lookback=3,lookahead=1)
    candidates=build_candidates(mins,strict,internal)
    h1=aggregate_h1(mins)
    records=build_snapshots(symbol,candidates,sec5,mins,h1)
    model=fit_model(records)
    oos=candidate_first_accept(records,model,stamp(OOS),stamp(END))
    discovery=candidate_first_accept(records,model,stamp(DISCOVERY),stamp(OOS))
    availability={
        "contract_points":116,
        "input_ids":sorted(INPUT_IDS),
        "target_eval_ids":sorted(TARGET_IDS),
        "observed_historical_input_ids":sorted(HISTORICAL_OBSERVED_IDS & set(INPUT_IDS)),
        "unavailable_historical_input_ids":{str(i):HISTORICAL_UNAVAILABLE.get(i,"not observed in archive-only historical pass")
                                            for i in sorted(set(INPUT_IDS)-HISTORICAL_OBSERVED_IDS)},
        "rule":"unavailable inputs remain unavailable; no synthetic imputation",
    }
    manifest={"symbol":symbol,"period":[START.isoformat(),END.isoformat()],"discovery_start":DISCOVERY.isoformat(),
              "train_end":TRAIN_END.isoformat(),"oos_start":OOS.isoformat(),
              "integrity":integrity,"minute_bars":len(mins),"five_second_bars":len(sec5),
              "strict_labels":len(strict),"internal_labels":len(internal),"candidates":len(candidates),
              "candidate_snapshots":len(records),"raw_archives_retained":False,
              "compression":"final compact JSONL/JSON gzip level 9","feature_contract":"116-point canonical; availability-aware",
              "future_leakage_guard":"offline labels/points 83..110 never enter feature dictionaries"}
    summary={"symbol":symbol,"manifest":{k:v for k,v in manifest.items() if k!="integrity"},
             "model":model,"discovery":discovery,"oos":oos,
             "top_features":[{"name":k,**v} for k,v in model["features"].items()]}
    write_json(out/"manifest.json",manifest)
    write_json(out/"feature_availability.json",availability)
    write_json(out/"summary.json",summary)
    write_json_gz(out/"labels.json.gz",{"strict":strict,"strict_exclusions":strict_excl,
                                        "internal":internal,"internal_exclusions":internal_excl})
    write_jsonl_gz(out/"compact_1m.jsonl.gz",mins)
    write_jsonl_gz(out/"candidate_snapshots.jsonl.gz",records)
    # No full 5-second stream is persisted. It is deliberately discarded after candidate extraction.
    artifact_manifest={}
    for p in sorted(out.iterdir()):
        if p.is_file():
            artifact_manifest[p.name]={"bytes":p.stat().st_size,"sha256":sha256(p)}
    write_json(out/"artifact_manifest.json",artifact_manifest)
    print("LOCAL116_RESULT="+json.dumps({"symbol":symbol,"strict_labels":len(strict),"candidates":len(candidates),
          "snapshots":len(records),"top_features":list(model["features"])[:10],"discovery":discovery,"oos":oos},
          separators=(",",":"),sort_keys=True),flush=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--symbol",required=True)
    ap.add_argument("--output",required=True,type=Path)
    ap.add_argument("--cache",required=True,type=Path)
    args=ap.parse_args()
    run(args.symbol.upper(),args.output,args.cache)

if __name__=="__main__":
    main()
