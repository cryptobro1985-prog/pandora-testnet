#!/usr/bin/env python3
from __future__ import annotations

import argparse, gzip, hashlib, io, json, math, statistics, zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Local:
    period: str
    label_id: int
    side: str
    price: float
    ts_ms: int
    start_ms: int
    end_ms: int


def pctile(xs, q):
    if not xs:
        return None
    a=sorted(xs)
    if len(a)==1:
        return float(a[0])
    pos=(len(a)-1)*q
    lo=int(math.floor(pos)); hi=int(math.ceil(pos))
    if lo==hi:
        return float(a[lo])
    w=pos-lo
    return float(a[lo]*(1-w)+a[hi]*w)


def read_labels_gz_bytes(data: bytes, period: str) -> list[Local]:
    with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as gz:
        doc=json.loads(gz.read().decode("utf-8"))
    out=[]
    for r in doc.get("strict") or []:
        if not bool(r.get("reference_finalized", True)):
            continue
        side=str(r["side"]).upper()
        if side not in ("LOW","HIGH"):
            continue
        out.append(Local(
            period=period,
            label_id=int(r["label_id"]),
            side=side,
            price=float(r["extreme_price"]),
            ts_ms=int(r.get("extreme_ts_ms",r.get("extreme_interval_start_ms"))),
            start_ms=int(r["extreme_interval_start_ms"]),
            end_ms=int(r["extreme_interval_end_ms"]),
        ))
    out.sort(key=lambda x:(x.start_ms,x.ts_ms,x.label_id))
    return out


def nested_labels_from_zip(path: Path) -> list[Local]:
    result=[]
    seen=set()

    def visit_zip_bytes(data: bytes, prefix: str):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                lower=name.lower()
                blob=None
                if lower.endswith("labels.json.gz"):
                    blob=z.read(name)
                    period=Path(name).parent.name or prefix or "root"
                    key=hashlib.sha256(blob).hexdigest()
                    if key not in seen:
                        seen.add(key)
                        result.extend(read_labels_gz_bytes(blob,period))
                elif lower.endswith(".zip"):
                    try:
                        visit_zip_bytes(z.read(name), Path(name).stem)
                    except zipfile.BadZipFile:
                        pass

    if path.is_file() and path.suffix.lower()==".zip":
        visit_zip_bytes(path.read_bytes(),path.stem)
    elif path.is_dir():
        for p in path.rglob("*"):
            if p.is_file() and p.name.lower()=="labels.json.gz":
                period=p.parent.name
                blob=p.read_bytes()
                key=hashlib.sha256(blob).hexdigest()
                if key not in seen:
                    seen.add(key)
                    result.extend(read_labels_gz_bytes(blob,period))
            elif p.is_file() and p.suffix.lower()==".zip":
                try:
                    visit_zip_bytes(p.read_bytes(),p.stem)
                except zipfile.BadZipFile:
                    pass
    return result


def collapse_same_side(labels: list[Local]) -> list[Local]:
    """Defensive collapse at period boundaries; keep the more extreme same-side local."""
    out=[]
    for x in sorted(labels,key=lambda z:(z.ts_ms,z.period,z.label_id)):
        if not out or out[-1].side!=x.side:
            out.append(x)
            continue
        prev=out[-1]
        better=(x.side=="LOW" and x.price<prev.price) or (x.side=="HIGH" and x.price>prev.price)
        if better:
            out[-1]=x
    return out


def leg_record(a: Local, b: Local):
    if a.side==b.side:
        return None
    if a.side=="LOW" and b.side=="HIGH":
        gross=(b.price/a.price-1.0)*100.0
        direction="LONG"
    elif a.side=="HIGH" and b.side=="LOW":
        gross=(a.price-b.price)/a.price*100.0
        direction="SHORT"
    else:
        return None
    return {
        "entry_side":a.side,
        "entry_label_id":a.label_id,
        "entry_period":a.period,
        "entry_ts_ms":a.ts_ms,
        "entry_price":a.price,
        "direction":direction,
        "exit_side":b.side,
        "exit_label_id":b.label_id,
        "exit_period":b.period,
        "exit_ts_ms":b.ts_ms,
        "exit_price":b.price,
        "hold_hours":(b.ts_ms-a.ts_ms)/3_600_000.0,
        "captured_move_pct":gross,
        "captured_move_bps":gross*100.0,
    }


