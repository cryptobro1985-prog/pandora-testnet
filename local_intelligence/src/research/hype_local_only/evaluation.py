"""Temporal evaluation primitives. Labels and feature availability are separate."""
from __future__ import annotations

import math
import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss

HOUR = 3_600_000
DAY = 24 * HOUR


def purged_partition(rows, train_end, calibration_end, eval_start, eval_end, embargo_ms=6*HOUR):
    """An example may train/calibrate only after its delayed label is available.

    Six-hour embargo also separates the longest local context. Candidate groups
    cannot cross partitions. Boundaries always use prediction and label times.
    """
    train = [r for r in rows if r["snapshot_ts_ms"] < train_end - embargo_ms
             and r["label_mature_ms"] <= train_end - embargo_ms]
    calibration = [r for r in rows if train_end <= r["snapshot_ts_ms"] < calibration_end - embargo_ms
                   and r["label_mature_ms"] <= calibration_end - embargo_ms]
    evaluation = [r for r in rows if eval_start <= r.get("candidate_ts_ms",r["snapshot_ts_ms"]) < eval_end
                  and r["snapshot_ts_ms"] < eval_end
                  and r["label_mature_ms"] <= eval_end - embargo_ms]
    groups = [{r["candidate_id"] for r in part} for part in (train, calibration, evaluation)]
    if any(groups[a] & groups[b] for a,b in ((0,1),(0,2),(1,2))):
        raise ValueError("candidate crossed a chronological boundary")
    return train, calibration, evaluation


def wilson(successes, total):
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    d = 1 + z*z/total
    center = (p+z*z/(2*total))/d
    half = z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/d
    return [max(0.0,center-half),min(1.0,center+half)]


def binary_metrics(rows, probabilities, threshold):
    labels = np.asarray([bool(r["strict_true"]) for r in rows], dtype=int)
    probs = np.clip(np.asarray(probabilities, dtype=float), 1e-8, 1-1e-8)
    predicted = probs >= threshold
    tp = int(np.sum(predicted & (labels == 1)))
    fp = int(np.sum(predicted & (labels == 0)))
    fn = int(np.sum(~predicted & (labels == 1)))
    tn = int(np.sum(~predicted & (labels == 0)))
    precision = tp / (tp+fp) if tp+fp else None
    recall = tp / (tp+fn) if tp+fn else None
    result = {"n":len(rows),"tp":tp,"fp":fp,"fn":fn,"tn":tn,
              "precision":precision,"recall":recall,
              "f1":2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0,
              "precision_ci95":wilson(tp,tp+fp),"recall_ci95":wilson(tp,tp+fn),
              "accuracy":(tp+tn)/len(rows) if rows else None,
              "brier":float(brier_score_loss(labels,probs)) if rows else None,
              "log_loss":float(log_loss(labels,probs,labels=[0,1])) if rows else None,
              "pr_auc":float(average_precision_score(labels,probs)) if labels.sum() else None}
    bins=[]
    for low in np.arange(0,1,.1):
        mask=(probs>=low)&(probs<low+.1)
        if mask.any():
            bins.append({"low":float(low),"n":int(mask.sum()),"mean_probability":float(probs[mask].mean()),
                         "observed_rate":float(labels[mask].mean())})
    result["calibration_bins"]=bins
    result["ece"] = sum(b["n"]*abs(b["mean_probability"]-b["observed_rate"]) for b in bins)/max(1,len(rows))
    return result


