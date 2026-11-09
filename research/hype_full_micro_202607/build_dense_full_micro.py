from __future__ import annotations

import argparse, json, math, os, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.hype_full_micro_202607 import build_full_micro as base
from research.hype_quant.feature_contract import INPUT_IDS, TARGET_IDS, METADATA_IDS

# Sampling timestamps are observation points for historical reconstruction only.
# They NEVER gate live entry eligibility.
OBSERVATION_DELAYS=(0,5,15,30,60,120,180,300,600)
RETRACE_ANCHORS_BPS=(25,30,33,35,38,45,60)


def dense_swing_candidates(mins, labels):
    """Every new target-side running extreme inside each completed strict swing.

    Teacher labels only define offline episode boundaries/targets. They are not
    exposed to feature generation. A candidate is invalidated immediately when a
    more extreme same-side candidate appears, matching live signature semantics.
    """
    labs=[dict(x) for x in labels if bool(x.get("reference_finalized",True))]
    labs.sort(key=lambda x:int(x["extreme_interval_start_ms"]))
    out=[]
    for i in range(1,len(labs)):
        prev,target=labs[i-1],labs[i]
        side=str(target["side"])
        left=int(prev["extreme_interval_start_ms"])
        right=int(target["extreme_interval_end_ms"])
        running=None
        episode=[]
        for r in mins:
            st=int(r["start_ms"])
            end=int(r.get("bar_end_ms",r.get("ts_ms",st+60_000)))
            if end<=left: continue
            if st>right: break
            if side=="LOW":
                px=float(r["low"]);ts=int(r.get("low_ts_ms",st))
                better=running is None or px<running
            else:
                px=float(r["high"]);ts=int(r.get("high_ts_ms",st))
                better=running is None or px>running
            if not better or ts<=left or ts>right:
                continue
            running=px
            item={
                "side":side,"extreme_price":px,"extreme_ts_ms":ts,
                "candidate_id":f"DENSE-{side[0]}-{ts}",
                "target_label_id":int(target["label_id"]),
                "episode":i,
                "strict_label_id":None,
                "invalidated_at_ms":None,
            }
            if (int(target["extreme_interval_start_ms"])<=ts<=int(target["extreme_interval_end_ms"])
                    and math.isclose(px,float(target["extreme_price"]),rel_tol=1e-10,abs_tol=1e-8)):
                item["strict_label_id"]=int(target["label_id"])
            if episode:
                episode[-1]["invalidated_at_ms"]=ts
            episode.append(item)
        out.extend(episode)
    return [c for c in out if int(c["extreme_ts_ms"])>=base.ms(base.START)]


