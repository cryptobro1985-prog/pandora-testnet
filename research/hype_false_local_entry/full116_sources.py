"""Verify HYPE source identity and account for every canonical point."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import PurePosixPath
from zipfile import ZipFile

from research.hype_false_local_entry import full116_candidate_features as features
from research.hype_false_local_entry import replay_early_trajectory as prior
from research.hype_quant.feature_contract import INPUT_IDS, METADATA_IDS, POINTS, TARGET_IDS

MASTER_ID = 13650399622
CONTROL_CAPTURE_ID = 13677742339
CONTROL_CAPTURE_SHA = "41b2f69b7e4669c15628d380ecee216d693d629aae9b5b34826c8c84ce51a525"
CLEAN_PENDING_RUN = 42619539996
HISTORICAL_FAMILIES = {
    "book": set(range(44, 58)), "liquidations": set(range(65, 77)),
    "oi": {58, 59, 60, 61, 115}, "scalars": {2, 3, 62, 113, 114},
}


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def checked_member(archive, name, index):
    payload = archive.read(name)
    descriptor = index[name]
    if len(payload) != descriptor["bytes"] or sha_bytes(payload) != descriptor["sha256"]:
        raise ValueError(f"artifact member checksum mismatch: {name}")
    return payload


def read_master(path):
    if prior.file_sha(path) != prior.MASTER_SHA256:
        raise ValueError("unexpected historical master SHA-256")
    with ZipFile(path) as z:
        document = json.loads(z.read("MASTER_INDEX.json"))
        index = {member["path"]: member for member in document["files"]}
        for period in document["periods"]:
            folder = period["folder"]
            tape = checked_member(z, f"{folder}/compact_1m.jsonl.gz", index)
            labels = checked_member(z, f"{folder}/labels.json.gz", index)
            bars = [json.loads(line) for line in gzip.decompress(tape).splitlines()]
            yield period, bars, json.loads(gzip.decompress(labels))["strict"]


def read_live_coverage(path):
    if path is None:
        return {}
    if prior.file_sha(path) != CONTROL_CAPTURE_SHA:
        raise ValueError("unexpected live checkpoint SHA-256")
    with ZipFile(path) as z:
        status = json.loads(z.read("LOCAL_ONLY_STATUS.json"))
    report = status["feature_contract"]
    seen = set(report["seen_input_ids"])
    if seen - INPUT_IDS:
        raise ValueError("live input report includes a forbidden point ID")
    return {"artifact": CONTROL_CAPTURE_ID, "updated_ts_ms": status["updated_ts_ms"],
            "seen_input_ids": sorted(seen), "point_age_seconds": report["point_age_seconds"]}


def nonnegative(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def validate_snapshot(row):
    f = row["features"]
    book = f.get("fullmicro_book_valid")
    spread = f.get("fullmicro_spread_bps")
    if book not in (0, 1) or (book == 1 and (
        not nonnegative(spread) or spread == 0 or f.get("fullmicro_book_crossed") != 0
    )) or (book == 0 and spread is not None):
        raise ValueError("invalid point book or spread")
    for sec in features.WINDOWS:
        valid = f.get(f"fullmicro_book_window_valid_{sec}s")
        rolling_value = f.get(f"fullmicro_book_churn_notional_{sec}s")
        if valid not in (0, 1) or (valid == 1 and (book != 1 or not nonnegative(rolling_value))):
            raise ValueError("missing or invalid continuous book window mask")
        if valid == 0 and rolling_value is not None:
            raise ValueError("book data emitted across invalid window")
    for sec in features.LIQ_WINDOWS:
        valid = f.get(f"fullmicro_liq_stream_valid_{sec}s")
        keys = [f"fullmicro_{key}_{sec}s" for key in
                ("liq_count", "long_liq_notional", "short_liq_notional", "liq_imbalance")]
        if valid not in (0, 1) or (valid == 1 and any(not nonnegative(f.get(key)) for key in keys[:3])):
            raise ValueError("missing or invalid liquidation window mask")
        if valid == 0 and any(key in f for key in keys):
            raise ValueError("unobserved liquidation window encoded as an observation")
    for kind in ("open_interest", "mark_price", "ticker", "account_ratio"):
        age_key = f"fullmicro_{kind}_age_ms"
        age = f.get(age_key)
        if age is not None and (not nonnegative(age) or age > row["snapshot_ts_ms"]):
            raise ValueError("scalar receipt age cannot be negative or after the decision")
    if any(k.startswith("fullmicro_open_interest_sum_open_interest") for k in f):
        if not nonnegative(f.get("fullmicro_open_interest_age_ms")):
            raise ValueError("OI value lacks a measured receipt age")


def read_clean_cache(path, expected_sha256):
    """Require the upgraded producer and measured stream integrity, not a filename."""
    if prior.file_sha(path) != expected_sha256:
        raise ValueError("unexpected clean-cache SHA-256")
    with ZipFile(path) as z:
        names = {}
        for path_name in z.namelist():
            basename = PurePosixPath(path_name).name
            if basename in names:
                raise ValueError(f"ambiguous clean-cache member: {basename}")
            names[basename] = path_name
        manifest = json.loads(z.read(names["manifest.json"]))
        if manifest.get("microstructure_quality_contract") != features.MICRO_CONTRACT:
            raise ValueError("cache predates the required receipt and window validity contract")
        audit = json.loads(z.read(names["CLEAN_MICRO_AUDIT.json"]))
        member = "candidate_snapshots_full_micro.jsonl.gz"
        checks = json.loads(z.read(names["artifact_manifest.json"]))
        payload = checked_member(z, names[member], {names[member]: checks[member]})
    rows = [json.loads(line) for line in gzip.decompress(payload).splitlines()]
    valid = 0
    liq = Counter()
    for row in rows:
        validate_snapshot(row)
        f = row["features"]
        valid += f["fullmicro_book_valid"] == 1
        liq.update(sec for sec in features.LIQ_WINDOWS if f[f"fullmicro_liq_stream_valid_{sec}s"] == 1)
    if (len(rows) != audit["rows"] or valid != audit["book_valid_rows"] or not valid
            or any(liq[sec] != audit["liq_valid_rows"][str(sec)] for sec in features.LIQ_WINDOWS)):
        raise ValueError("clean audit totals do not match decoded snapshot availability")
    return features.snapshot_index(rows)


def coverage(periods, live, clean, predictor_ids=()):
    """Produce a decision-row coverage matrix distinct from source inventory."""
    rows = []
    predictors = set(predictor_ids)
    if predictors - INPUT_IDS:
        raise ValueError("coverage reports a forbidden predictor ID")
    for point in POINTS:
        i = point["id"]
        hist = {}
        for name, p in periods.items():
            available = p["counts"][i]
            total = p["decision_rows"]
            role = point["role"]
            if role == "METADATA_ONLY":
                status, reason = ("verified_manifest", "Verified artifact/member provenance") if i == 81 else (
                    "compact_only", "Replayable compact M1, no retained individual raw frames")
                pct = None
            elif i in TARGET_IDS:
                if i in {107, 108}:
                    status = "strict_teacher" if i == 107 else "offline_internal_scope"
                    reason = "Strict archived L6/K2 used in evaluation" if i == 107 else "Internal scope excluded from terminal scoring"
                else:
                    status, reason = "reserved_evaluation", "Derived only where available for evaluation"
                pct = None
            else:
                pct = 100*available/total if total else None
                if available:
                    status = ("candidate_lineage_proxy" if i in features.PROXY_POINTS else
                              "aggregate_or_derived" if i in features.AGGREGATED_POINTS else "verified_causal")
                    reason = None
                elif i in features.HISTORICAL_POINTS:
                    status, reason = "unavailable", "No valid state for this point at the tested decision clocks"
                elif name.startswith("01_") and any(i in group for group in HISTORICAL_FAMILIES.values()):
                    status, reason = "uncertified", "Legacy source requires certification before causal modeling"
                else:
                    status, reason = "unavailable", "Source absent at this decision resolution"
            rich_count = p.get("clean_counts", {}).get(i, 0)
            rich_total = p.get("clean_matches", 0)
            hist[name] = {"status": status, "decision_rows": total, "observed_rows": available,
                          "coverage_pct": pct, "reason": reason,
                          "source": p["source"], "period_utc": p["period_utc"],
                          "freshness": "completed-bar close" if available else None,
                          "certified_snapshot_rows": rich_count,
                          "certified_snapshot_coverage_pct": 100*rich_count/rich_total if rich_total and i in INPUT_IDS else None}
        seen = i in live.get("seen_input_ids", ())
        live_status = "seen_since_boot" if seen else "not_measured"
        if live and i in METADATA_IDS:
            live_status = "checkpoint_provenance" if i == 81 else "raw_capture_inventory"
        rows.append(dict(point, allowed_as_predictor=i in INPUT_IDS,
                         used_as_predictor=i in predictors, historical=hist,
                         live={"available_since_boot": seen if i in INPUT_IDS and live else None,
                               "status": live_status, "coverage_pct": None,
                               "age_seconds": live.get("point_age_seconds", {}).get(str(i)),
                               "source": live.get("artifact")}))
    return {"contract": "HYPE-QUANT-116-v1", "master_artifact": MASTER_ID,
            "master_sha256": prior.MASTER_SHA256, "periods": {
                key: {k: v for k, v in value.items() if k not in ("counts", "clean_counts")}
                for key, value in periods.items()
            },
            "clean_cache": clean, "live": live,
            "live_caveat": "Checkpoint seen-since-boot is not per-decision coverage or a valid model input.",
            "sealed": "Unopened before a transferable model is frozen.",
            "forward": "No forward observations used for fitting, calibration or historical precision.",
            "points": rows, "real_orders": False}


def coverage_markdown(doc):
    periods = list(doc["periods"])
    lines = [
        "# HYPE · покрытие 116-point contract",
        "",
        "Процент показывает долю ранних решений с хотя бы одним допустимым значением по ID. "
        "Источник исторических минуток указан для каждого блока. Live отражает наличие с момента "
        "старта checkpoint и возраст последнего наблюдения. Доля валидных live-решений не измерена.",
        "В master также есть снимки Jul–Aug и Oct–Nov с секундными агрегатами сделок. "
        "Матрица показывает общую M1-плоскость. Архивные L50 и ликвидации Jul–Aug ожидают проверки "
        "непрерывности, времени получения и масок по каждому окну.",
        "",
    ]
    for i, name in enumerate(periods, 1):
        p = doc["periods"][name]
        lines.append(f"- H{i} · {name} · {p['tape_rows']} M1 · {p['decision_rows']} решений · {p['source']}")
    lines.extend(["", "| ID | Поле | Роль | Допуск / X | "
                  + " | ".join(f"H{i}" for i in range(1, len(periods)+1)) + " | Live |",
                  "|---:|---|---|---|" + "---|"*(len(periods)+1)])
    for row in doc["points"]:
        availability = []
        for name in periods:
            value = row["historical"][name]
            percent = value["coverage_pct"]
            availability.append(value["status"] if percent is None else f"{percent:.1f}% {value['status']}")
        age = row["live"]["age_seconds"]
        live = row["live"]["status"] if age is None else f"seen · {age:.1f} s"
        allowed = "да" if row["allowed_as_predictor"] else "нет"
        used = "да" if row["used_as_predictor"] else "нет"
        lines.append(f"| {row['id']} | {row['title']} | {row['role']} | {allowed} / {used} | "
                     + " | ".join([*availability, live]) + " |")
    return "\n".join(lines) + "\n"
