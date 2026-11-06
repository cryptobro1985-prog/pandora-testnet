from __future__ import annotations
import gzip, heapq, json, math
from collections import deque
from pathlib import Path

from research.hype_local_v5.decode_compact import manifest,chunk_meta,stream_meta,decode_events,decode_table
from research.hype_quant.features import FeatureState
from research.hype_quant.agents import augment_with_agents
from research.hype_quant.bootstrap_30d_unified import historical_states, load_jsonl_gz
from research.hype_quant.learner import OnlineQuantLearner, load_config, clean_features
from .technical import causal_indicator_map, indicator_series, resample

def write_jsonl_gz(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(path,"wt",encoding="utf-8",compresslevel=6) as f:
        for r in rows:
            f.write(json.dumps(r,separators=(",",":"),allow_nan=False)+"\n")

def _apply_kline(state,row):
    topic=str(row.get("topic") or "")
    parts=topic.split(".")
    tf=parts[1] if len(parts)>=3 else ""
    if tf not in state.candles:return
    recv=int(row.get("received_ts_ms") or 0)
    store=state.candles[tf]
    for b in row.get("data") or []:
        if not isinstance(b,dict):continue
        start=int(b.get("start") or 0)
        try:
            vals={k:float(b.get(k)) for k in ("open","high","low","close","volume","turnover") if b.get(k) is not None}
        except Exception:
            continue
        if start<=0 or not all(k in vals for k in ("open","high","low","close")):continue
        store[start]={"start_ms":start,**vals,"confirm":1.0 if b.get("confirm") else 0.0,
                      "received_ts_ms":recv,"source_timestamp_ms":int(b.get("timestamp") or row.get("exchange_ts_ms") or recv)}
    keep=600 if tf=="1" else 300 if tf=="3" else 220 if tf=="5" else 100
    if len(store)>keep:
        for k in sorted(store)[:-keep]:store.pop(k,None)

def _technical_from_state(state,now_ms):
    # Only completed candles may be used.
    m1=[]
    for k in sorted(state.candles["1"]):
        b=state.candles["1"][k]
        if k+60_000<=now_ms:
            m1.append({"ts_ms":k,"open":b["open"],"high":b["high"],"low":b["low"],"close":b["close"],
                       "volume":b.get("volume",0) or 0,"turnover":b.get("turnover",0) or 0})
    if len(m1)<15:return {}
    out={}
    for tf in (5,15,60):
        rs=resample(m1,tf)[-120:]
        if not rs:continue
        series=indicator_series(rs)
        if not series:continue
        last=series[-1]
        span=tf*60_000
        if last["ts_ms"]+span>now_ms:continue
        for k,v in last.items():
            if k!="ts_ms":
                out[f"tech_{tf}m_{k}"]=float(v)
    return out

def build_historical(root:Path):
    bars=load_jsonl_gz(root/"compact_1m.jsonl.gz")
    candidates=load_jsonl_gz(root/"candidate_snapshots.jsonl.gz")
    minute=[]
    for b in bars:
        minute.append({
            "ts_ms":int(b["bar_end_ms"])-60_000,
            "open":float(b["open"]),"high":float(b["high"]),"low":float(b["low"]),"close":float(b["close"]),
            "volume":float(b.get("volume",0) or 0),"turnover":float(b.get("turnover",0) or 0),
        })
    tech=causal_indicator_map(minute)
    rows=[]
    for ts,px,x,b in historical_states(bars,candidates):
        x=dict(x);x.update(tech.get(ts,{}))
        x=augment_with_agents(x)
        rows.append({"ts_ms":int(ts),"price":float(px),"high":float(b["high"]),"low":float(b["low"]),
                     "features":x,"source":"historical_30d"})
    return rows

def _stream_iter(pkg:Path,chunk,name):
    m=manifest(pkg);c=chunk_meta(m,chunk)
    sm=stream_meta(c,name)
    p=pkg/"chunks"/chunk/name
    if name=="events.mpk.xz":
        for row in decode_events(p,sm):
            ts=int(row.get("received_ts_ms") or row.get("exchange_ts_ms") or 0)
            if ts:yield ts,0,"event",row
    else:
        kind={"microstructure_1s.mpk.xz":"micro","market_context_1m.mpk.xz":"market",
              "structural_context_1m.mpk.xz":"struct"}[name]
        for row in decode_table(p):
            ts=int(row.get("received_ts_ms") or row.get("ts_ms") or 0)
            if ts:yield ts,{"market":1,"struct":2,"micro":3}[kind],kind,row

def replay_package(pkg:Path,state:FeatureState,next_sample_ms=0,sample_ms=5000):
    m=manifest(pkg);out=[];tech_cache={};last_tech_min=None
    for ch in m["chunks"]:
        chunk=ch["chunk"];iters=[]
        names={s["name"] for s in ch["streams"]}
        for name in ("events.mpk.xz","market_context_1m.mpk.xz","structural_context_1m.mpk.xz","microstructure_1s.mpk.xz"):
            if name in names:
                it=iter(_stream_iter(pkg,chunk,name))
                try:first=next(it)
                except StopIteration:continue
                iters.append([first,it])
        heap=[]
        for idx,(item,it) in enumerate(iters):heapq.heappush(heap,(item[0],item[1],idx,item[2],item[3]))
        while heap:
            ts,prio,idx,kind,row=heapq.heappop(heap)
            it=iters[idx][1]
            try:n=next(it);heapq.heappush(heap,(n[0],n[1],idx,n[2],n[3]))
            except StopIteration:pass
            if kind=="event":
                if row.get("kind")=="kline":_apply_kline(state,row)
                else:state.update_event(row)
            elif kind=="market":state.update_market_context(row)
            elif kind=="struct":state.update_structural_context(row)
            else:
                try:px,x=state.update_micro(row)
                except Exception:continue
                if ts<next_sample_ms:continue
                next_sample_ms=ts+sample_ms
                minute=ts//60_000
                if minute!=last_tech_min:
                    tech_cache=_technical_from_state(state,ts);last_tech_min=minute
                x.update(tech_cache)
                x=augment_with_agents(x)
                out.append({"ts_ms":ts,"price":float(px),"high":float(px),"low":float(px),
                            "features":x,"source":"live_full116"})
    return out,next_sample_ms

def build_live_phase(root:Path,phase:str):
    state=FeatureState();rows=[];next_sample=0
    for seg in sorted((root/phase).glob("segment_*")):
        pkg=seg/"package"
        if not (pkg/"PACK_MANIFEST.json").exists():continue
        rr,next_sample=replay_package(pkg,state,next_sample,5000)
        rows.extend(rr)
    return rows


DISCOVERY=1791676800000
TRAIN_END=1792713600000

def _quant_prediction_features(learner,x):
    xx=clean_features(x)
    scales={60:.0015,180:.0030,300:.0045,600:.0070,900:.0100,1800:.0150}
    weights={60:.10,180:.15,300:.25,600:.20,900:.15,1800:.15}
    direction=confidence=ret_score=0.0
    out={}
    for h in learner.horizons:
        p=learner.challenger[h].predict(xx)
        ds=(2*p.p_up-1.0)*.40 + __import__("math").tanh(p.expected_return/max(scales[h],1e-9))*.60
        w=weights[h]
        direction+=w*ds
        confidence+=w*abs(2*p.p_up-1.0)
        ret_score+=w*__import__("math").tanh(p.expected_return/max(scales[h],1e-9))
        out[f"quant_p_up_{h}s"]=float(p.p_up)
        out[f"quant_expected_return_{h}s"]=float(p.expected_return)
        out[f"quant_expected_max_up_{h}s"]=float(p.expected_max_up)
        out[f"quant_expected_max_down_{h}s"]=float(p.expected_max_down)
    out["quant_direction"]=max(-1.0,min(1.0,direction))
    out["quant_confidence"]=max(0.0,min(1.0,confidence))
    out["quant_return_score"]=max(-1.0,min(1.0,ret_score))
    return out

def add_frozen_quant_overlay(hist,cal,hold):
    cfg=load_config(Path("research/hype_quant/config.json"))
    learner=OnlineQuantLearner(cfg)
    learner.config["action_space"]["leverage"]=[1]
    learner.config["action_space"]["margin_fraction"]=[.02]
    learner.memory.neighbors=10**9
    # Walk-forward predictions before each historical update. Training freezes at
    # TRAIN_END; validation/OOS/live never update the model.
    for r in sorted(hist,key=lambda z:z["ts_ms"]):
        x=r["features"]
        qf=_quant_prediction_features(learner,x)
        if int(r["ts_ms"])<TRAIN_END:
            learner.observe(int(r["ts_ms"]),float(r["price"]),x)
        x.update(qf)
    learner.pending.clear()
    for rows in (cal,hold):
        for r in rows:
            r["features"].update(_quant_prediction_features(learner,r["features"]))
    return {"labels":learner.labels,"promotions":learner.promotions,"champion_ready":learner.champion_ready}


def _num(v):
    try:
        x=float(v);return x if math.isfinite(x) else None
    except Exception:return None

def _flatten_numeric(prefix,obj,out,depth=0):
    if depth>3:return
    if isinstance(obj,dict):
        for k,v in obj.items():_flatten_numeric(prefix+"_"+str(k),v,out,depth+1)
    else:
        v=_num(obj)
        if v is not None:out[prefix]=v

def _value_at(hist,target):
    out=None
    for ts,v in reversed(hist):
        if ts<=target:return v
    return out

def _tech_from_minutes(minutes,now_ms):
    if len(minutes)<20:return {}
    out={}
    for tf in (5,15,60):
        rs=resample(minutes[-720:],tf)
        if not rs:continue
        s=indicator_series(rs)
        if not s:continue
        last=s[-1];span=tf*60_000
        if last["ts_ms"]+span>now_ms and len(s)>1:last=s[-2]
        for k,v in last.items():
            if k!="ts_ms" and _num(v) is not None:out[f"tech_{tf}m_{k}"]=float(v)
    return out

def build_live_phase_fast(root:Path,phase:str):
    rows=[];next_sample=0
    price_hist=deque(maxlen=5000);oi_hist=deque(maxlen=5000);flow_hist=deque(maxlen=5000)
    minute_bars=[];current_minute=None;bar=None;tech={}
    latest_struct={};latest_market={}
    for seg in sorted((root/phase).glob("segment_*")):
        pkg=seg/"package"
        if not (pkg/"PACK_MANIFEST.json").exists():continue
        m=manifest(pkg)
        for ch in sorted((x["chunk"] for x in m["chunks"])):
            meta=chunk_meta(m,ch);names={s["name"] for s in meta["streams"]}
            structs=[];markets=[]
            if "structural_context_1m.mpk.xz" in names:
                sm=stream_meta(meta,"structural_context_1m.mpk.xz")
                structs=list(decode_table(pkg/"chunks"/ch/"structural_context_1m.mpk.xz"))
            if "market_context_1m.mpk.xz" in names:
                mm=stream_meta(meta,"market_context_1m.mpk.xz")
                markets=list(decode_table(pkg/"chunks"/ch/"market_context_1m.mpk.xz"))
            si=mi=0
            if "microstructure_1s.mpk.xz" not in names:continue
            micro=list(decode_table(pkg/"chunks"/ch/"microstructure_1s.mpk.xz"))
            for mr in micro:
                ts=int(mr.get("ts_ms") or 0)
                px=_num(mr.get("mid")) or _num(mr.get("best_bid")) or _num(mr.get("best_ask"))
                if ts<=0 or not px:continue
                while si<len(structs) and int(structs[si].get("ts_ms") or 0)<=ts:
                    latest_struct=structs[si];si+=1
                while mi<len(markets) and int(markets[mi].get("received_ts_ms") or markets[mi].get("ts_ms") or 0)<=ts:
                    latest_market=markets[mi];mi+=1

                minute=(ts//60_000)*60_000
                if current_minute is None:
                    current_minute=minute;bar={"ts_ms":minute,"open":px,"high":px,"low":px,"close":px,"volume":0.0,"turnover":0.0}
                elif minute!=current_minute:
                    minute_bars.append(bar)
                    if len(minute_bars)>1600:minute_bars=minute_bars[-1600:]
                    tech=_tech_from_minutes(minute_bars,ts)
                    current_minute=minute;bar={"ts_ms":minute,"open":px,"high":px,"low":px,"close":px,"volume":0.0,"turnover":0.0}
                else:
                    bar["high"]=max(bar["high"],px);bar["low"]=min(bar["low"],px);bar["close"]=px

                if ts<next_sample:continue
                next_sample=ts+5000
                price_hist.append((ts,px))
                oi=_num(mr.get("open_interest"))
                if oi is not None:oi_hist.append((ts,oi))
                f60=_num(mr.get("flow_imbalance_60s"))
                if f60 is not None:flow_hist.append((ts,f60))

                x={}
                for k,v in mr.items():
                    nv=_num(v)
                    if nv is not None:x[k]=nv
                x.update(tech)
                x["flow_imbalance_raw_15s"]=_num(mr.get("flow_imbalance_15s")) or 0.0
                x["flow_imbalance_raw_60s"]=_num(mr.get("flow_imbalance_60s")) or 0.0
                recent_flow=[v for t,v in flow_hist if t>=ts-300_000]
                x["flow_imbalance_raw_300s"]=sum(recent_flow)/len(recent_flow) if recent_flow else x["flow_imbalance_raw_60s"]
                x["bid_absorption_proxy_60s"]=_num(mr.get("bid_replenishment_proxy_ratio_60s")) or 0.0
                x["ask_absorption_proxy_60s"]=_num(mr.get("ask_replenishment_proxy_ratio_60s")) or 0.0
                x["book_bid_add_60s"]=_num(mr.get("bid_add_notional")) or 0.0
                x["book_ask_add_60s"]=_num(mr.get("ask_add_notional")) or 0.0
                x["book_bid_cancel_60s"]=_num(mr.get("bid_cancel_notional")) or 0.0
                x["book_ask_cancel_60s"]=_num(mr.get("ask_cancel_notional")) or 0.0
                x["liq_long_notional_raw_60s"]=_num(mr.get("long_liq_notional_60s")) or 0.0
                x["liq_short_notional_raw_60s"]=_num(mr.get("short_liq_notional_60s")) or 0.0

                for sec in (30,60,180,300,900):
                    old=_value_at(price_hist,ts-sec*1000)
                    if old and old>0:
                        ret=px/old-1.0;x[f"ret_{sec}s"]=ret
                    pp=[(t,p) for t,p in price_hist if t>=ts-sec*1000]
                    if len(pp)>=2:
                        vals=[p for _,p in pp];hh=max(vals);ll=min(vals);span=max(hh-ll,1e-12)
                        hi_t=max(pp,key=lambda z:z[1])[0];lo_t=min(pp,key=lambda z:z[1])[0]
                        x[f"survival_since_high_{sec}s"]=(ts-hi_t)/1000.0
                        x[f"survival_since_low_{sec}s"]=(ts-lo_t)/1000.0
                        x[f"retracement_from_high_{sec}s"]=(hh-px)/span
                        x[f"retracement_from_low_{sec}s"]=(px-ll)/span
                        diffs=[b/a-1 for a,b in zip(vals,vals[1:]) if a>0]
                        if diffs:
                            x[f"positive_persistence_{sec}s"]=sum(d>0 for d in diffs)/len(diffs)
                            x[f"negative_persistence_{sec}s"]=sum(d<0 for d in diffs)/len(diffs)

                bn=_num(mr.get("buy_notional_60s")) or 0.0;sn=_num(mr.get("sell_notional_60s")) or 0.0
                r60=x.get("ret_60s",0.0)
                if bn>0:x["buy_efficiency_60s"]=max(r60,0.0)/bn
                if sn>0:x["sell_efficiency_60s"]=max(-r60,0.0)/sn
                x["buy_efficiency_300s"]=x.get("buy_efficiency_60s",0.0)
                x["sell_efficiency_300s"]=x.get("sell_efficiency_60s",0.0)

                if oi is not None:
                    for sec in (60,300):
                        past=_value_at(oi_hist,ts-sec*1000)
                        if past and past>0:
                            d=oi/past-1.0;x[f"oi_delta_{sec}s"]=d
                            rr=x.get(f"ret_{sec}s")
                            if rr is not None:x[f"price_oi_interaction_{sec}s"]=rr*d

                if latest_struct:_flatten_numeric("struct",latest_struct,x)
                if latest_market:
                    ar=latest_market.get("account_ratio")
                    if isinstance(ar,dict):_flatten_numeric("account",ar,x)
                    st=latest_market.get("server_time")
                    if isinstance(st,dict):_flatten_numeric("server",st,x)
                    inst=latest_market.get("instrument")
                    if isinstance(inst,dict):_flatten_numeric("instrument",inst,x)

                if len(price_hist)>0:
                    vals60=[p for t,p in price_hist if t>=ts-3_600_000]
                    if vals60:
                        hi=max(vals60);lo=min(vals60)
                        x["rolling_60m_high"]=hi;x["rolling_60m_low"]=lo
                        x["dist_rolling_60m_high"]=px/hi-1.0;x["dist_rolling_60m_low"]=px/lo-1.0

                x=augment_with_agents(x)
                rows.append({"ts_ms":ts,"price":px,"high":px,"low":px,"features":x,"source":"live_full116_fast"})
    return rows

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--historical-root",type=Path,required=True)
    ap.add_argument("--live-root",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    hist=build_historical(args.historical_root)
    cal=build_live_phase_fast(args.live_root,"calibration")
    hold=build_live_phase_fast(args.live_root,"holdout")
    quant=add_frozen_quant_overlay(hist,cal,hold)
    write_jsonl_gz(args.output/"historical.jsonl.gz",hist)
    write_jsonl_gz(args.output/"calibration.jsonl.gz",cal)
    write_jsonl_gz(args.output/"holdout.jsonl.gz",hold)
    summary={"historical_rows":len(hist),"calibration_rows":len(cal),"holdout_rows":len(hold),"quant_overlay":quant,
             "historical_first":hist[0]["ts_ms"] if hist else None,"historical_last":hist[-1]["ts_ms"] if hist else None,
             "calibration_first":cal[0]["ts_ms"] if cal else None,"calibration_last":cal[-1]["ts_ms"] if cal else None,
             "holdout_first":hold[0]["ts_ms"] if hold else None,"holdout_last":hold[-1]["ts_ms"] if hold else None,
             "anti_leakage":"search tunes on historical train/validation + calibration; holdout is report/gate only"}
    (args.output/"DATASET_SUMMARY.json").write_text(json.dumps(summary,indent=2)+"\n")
    print("ONLY_PROFIT_DATASET="+json.dumps(summary,separators=(",",":")))

if __name__=="__main__":
    main()