def event_metrics(rows, probabilities, threshold, teachers, start, end, side=None):
    """First accepted event per side/hour; a teacher is counted at most once.

    All finalized teachers in the interval form recall's denominator, including
    any with no surviving proposal. Delay uses recorded trade-extreme timestamps;
    the retained minute teacher also supplies interval uncertainty bounds.
    """
    eligible=[t for t in teachers if t.get("reference_finalized") and start<=t["extreme_interval_start_ms"]<end
              and (side is None or t["side"]==side)]
    truth={int(t["label_id"]) for t in eligible}
    teacher_map={int(t["label_id"]):t for t in eligible}
    accepted=[];seen=set();matched=set();delays=[];delay_bounds=[]
    for row,p in sorted(zip(rows,probabilities),key=lambda z:z[0]["snapshot_ts_ms"]):
        if side is not None and row["side"]!=side:
            continue
        key=row["event_key"]
        if p<threshold or key in seen:
            continue
        seen.add(key);accepted.append(row)
        label=row.get("strict_label_id")
        if row["strict_true"] and label in truth and label not in matched:
            matched.add(label);delays.append((row["snapshot_ts_ms"]-row["candidate_ts_ms"])/1000)
            teacher=teacher_map[label]
            delay_bounds.append([max(0.,(row["snapshot_ts_ms"]-teacher["extreme_interval_end_ms"])/1000),
                                 (row["snapshot_ts_ms"]-teacher["extreme_interval_start_ms"])/1000])
    tp=len(matched);fp=len(accepted)-tp;fn=len(truth)-tp
    return {"accepted":len(accepted),"true_events":tp,"false_events":fp,
            "teacher_events":len(truth),"missed_events":fn,
            "precision":tp/len(accepted) if accepted else None,
            "recall":tp/len(truth) if truth else None,
            "f1":2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0,
            "precision_ci95":wilson(tp,len(accepted)),"recall_ci95":wilson(tp,len(truth)),
            "missed_local_rate":fn/len(truth) if truth else None,
            "false_signals_per_hour":fp/max(1e-9,(end-start)/HOUR),
            "detection_delay_s":{"p50":float(np.median(delays)) if delays else None,
                                 "p95":float(np.quantile(delays,.95)) if delays else None,
                                 "timestamp_provenance":"recorded individual-trade extreme timestamp; raw trades not retained",
                                 "teacher_interval_p50_lower":float(np.median([d[0] for d in delay_bounds])) if delay_bounds else None,
                                 "teacher_interval_p50_upper":float(np.median([d[1] for d in delay_bounds])) if delay_bounds else None},
            "deduplication":"first accepted side:hour; all stages share one event"}


def choose_event_threshold(rows, probabilities, teachers, start, end):
    if not rows:
        return 1.0
    values=np.asarray(probabilities)
    choices=np.unique(np.r_[0.01,np.quantile(values,np.linspace(0,1,71)),1.0])
    ranked=[]
    for threshold in choices:
        m=event_metrics(rows,probabilities,float(threshold),teachers,start,end)
        # F1 balances misses/false signals. No precision-only rare-signal objective.
        ranked.append(((m["f1"],m["recall"] or 0,-m["false_events"],float(threshold)),float(threshold)))
    return max(ranked)[1]


def paired_day_bootstrap(rows, first, second, iterations=1000, seed=20261107):
    """Cluster by UTC day so correlated stages are never treated independent."""
    groups={}
    for i,r in enumerate(rows):
        groups.setdefault(r["candidate_ts_ms"]//DAY,[]).append(i)
    days=list(groups)
    if len(days)<2:
        return {"delta_brier_ci95":None,"independent_day_blocks":len(days)}
    y=np.asarray([r["strict_true"] for r in rows],dtype=float)
    delta=(np.asarray(second)-y)**2-(np.asarray(first)-y)**2
    rng=np.random.default_rng(seed);samples=[]
    for _ in range(iterations):
        idx=np.concatenate([groups[days[int(j)]] for j in rng.integers(0,len(days),len(days))])
        samples.append(float(delta[idx].mean()))
    return {"delta_brier_second_minus_first":float(delta.mean()),
            "delta_brier_ci95":[float(v) for v in np.quantile(samples,[.025,.975])],
            "independent_day_blocks":len(days),"iterations":iterations,
            "interpretation":"negative favors second; selection uncertainty is not included"}
