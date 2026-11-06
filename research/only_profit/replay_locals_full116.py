from __future__ import annotations
import argparse,bisect,json,lzma,math
from collections import defaultdict
from pathlib import Path
import msgpack

from research.hype_local_v5.labels import structural_labels

def unpack(path):
    with lzma.LZMAFile(path,"rb") as f:
        yield from msgpack.Unpacker(f,raw=False,strict_map_key=False)

def manifest(pkg): return json.loads((pkg/"PACK_MANIFEST.json").read_text())
def stream_meta(c,name):
    for s in c["streams"]:
        if s["name"]==name:return s
    raise KeyError(name)

def decode_table(path):
    it=iter(unpack(path));head=next(it,None)
    if not head or head[0]!="__keys__":return
    keys=head[1]
    for row in it:
        yield {k:v for k,v in zip(keys,row) if v is not None}

def decode_events(path,meta):
    ps,qs=meta["price_scale"],meta["qty_scale"]
    pb={"recv":0,"ets":0,"u":0,"seq":0};fb=True;lp={"b":0,"a":0}
    pt={"recv":0,"ts":0,"seq":0};ft=True
    pl={"recv":0,"ts":0};fl=True
    for r in unpack(path):
        typ=r[0]
        if typ==0:
            snap,dr,de,du,ds,bids,asks=r[1:]
            if fb:recv,ets,u,seq=dr,de,du,ds;fb=False
            else:recv,ets,u,seq=pb["recv"]+dr,pb["ets"]+de,pb["u"]+du,pb["seq"]+ds
            pb.update(recv=recv,ets=ets,u=u,seq=seq)
            for side,rows in (("b",bids),("a",asks)):
                for dp,q in rows:lp[side]+=dp
        elif typ==1:
            dr,dt,ds,*rest=r[1:]
            if ft:recv,ts,seq=dr,dt,ds;ft=False
            else:recv,ts,seq=pt["recv"]+dr,pt["ts"]+dt,pt["seq"]+ds
            pt.update(recv=recv,ts=ts,seq=seq)
        elif typ==2:
            dr,dt,*rest=r[1:]
            if fl:recv,ts=dr,dt;fl=False
            else:recv,ts=pl["recv"]+dr,pl["ts"]+dt
            pl.update(recv=recv,ts=ts)
        elif typ==4:
            yield {"received_ts_ms":r[1],"exchange_ts_ms":r[2],"topic":r[3],"data":r[4]}

def collect(root):
    klines={};micro={}
    for phase in ("calibration","holdout"):
        for seg in sorted((root/phase).glob("segment_*")):
            pkg=seg/"package"
            if not (pkg/"PACK_MANIFEST.json").exists():continue
            m=manifest(pkg)
            for c in m["chunks"]:
                names={s["name"] for s in c["streams"]}
                cd=pkg/"chunks"/c["chunk"]
                if "events.mpk.xz" in names:
                    sm=stream_meta(c,"events.mpk.xz")
                    for ev in decode_events(cd/"events.mpk.xz",sm):
                        if ev["topic"]!="kline.1.HYPEUSDT":continue
                        for b in ev["data"]:
                            start=int(b.get("start") or 0)
                            if start and (start not in klines or ev["received_ts_ms"]>klines[start][0]):
                                klines[start]=(ev["received_ts_ms"],b)
                if "microstructure_1s.mpk.xz" in names:
                    for r in decode_table(cd/"microstructure_1s.mpk.xz"):
                        ts=int(r.get("ts_ms") or 0)
                        if ts and r.get("mid") is not None:micro[ts]=r
    bars=[]
    for start in sorted(klines):
        b=klines[start][1]
        bars.append({"start_ms":start,"ts_ms":start+60000,"bar_end_ms":start+60000,
                     "interval_ms":60000,"gap":False,
                     "open":float(b["open"]),"high":float(b["high"]),"low":float(b["low"]),"close":float(b["close"]),
                     "volume":float(b.get("volume") or 0),"turnover":float(b.get("turnover") or 0)})
    return bars,micro

def nearest(micro,t):
    keys=sorted(micro);i=bisect.bisect_left(keys,t);cand=[]
    if i<len(keys):cand.append(keys[i])
    if i:cand.append(keys[i-1])
    if not cand:return {}
    return micro[min(cand,key=lambda x:abs(x-t))]

