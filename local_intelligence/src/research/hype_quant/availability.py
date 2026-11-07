"""Reproducible, read-only audit of the supplied compact historical artifacts."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path

from .feature_bus import is_predictive_name
from .feature_contract import INPUT_IDS, TARGET_IDS, METADATA_IDS


def json_lines(path):
    with gzip.open(path,"rt",encoding="utf-8") as stream:
        for line in stream:
            if line.strip():yield json.loads(line)


def audit_history(artifacts: Path) -> dict:
    history=artifacts/"history_30d_local116"
    snapshots=list(json_lines(history/"candidate_snapshots.jsonl.gz"))
    minutes=list(json_lines(history/"compact_1m.jsonl.gz"))
    with gzip.open(history/"labels.json.gz","rt") as stream:labels=json.load(stream)
    keys=Counter((r["candidate_id"],r.get("delay_s")) for r in snapshots)
    features=Counter(k for r in snapshots for k in r.get("features",{}))
    starts=sorted(int(r["start_ms"]) for r in minutes)
    gaps=[{"after_start_ms":a,"before_start_ms":b,"missing_minutes":(b-a)//60_000-1}
          for a,b in zip(starts,starts[1:]) if b-a>60_000]
    nonfinite=sum(not isinstance(v,(int,float)) or not math.isfinite(v)
                  for r in snapshots for v in r.get("features",{}).values())
    forbidden=sorted(k for k in features if not is_predictive_name(k))
    out={"version":"PANDORA-FEATURE-AUDIT-v1",
         "contract":{"total":116,"input":len(INPUT_IDS),"target_eval":len(TARGET_IDS),"metadata":len(METADATA_IDS)},
         "snapshots":{"rows":len(snapshots),"candidates":len({r["candidate_id"] for r in snapshots}),
                      "duplicate_candidate_stage_rows":sum(n-1 for n in keys.values() if n>1),
                      "nonfinite_feature_values":nonfinite,"forbidden_feature_names":forbidden,
                      "feature_name_observation_counts":dict(sorted(features.items()))},
         "minute_bars":{"rows":len(minutes),"duplicate_starts":len(starts)-len(set(starts)),
                        "missing_intervals":gaps,"first_start_ms":min(starts),"last_start_ms":max(starts)},
         "labels":{k:len(v) for k,v in labels.items() if isinstance(v,list)},
         "historical_receive_timestamps":"unavailable; exchange timestamps are not receive timestamps",
         "legacy_snapshot_causality":"failed: 5s bars selected by start<t and full final close/flow; minute bars selected by start<=t and full OHLC",
         "usable_reconstruction":"completed compact 1m OHLC through bar_end<=prediction; gap windows unavailable",
         "unavailable_historical_families":{
             "44-57":"L50 primary replay absent",
             "65-76":"liquidation primary websocket events absent",
             "77-78":"raw receipt/latency and live micro snapshot provenance absent",
             "111":"runner clock offset absent",
             "112-113":"contemporaneous instrument and account ratio history absent",
             "116":"historical websocket continuity cannot be reconstructed"}}
    auxiliary=artifacts/"historical_gaps"
    if auxiliary.exists():
        manifest=json.loads((auxiliary/"manifest.json").read_text())
        verified={}
        for name,meta in manifest.get("files",{}).items():
            path=auxiliary/name
            verified[name]={"sha256_matches":hashlib.sha256(path.read_bytes()).hexdigest()==meta["sha256"],
                            "bytes_match":path.stat().st_size==meta["bytes"]}
        enriched=list(json_lines(auxiliary/"candidate_snapshots_enriched.jsonl.gz"))
        violations=[]
        for row in enriched:
            ts=int(row["snapshot_ts_ms"])
            for key,value in row.get("historical_gap_sources",{}).items():
                if not key.endswith("_ts_ms") or value is None:continue
                available=int(value)+(60_000 if key in {"mark_ts_ms","index_ts_ms"} else 0)
                if available>ts:violations.append({"candidate_id":row["candidate_id"],"source":key,"available_ms":available,"snapshot_ms":ts})
        out["auxiliary"]={"source_counts":{name:sum(1 for _ in json_lines(auxiliary/name))
                                             for name in ("mark_1m.jsonl.gz","index_1m.jsonl.gz","open_interest_5m.jsonl.gz","funding.jsonl.gz")},
                          "manifest_integrity":verified,"enriched_rows":len(enriched),
                          "source_availability_violations":violations,
                          "safe_source_time_features":["completed mark/index basis","OI log and timestamped deltas","funding"],
                          "unsafe_until_rebuilt":["mark/index divided by legacy 5s final price","OI notional using legacy price"],
                          "receive_provenance":"unknown; source_time_only"}
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts",type=Path,default=Path("artifacts"))
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    result=audit_history(args.artifacts)
    encoded=json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(encoded)
    else:print(encoded,end="")


if __name__=="__main__":main()