def target_records(cands,sec5,mins):
    out=[]
    end_ms=base.ms(base.END)
    starts=[int(x["start_ms"]) for x in sec5]

    for c in cands:
        invalidated=c.get("invalidated_at_ms")
        stop=min(end_ms,int(invalidated) if invalidated is not None else end_ms)

        # Generic observation snapshots remain for trajectory learning.
        for d in OBSERVATION_DELAYS:
            t=int(c["extreme_ts_ms"])+int(d)*1000
            if t>=stop: break
            out.append({
                "symbol":"HYPE","candidate_id":c["candidate_id"],"side":c["side"],
                "candidate_ts_ms":int(c["extreme_ts_ms"]),"snapshot_ts_ms":t,
                "delay_s":int(d),"extreme_price":float(c["extreme_price"]),
                "strict_true":bool(c["strict_label_id"]),
                "strict_label_id":c["strict_label_id"],
                "target_label_id":int(c["target_label_id"]),
                "episode":int(c["episode"]),
                "invalidated_at_ms":c.get("invalidated_at_ms"),
                "observation_kind":"TIME_SAMPLE",
                "retrace_anchor_bps":None,
                "features":base.base_features(c,t,sec5,mins),
            })

        # Adaptive event snapshots: capture the *first causal state* at which
        # price has retraced 0.25/0.30/0.33/0.35/... from the running extreme.
        # These anchors are NOT Local confirmation rules. They are observation
        # events where the complete causal signature is sampled and compared.
        cp=float(c["extreme_price"])
        rev=1.0 if c["side"]=="LOW" else -1.0
        lo=bisect.bisect_left(starts,int(c["extreme_ts_ms"])-5000)
        hi=bisect.bisect_left(starts,stop)
        pending=set(RETRACE_ANCHORS_BPS)
        for bar in sec5[max(0,lo):hi]:
            t=int(bar.get("bar_end_ms",bar.get("ts_ms",int(bar["start_ms"])+5000)))
            if t<=int(c["extreme_ts_ms"]):
                continue
            px=float(bar["close"])
            retr=(px/cp-1.0)*rev*10000.0
            if retr<min(pending or {10**9}):
                continue
            reached=sorted(a for a in pending if retr>=a)
            for anchor in reached:
                out.append({
                    "symbol":"HYPE","candidate_id":c["candidate_id"],"side":c["side"],
                    "candidate_ts_ms":int(c["extreme_ts_ms"]),"snapshot_ts_ms":t,
                    "delay_s":max(0.0,(t-int(c["extreme_ts_ms"]))/1000.0),
                    "extreme_price":cp,
                    "strict_true":bool(c["strict_label_id"]),
                    "strict_label_id":c["strict_label_id"],
                    "target_label_id":int(c["target_label_id"]),
                    "episode":int(c["episode"]),
                    "invalidated_at_ms":c.get("invalidated_at_ms"),
                    "observation_kind":"RETRACE_CROSS",
                    "retrace_anchor_bps":int(anchor),
                    "features":base.base_features(c,t,sec5,mins),
                })
                pending.remove(anchor)
            if not pending:
                break
    return out