def full116_evidence(side,r):
    sign=1 if side=="LOW" else -1;votes=[]
    for k in ("flow_imbalance_60s","book_imbalance_5","book_imbalance_25"):
        v=r.get(k)
        if isinstance(v,(int,float)) and math.isfinite(v):votes.append(1.0 if v*sign>0 else 0.0)
    bid=r.get("bid_replenishment_proxy_ratio_60s");ask=r.get("ask_replenishment_proxy_ratio_60s")
    if isinstance(bid,(int,float)) and isinstance(ask,(int,float)):
        votes.append(1.0 if (bid>=ask if side=="LOW" else ask>=bid) else 0.0)
    ll=float(r.get("long_liq_notional_60s") or 0);sl=float(r.get("short_liq_notional_60s") or 0)
    if ll+sl>0:votes.append(1.0 if (ll>=sl if side=="LOW" else sl>=ll) else 0.0)
    return sum(votes)/len(votes) if votes else None

def match_strict(c,labels):
    for x in labels:
        if x["side"]!=c["side"]:continue
        if x["extreme_interval_start_ms"]<=c["candidate_ts_ms"]<x["extreme_interval_end_ms"]:
            if abs(float(x["extreme_price"])-float(c["extreme_price"]))<=0.01:return True
    return False

def detect(bars,micro,labels):
    out=[];lows=[];highs=[]
    for i,r in enumerate(bars):
        if i<360:lows.append(r["low"]);highs.append(r["high"]);continue
        prev_low=min(lows[-360:]);prev_high=max(highs[-360:])
        made=[]
        if r["low"]<prev_low:made.append(("LOW",r["low"]))
        if r["high"]>prev_high:made.append(("HIGH",r["high"]))
        for side,px in made:
            c={"side":side,"candidate_ts_ms":r["start_ms"],"extreme_price":px,
               "strict_h1_local":False,"stages":[],"invalidated_at_ms":None}
            c["strict_h1_local"]=match_strict(c,labels)
            for delay,stage,min_ev in ((300,"FORMING",0.0),(600,"CONFIRMED",0.50),(900,"HARD_CONFIRMED",0.50)):
                n=delay//60
                if i+n>=len(bars):continue
                w=bars[i+1:i+n+1]
                ext=any(x["low"]<px-1e-12 for x in w) if side=="LOW" else any(x["high"]>px+1e-12 for x in w)
                if ext:break
                cur=bars[i+n]["close"];sign=1 if side=="LOW" else -1
                retr=(cur/px-1)*sign*10000
                snap=nearest(micro,bars[i+n]["ts_ms"])
                ev=full116_evidence(side,snap)
                if retr>=35 and (ev is None or ev>=min_ev):
                    c["stages"].append({"stage":stage,"delay_s":delay,"snapshot_ts_ms":bars[i+n]["ts_ms"],
                                       "retrace_bps":retr,"full116_evidence":ev,
                                       "flow60":snap.get("flow_imbalance_60s"),
                                       "book5":snap.get("book_imbalance_5"),"book25":snap.get("book_imbalance_25"),
                                       "oi_change_pct":snap.get("oi_change_since_prev_poll_pct"),
                                       "long_liq60":snap.get("long_liq_notional_60s"),
                                       "short_liq60":snap.get("short_liq_notional_60s")})
            for q in bars[i+1:]:
                broken=q["low"]<px-1e-12 if side=="LOW" else q["high"]>px+1e-12
                if broken:c["invalidated_at_ms"]=q["start_ms"];break
            if c["stages"]:out.append(c)
        lows.append(r["low"]);highs.append(r["high"])
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    bars,micro=collect(args.root)
    labels,excluded=structural_labels(bars,lookback=6,lookahead=2)
    candidates=detect(bars,micro,labels)
    strict=[c for c in candidates if c["strict_h1_local"]]
    report={"symbol":"HYPEUSDT","minute_bars":len(bars),"micro_snapshots":len(micro),
            "strict_labels":labels,"strict_exclusions":excluded,"candidates":candidates,
            "strict_detected":strict,
            "rule_note":"35 bps retracement + 5/10/15m survival skeleton from 30d research; full116 evidence is diagnostic, not a probability."}
    (args.output/"HYPE_FULL116_LOCALS.json").write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("HYPE_FULL116_LOCALS="+json.dumps({"strict_labels":len(labels),"strict_detected":len(strict),
          "strict":[{"side":x["side"],"ts":x["candidate_ts_ms"],"price":x["extreme_price"],
                     "stages":[s["stage"] for s in x["stages"]]} for x in strict],
          "all_stage_candidates":len(candidates)},separators=(",",":")))

if __name__=="__main__":main()