def summarize_legs(legs):
    moves=[x["captured_move_pct"] for x in legs]
    holds=[x["hold_hours"] for x in legs]
    compound=1.0
    for r in moves:
        compound*=1.0+r/100.0
    return {
        "legs":len(legs),
        "total_captured_move_pct_sum":sum(moves),
        "median_move_pct":statistics.median(moves) if moves else None,
        "p25_move_pct":pctile(moves,.25),
        "p75_move_pct":pctile(moves,.75),
        "p90_move_pct":pctile(moves,.90),
        "min_move_pct":min(moves) if moves else None,
        "max_move_pct":max(moves) if moves else None,
        "median_hold_hours":statistics.median(holds) if holds else None,
        "p90_hold_hours":pctile(holds,.90),
        "ideal_full_equity_compound_multiple_no_fees_no_slippage":compound,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--artifact",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()

    labels=nested_labels_from_zip(args.artifact)
    if not labels:
        raise SystemExit("No strict finalized labels found in artifact")

    by_period={}
    for x in labels:
        by_period.setdefault(x.period,[]).append(x)

    # Score within each archival period to avoid fabricating trades across gaps.
    all_legs=[]
    period_reports={}
    all_locals=[]
    for period, rows in sorted(by_period.items()):
        seq=collapse_same_side(rows)
        legs=[]
        for a,b in zip(seq,seq[1:]):
            z=leg_record(a,b)
            if z is not None:
                legs.append(z)
        all_legs.extend(legs)
        all_locals.extend(seq)
        period_reports[period]={
            "finalized_locals":len(seq),
            "LOW":sum(x.side=="LOW" for x in seq),
            "HIGH":sum(x.side=="HIGH" for x in seq),
            "first_ts_ms":min(x.ts_ms for x in seq) if seq else None,
            "last_ts_ms":max(x.ts_ms for x in seq) if seq else None,
            "oracle":summarize_legs(legs),
        }

    low_legs=[x for x in all_legs if x["entry_side"]=="LOW"]
    high_legs=[x for x in all_legs if x["entry_side"]=="HIGH"]
    ranked=sorted(all_legs,key=lambda x:x["captured_move_pct"],reverse=True)

    # Best individual oracle entry locals by subsequent opposite-local move.
    best_low=max(low_legs,key=lambda x:x["captured_move_pct"]) if low_legs else None
    best_high=max(high_legs,key=lambda x:x["captured_move_pct"]) if high_legs else None

    # Practical "worth trading" move floors by empirical quantile.
    move_floor={
        "LOW_to_HIGH":{
            "median_bps":pctile([x["captured_move_bps"] for x in low_legs],.5),
            "p25_bps":pctile([x["captured_move_bps"] for x in low_legs],.25),
            "p10_bps":pctile([x["captured_move_bps"] for x in low_legs],.10),
        },
        "HIGH_to_LOW":{
            "median_bps":pctile([x["captured_move_bps"] for x in high_legs],.5),
            "p25_bps":pctile([x["captured_move_bps"] for x in high_legs],.25),
            "p10_bps":pctile([x["captured_move_bps"] for x in high_legs],.10),
        },
    }

    report={
        "version":"HYPE-STRICT-LOCAL-ORACLE-ALL-DATA-v1",
        "teacher":"STRICT_L6_K2_REFERENCE_FINALIZED_ONLY",
        "scope":"all label archives found in master artifact; no trade bridged across archival gaps",
        "artifact":str(args.artifact),
        "periods":period_reports,
        "totals":{
            "finalized_locals":len(all_locals),
            "LOW":sum(x.side=="LOW" for x in all_locals),
            "HIGH":sum(x.side=="HIGH" for x in all_locals),
            "oracle_all":summarize_legs(all_legs),
            "oracle_long_from_LOW":summarize_legs(low_legs),
            "oracle_short_from_HIGH":summarize_legs(high_legs),
        },
        "best_oracle_LOW_entry":best_low,
        "best_oracle_HIGH_entry":best_high,
        "top_20_oracle_legs":ranked[:20],
        "move_floor_bps":move_floor,
        "interpretation":{
            "ideal_trade_rule":"At each finalized TRUE terminal LOW enter LONG and flip at next TRUE terminal HIGH; at each TRUE terminal HIGH enter SHORT and flip at next TRUE terminal LOW.",
            "research_target":"A live detector should approximate these labels causally. Oracle labels themselves are future-confirmed teacher data and cannot be used as live inputs.",
        },
        "real_orders":False,
    }

    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("ORACLE_SUMMARY="+json.dumps({
        "totals":report["totals"],
        "best_low":best_low,
        "best_high":best_high,
        "move_floor_bps":move_floor
    },separators=(",",":")))


if __name__=="__main__":
    main()
