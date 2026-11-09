"""Postfactum audit of sequential flips against complete alternating local intervals.

The caller MUST generate signals causally before passing finalized teacher labels.
No future labels enter signal generation. No order execution.
"""
from bisect import bisect_right
from statistics import median


def _time(label):
    return int(label["extreme_interval_start_ms"])


def _price(label):
    return float(label["extreme_price"])


def score_first_flips(bars, labels, flips, max_lag_ms=3600000):
    """One-to-one chronological matching; all flips counted, including false-first.

    A signal belongs to a teacher interval only when it is the FIRST flip
    following that local, has the same side, and occurs before the next local.
    Later flips within the same interval are counted as duplicates/false.
    This is a retrospective attribution contract, not causal ground truth.
    """
    labels = sorted(labels, key=_time)
    bars = sorted(bars, key=lambda b: int(b.get("bar_end_ms") or int(b["ts_ms"])+60000))
    flips = sorted(flips, key=lambda s: s.ts_ms)
    used = set()
    results = []
    for i, local in enumerate(labels):
        start = _time(local)
        next_local = labels[i+1] if i+1 < len(labels) else None
        stop = _time(next_local) if next_local else start + max_lag_ms
        candidates = [(j,s) for j,s in enumerate(flips)
                      if j not in used and start <= s.ts_ms < min(stop,start+max_lag_ms)]
        first = candidates[0] if candidates else None
        matched = first is not None and first[1].side == local["side"]
        row = {"label_id":local.get("label_id"),"side":local["side"],
               "detected":matched,"first_signal_present":first is not None,
               "first_signal_wrong_side":first is not None and not matched}
        if first:
            j,s=first
            used.add(j)
            row.update(signal_ts_ms=s.ts_ms,signal_side=s.side,lag_ms=s.ts_ms-start,
                       entry_price=s.close,stage=s.stage)
            if matched:
                sign=1 if local["side"]=="LOW" else -1
                extreme=_price(local)
                row["entry_distance_bps"]=sign*(s.close/extreme-1)*10000
                if next_local:
                    target=_price(next_local)
                    full=sign*(target-extreme)
                    remaining=sign*(target-s.close)
                    row["remaining_swing_fraction"]=remaining/full if full>0 else None
                    # Entry occurs at the CLOSE of the signal minute.
                    # Its high/low preceded execution; exclude that candle
                    # from post-entry adverse excursion.
                    path=[b for b in bars if s.ts_ms < int(b.get("bar_end_ms") or int(b["ts_ms"])+60000) <= stop]
                    if path:
                        worst=min(float(b["low"]) for b in path) if sign==1 else max(float(b["high"]) for b in path)
                        row["adverse_extension_bps"]=max(0.,-sign*(worst/s.close-1)*10000)
                    else:
                        row["adverse_extension_bps"]=None
        results.append(row)
    false=[{"ts_ms":s.ts_ms,"side":s.side,"stage":s.stage,"price":s.close}
           for j,s in enumerate(flips) if j not in used]
    # Wrong-side first signals are also false, even though they were assigned
    # to a local interval. Avoid silently inflating precision.
    wrong=[r for r in results if r["first_signal_wrong_side"]]
    hits=[r for r in results if r["detected"]]
    total=len(flips)
    # The terminal finalized local has no completed opposite swing.
    # Preserve local-level diagnostics, but expose the exact 121/75
    # completed-swing denominators separately. Never silently count the
    # terminal local as a completed swing.
    completed_rows = results[:-1]
    completed_hits = sum(bool(r["detected"]) for r in completed_rows)
    completed_swings = len(completed_rows)
    completed_wrong_first = sum(bool(r["first_signal_wrong_side"]) for r in completed_rows)
    completed_missed = completed_swings - completed_hits
    # Completed-swing precision excludes the terminal, unfinished interval.
    # Still charge all unassigned/duplicate core flips as false predictions.
    terminal_hit = bool(results[-1]["detected"]) if results else False
    completed_true_first = completed_hits
    completed_false_predictions = total - completed_true_first
    completed_precision = completed_true_first / total if total else None
    def med(key, rows):
        vals=[r[key] for r in rows if r.get("detected") and r.get(key) is not None]
        return median(vals) if vals else None
    return {
        "finalized_locals":len(labels),"complete_swings":max(0,len(labels)-1),
        "detected_locals":len(hits),"missed_locals":len(labels)-len(hits),
        "completed_swing_true_first":completed_hits,
        "completed_swing_missed":completed_missed,
        "completed_swing_missed_rate":completed_missed/completed_swings if completed_swings else None,
        "completed_swing_recall":completed_hits/completed_swings if completed_swings else None,
        "completed_swing_wrong_first":completed_wrong_first,
        "completed_swing_first_signal_precision":completed_precision,
        "completed_swing_false_first":completed_false_predictions,
        "terminal_local_hit_excluded_from_completed_swing_precision":terminal_hit,
        "missed_local_rate":(len(labels)-len(hits))/len(labels) if labels else None,
        "total_core_flips":total,"false_first":len(false)+len(wrong),
        "first_signal_precision":len(hits)/total if total else None,
        "median_lag_ms":med("lag_ms", results),
        "median_entry_distance_bps":med("entry_distance_bps", results),
        "median_adverse_extension_bps":med("adverse_extension_bps", results),
        "median_remaining_swing_fraction":med("remaining_swing_fraction", results),
        "completed_swing_median_lag_ms":med("lag_ms", completed_rows),
        "completed_swing_median_entry_distance_bps":med("entry_distance_bps", completed_rows),
        "completed_swing_median_adverse_extension_bps":med("adverse_extension_bps", completed_rows),
        "completed_swing_median_remaining_swing_fraction":med("remaining_swing_fraction", completed_rows),
        "matched":results,"unassigned_false_flips":false,
        "caveats":["Teacher intervals are used only after causal signal generation.",
                   "Last local has no known opposite target.",
                   "M1 high/low path bounds adverse excursion; intrabar order is unknown.",
                   "Candidate generation recall must be reported separately.",
                   "No untouched OOS inference from this in-sample scoring."]
    }
