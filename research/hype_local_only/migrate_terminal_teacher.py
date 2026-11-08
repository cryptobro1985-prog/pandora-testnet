#!/usr/bin/env python3
"""One-time checkpoint sanitation for the terminal-local teacher migration.

Replaces STRICT candidate heads and H1 prior with a clean finalized historical
pretrain.  Preserves the separate INTERNAL tactical learner.  Legacy live
weights cannot be unlearned reliably because their teacher labeled provisional
K2 pivots as positive before terminal finalization.
"""
from __future__ import annotations

import argparse
import json
import pickle
import time
from pathlib import Path

from research.hype_local_only.model import LocalOnlyModel

MIGRATION_ID="TERMINAL_TEACHER_CLEAN_V1"


def sanitize_model(current: LocalOnlyModel, clean: LocalOnlyModel) -> dict:
    current._ensure_internal_scope()
    clean._ensure_internal_scope()

    old={
        "strict_live_labels_discarded":int(getattr(current,"live_labels",0) or 0),
        "strict_labels_before":sum(getattr(current,"labels",{}).values()),
        "strict_positive_before":sum(getattr(current,"positive",{}).values()),
        "h1_labels_before":sum(getattr(current,"h1_labels",{}).values()),
        "h1_positive_before":sum(getattr(current,"h1_positive",{}).values()),
        "old_model_version":getattr(current,"VERSION",None),
    }

    # Clean finalized 30D STRICT/H1 state.
    for attr in (
        "models","labels","positive","thresholds",
        "h1_models","h1_labels","h1_positive","h1_thresholds",
        "h1_last_trained_hour_ms","relationship_memory",
    ):
        setattr(current,attr,getattr(clean,attr))
    current.live_labels=0
    current.h1_shadow={}
    current.last_signal=None

    # INTERNAL_* fields deliberately remain from current checkpoint.
    meta=dict(getattr(clean,"history_meta",{}) or {})
    meta["terminal_teacher_migration"]={
        "id":MIGRATION_ID,
        "generated_ts_ms":int(time.time()*1000),
        "legacy_teacher":"H1_L6_K2_STRICT_PROVISIONAL_PIVOT",
        "new_strict_teacher":"STRICT_L6_K2_TERMINAL_FINALIZED",
        "new_internal_teacher":"INTERNAL_L3_K1_TERMINAL_FINALIZED",
        "legacy_live_weights_discarded":True,
        **old,
    }
    current.history_meta=meta
    return old


def sanitize_runtime(path: Path) -> dict:
    if not path.exists():
        return {"runtime_present":False}
    try:
        with path.open("rb") as f:
            rt=pickle.load(f)
    except Exception as exc:
        return {"runtime_present":True,"runtime_read_error":repr(exc)}
    if not isinstance(rt,dict):
        return {"runtime_present":True,"runtime_type":type(rt).__name__}

    old_expected=rt.get("expected_side")
    old_teacher=rt.get("last_teacher_local")
    rt["expected_side"]=None
    rt["last_teacher_local"]=None
    rt["structure_48h"]={}
    with path.open("wb") as f:
        pickle.dump(rt,f,pickle.HIGHEST_PROTOCOL)
    return {
        "runtime_present":True,
        "old_expected_side":old_expected,
        "old_last_teacher_local":old_teacher,
        "structural_anchor_cleared":True,
        "candidates_preserved":bool(rt.get("candidates")),
        "pending_preserved":len(rt.get("pending") or []),
    }


def already_migrated(model: LocalOnlyModel) -> bool:
    m=(getattr(model,"history_meta",{}) or {}).get("terminal_teacher_migration") or {}
    return m.get("id")==MIGRATION_ID


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--current-model",type=Path,required=True)
    ap.add_argument("--clean-model",type=Path,required=True)
    ap.add_argument("--runtime",type=Path)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args()

    current=LocalOnlyModel.load(args.current_model)
    current._ensure_internal_scope()
    if already_migrated(current):
        report={"status":"ALREADY_MIGRATED","migration_id":MIGRATION_ID}
    else:
        clean=LocalOnlyModel.load(args.clean_model)
        old=sanitize_model(current,clean)
        current.save(args.current_model)
        runtime=sanitize_runtime(args.runtime) if args.runtime else {}
        report={
            "status":"MIGRATED",
            "migration_id":MIGRATION_ID,
            "research_only":True,
            "real_orders":False,
            "discarded":old,
            "runtime":runtime,
            "strict_labels_after":sum(current.labels.values()),
            "strict_positive_after":sum(current.positive.values()),
            "h1_labels_after":sum(current.h1_labels.values()),
            "h1_positive_after":sum(current.h1_positive.values()),
            "internal_labels_preserved":sum(current.internal_labels.values()),
            "internal_positive_preserved":sum(current.internal_positive.values()),
            "h1_online_training_enabled":False,
        }
    args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("TERMINAL_MIGRATION="+json.dumps(report,separators=(",",":"),ensure_ascii=False))


if __name__=="__main__":
    main()
