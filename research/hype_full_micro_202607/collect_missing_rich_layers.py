from __future__ import annotations
import argparse, gzip, hashlib, json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.hype_full_micro_202607 import build_full_micro as base

UTC=timezone.utc
KINDS=("orderbook","liquidations","open_interest","mark_price","ticker")
WINDOWS=(5,15,60,180,300)

def minute_targets(start,end):
    t=int(start.timestamp()*1000)
    e=int(end.timestamp()*1000)
    # minute-end samples, causal and easy to join to existing compact M1 history
    first=((t+59_999)//60_000)*60_000
    return list(range(first,e,60_000))

def write_jsonl_gz(path,rows):
    with gzip.open(path,"wt",encoding="utf-8",compresslevel=9) as f:
        for r in rows:
            f.write(json.dumps(r,separators=(",",":"),allow_nan=False)+"\n")

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--cache",type=Path,required=True)
    args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)

    start=base.START
    end=base.END
    src=base.Source(args.cache,os.getenv("CRYPTOHFTDATA_API_KEY"))
    targets=minute_targets(start,end)
    byhour={}
    for t in targets:
        h=datetime.fromtimestamp(t/1000,tz=UTC).replace(minute=0,second=0,microsecond=0)
        byhour.setdefault(h,[]).append(t)

    # Only the missing rich streams. No trades, no labels, no candidate rebuild.
    base.prefetch_hours(src,start-timedelta(hours=1),end,KINDS)

    rows=[]
    schemas={}
    book_state=None
    scalar_state={k:{} for k in ("open_interest","mark_price","ticker")}
    liq_recent=[]
    liq_available_hours=set()

    dt=start.replace(minute=0,second=0,microsecond=0)-timedelta(hours=1)
    stop=end.replace(minute=0,second=0,microsecond=0)+timedelta(hours=1)
    while dt<stop:
        hour_targets=sorted(byhour.get(dt,[]))

        bp=src.get(dt,"orderbook")
        if bp:
            bsn,book_state,cs=base.book_replay(bp,hour_targets,book_state)
            if cs: schemas.setdefault("orderbook",cs)
            bp.unlink(missing_ok=True)
        else:
            if book_state is None:
                book_state={"bids":{},"asks":{},"last_u":None,"valid":False,"gap_count":0,"events":[]}
            base.invalidate_book(book_state)
            bsn={t:base.book_features(book_state,t) for t in hour_targets}

        lp=src.get(dt,"liquidations")
        if lp:
            df=base.read_parquet(lp)
            ev,cs=base.liquidation_events(df)
            if cs:
                schemas.setdefault("liquidations",cs)
                liq_recent.extend(ev)
                liq_available_hours.add(base.ms(dt))
            lp.unlink(missing_ok=True)

        scalar_snaps={}
        for kind in ("open_interest","mark_price","ticker"):
            p=src.get(dt,kind)
            df=base.read_parquet(p) if p else None
            snaps,scalar_state[kind],cs=base.scalar_snapshots(df,hour_targets,scalar_state[kind])
            scalar_snaps[kind]=snaps
            if cs: schemas.setdefault(kind,cs)
            if p: p.unlink(missing_ok=True)

        floor=base.ms(dt)-300_000
        liq_recent=[x for x in liq_recent if x[0]>=floor]

        for t in hour_targets:
            feat={}
            feat.update(bsn.get(t,base.book_features(book_state,t)))
            feat.update(base.liq_features(liq_recent,t,liq_available_hours))
            for kind in ("open_interest","mark_price","ticker"):
                z=scalar_snaps.get(kind,{}).get(t,{})
                stamp=z.get("_ts_ms")
                if stamp is not None:
                    feat[f"fullmicro_{kind}_age_ms"]=float(max(0,t-stamp))
                for k,v in z.items():
                    if k!="_ts_ms" and base.finite(v):
                        feat[f"fullmicro_{kind}_{k}"]=float(v)
            rows.append({"ts_ms":t,"features":feat})

        dt+=timedelta(hours=1)

    ratio_rows=base.fetch_account_ratio()
    if ratio_rows:
        ts=[int(x["ts_ms"]) for x in ratio_rows]
        import bisect
        for r in rows:
            t=int(r["ts_ms"])
            j=bisect.bisect_right(ts,t)-1
            if j<0: continue
            z=ratio_rows[j]
            age=t-int(z["ts_ms"])
            if age>30*60*1000: continue
            f=r["features"]
            f["fullmicro_account_buy_ratio"]=float(z["buy_ratio"])
            f["fullmicro_account_sell_ratio"]=float(z["sell_ratio"])
            if base.finite(z.get("long_short_ratio")):
                f["fullmicro_account_long_short_ratio"]=float(z["long_short_ratio"])
            f["fullmicro_account_ratio_age_ms"]=float(max(0,age))

    out=args.output/"missing_rich_layers_1m.jsonl.gz"
    write_jsonl_gz(out,rows)

    manifest={
        "symbol":base.SYMBOL,
        "period":[start.isoformat(),end.isoformat()],
        "purpose":"MISSING_RICH_LAYERS_ONLY",
        "join_key":"ts_ms",
        "rows_1m":len(rows),
        "downloaded_kinds":list(KINDS),
        "explicitly_not_downloaded":["trades"],
        "reuses_existing_history":True,
        "source_file_counts":dict(src.counts),
        "downloaded_files":src.downloads,
        "downloaded_bytes_ephemeral":src.bytes,
        "missing_files":src.missing,
        "raw_files_retained":False,
        "compression":"gzip-9",
        "schemas":schemas,
        "account_ratio_rows":len(ratio_rows),
        "quality_contract":base.MICRO_QUALITY_CONTRACT,
    }
    (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n")
    audit={
        "rows_1m":len(rows),
        "missing_file_count":len(src.missing),
        "missing_files":src.missing,
        "source_file_counts":dict(src.counts),
        "raw_download_mb_ephemeral":round(src.bytes/1024/1024,2),
        "compact_output_bytes":out.stat().st_size,
        "compact_output_mb":round(out.stat().st_size/1024/1024,2),
        "raw_cache_retained":False,
    }
    if out.stat().st_size:
        audit["compression_ratio_raw_to_compact"]=round(src.bytes/out.stat().st_size,2)
    (args.output/"COLLECTION_AUDIT.json").write_text(json.dumps(audit,indent=2,ensure_ascii=False)+"\n")
    (args.output/"artifact_manifest.json").write_text(json.dumps({
        out.name:{"bytes":out.stat().st_size,"sha256":sha256(out)}
    },indent=2)+"\n")
    print("MISSING_RICH_LAYERS="+json.dumps(audit,separators=(",",":")))

if __name__=="__main__":
    main()