def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--cache",type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    src=base.Source(args.cache,os.getenv("CRYPTOHFTDATA_API_KEY"))

    base.prefetch_hours(src,base.START-timedelta(hours=24),base.END,("trades",))
    sec5,mins,schemas=base.load_trades(src)
    strict,strict_exc=base.structural_labels(mins,lookback=6,lookahead=2)
    cands=dense_swing_candidates(mins,strict)
    records=target_records(cands,sec5,mins)

    print(json.dumps({
        "dense_candidates":len(cands),"dense_snapshots":len(records),
        "true_candidates":sum(bool(x["strict_label_id"]) for x in cands),
        "false_candidates":sum(not bool(x["strict_label_id"]) for x in cands),
        "observation_delays":OBSERVATION_DELAYS,
    }),flush=True)

    # Continuous L50 is needed for causal book reconstruction.
    base.prefetch_hours(src,base.START-timedelta(hours=24),base.END,("orderbook",))
    candidate_hours=sorted({
        datetime.fromtimestamp(r["snapshot_ts_ms"]/1000,tz=timezone.utc).replace(minute=0,second=0,microsecond=0)
        for r in records
    })
    aux_hours=sorted(set(candidate_hours)|{h-timedelta(hours=1) for h in candidate_hours})
    if aux_hours:
        with ThreadPoolExecutor(max_workers=(8 if src.api_key else 2)) as ex:
            futs=[]
            for dt in aux_hours:
                for kind in ("liquidations","open_interest","mark_price","ticker"):
                    futs.append(ex.submit(src.get,dt,kind,False))
            for n,fut in enumerate(as_completed(futs),1):
                fut.result()
                if n%100==0:
                    print(json.dumps({"aux_prefetch_done":n,"aux_prefetch_total":len(futs),
                                      "downloads":src.downloads,"bytes":src.bytes}),flush=True)

    ratio_rows=base.fetch_account_ratio()
    records=base.attach_account_ratio(records,ratio_rows)
    records=base.enrich(src,records,schemas)

    observed=set(range(1,44))|{77,78,79,80,116}
    if src.counts.get("orderbook",0) and any(r["features"].get("fullmicro_book_valid")==1.0 for r in records):
        observed|=set(range(44,58))
    if src.counts.get("open_interest",0): observed|={58,59,60,61,115}
    if src.counts.get("mark_price",0): observed|={2,3,62,114}
    if src.counts.get("ticker",0): observed|={63,64}
    if any(r["features"].get("fullmicro_liq_stream_valid_5s")==1.0 for r in records):
        observed|=set(range(65,77))
    if ratio_rows: observed|={113}

    availability={
        "points_total":116,"causal_input_points":len(INPUT_IDS),
        "target_eval_points":len(TARGET_IDS),"metadata_points":len(METADATA_IDS),
        "historically_observed_or_derived_input_ids":sorted(observed&set(INPUT_IDS)),
        "missing_input_ids":sorted(set(INPUT_IDS)-observed),
        "source_file_counts":dict(src.counts),
        "candidate_contract":"DENSE_STRICT_SWING_RUNNING_EXTREME_V1",
        "observation_delays_metric_only":list(OBSERVATION_DELAYS),
        "retrace_anchors_bps":list(RETRACE_ANCHORS_BPS),
        "retrace_anchor_role":"event snapshot only; never sufficient Local confirmation",
        "retrace_anchors_bps":list(RETRACE_ANCHORS_BPS),
        "retrace_anchor_role":"event snapshot only; never sufficient Local confirmation",
        "note":"Teacher defines offline swing/target only; target/eval values never enter X. Same-side replacement truncates old candidate states.",
    }
    base.write_jsonl_gz(args.output/"candidate_snapshots_full_micro.jsonl.gz",records)
    base.write_jsonl_gz(args.output/"compact_1m.jsonl.gz",[r for r in mins if r["start_ms"]>=base.ms(base.START)])
    base.write_json_gz(args.output/"labels.json.gz",{"strict":strict,"strict_exclusions":strict_exc})
    (args.output/"feature_availability.json").write_text(json.dumps(availability,indent=2)+"\n")

    manifest={
        "symbol":base.SYMBOL,"period":[base.START.isoformat(),base.END.isoformat()],
        "strict_labels":len(strict),
        "strict_finalized_labels":sum(bool(x.get("reference_finalized",True)) for x in strict),
        "candidates":len(cands),"true_candidates":sum(bool(x["strict_label_id"]) for x in cands),
        "false_candidates":sum(not bool(x["strict_label_id"]) for x in cands),
        "snapshots":len(records),
        "candidate_contract":"DENSE_STRICT_SWING_RUNNING_EXTREME_V1",
        "observation_delays_metric_only":list(OBSERVATION_DELAYS),
        "source":"CryptoHFTData Bybit hourly Parquet/Zstd",
        "downloaded_files":src.downloads,"downloaded_bytes":src.bytes,
        "source_file_counts":dict(src.counts),"account_ratio_rows":len(ratio_rows),
        "missing_files":src.missing,"schemas":schemas,"raw_files_retained":False,
        "compression":"gzip-9 compact outputs",
        "microstructure_quality_contract":base.MICRO_QUALITY_CONTRACT,
        "future_leakage_guard":"strict labels/episode boundaries are offline teacher only; no target/eval point enters features",
    }
    (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n")
    am={}
    for p in args.output.iterdir():
        if p.is_file():am[p.name]={"bytes":p.stat().st_size,"sha256":sha(p)}
    (args.output/"artifact_manifest.json").write_text(json.dumps(am,indent=2)+"\n")
    print("DENSE_FULL_MICRO="+json.dumps({
        "candidates":manifest["candidates"],"true_candidates":manifest["true_candidates"],
        "false_candidates":manifest["false_candidates"],"snapshots":manifest["snapshots"],
        "downloaded_files":manifest["downloaded_files"],"downloaded_bytes":manifest["downloaded_bytes"]
    },separators=(",",":")),flush=True)


if __name__=="__main__":main()
