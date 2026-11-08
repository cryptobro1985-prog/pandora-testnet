"""Causal HARD120 checkpoint gate for broad HYPE INTERNAL locals.

This is a paper/research layer, deliberately separate from the early ML
tactical learner. It uses only information available at decision time:

1) the candidate originated as a 6h trailing extreme;
2) no more-extreme same-side candidate replaced it for 120 minutes;
3) price retraced at least 40 bps from the extreme; and
4) that retrace recovered at least 45% of the causal 180-minute pre-move.

The checkpoint is evaluated once. A later recovery crossing is never
retroactively accepted. Thresholds were selected on the
2026-10-04..2026-11-03 archive and therefore MUST be forward-validated before
any promotion beyond PAPER.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Iterable, Mapping, Optional

HARD_AGE_S = 7_200
MIN_RETRACE_BPS = 40.0
MIN_RETRACE_FRACTION = 0.45
REQUIRED_WINDOW = "6h"
CHECKPOINT_GRACE_S = 90


@dataclass
class HardCandidate:
    side: str
    extreme_price: float
    extreme_ts_ms: int
    candidate_id: str
    pre_move_180_bps: float
    origin_windows: list[str]
    emitted: bool = False
    evaluated_stages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _completed_prior_rows(rows: Iterable[Mapping], ts_ms: int) -> list[dict]:
    out=[]
    for r in rows:
        start=int(r.get("start_ms", r.get("ts_ms", 0)) or 0)
        end=int(r.get("bar_end_ms", start + 60_000) or (start + 60_000))
        if end > int(ts_ms):
            continue
        try:
            out.append({
                "start_ms":start,
                "high":float(r["high"]),
                "low":float(r["low"]),
            })
        except Exception:
            continue
    out.sort(key=lambda z:z["start_ms"])
    return out


def pre_move_180_bps(side: str, extreme_price: float,
                     completed_m1_rows: Iterable[Mapping], ts_ms: int) -> float:
    """Causal move into the candidate using only prior completed M1 bars."""
    side=str(side).upper()
    p=float(extreme_price)
    if p <= 0 or side not in {"LOW","HIGH"}:
        return 0.0
    rows=_completed_prior_rows(completed_m1_rows, ts_ms)[-180:]
    if len(rows)<180:
        return 0.0
    if side=="LOW":
        prior_opp=max(float(r["high"]) for r in rows)
        return max(0.0,(prior_opp/p-1.0)*10_000.0)
    prior_opp=min(float(r["low"]) for r in rows)
    if prior_opp <= 0:
        return 0.0
    return max(0.0,(p/prior_opp-1.0)*10_000.0)


def more_extreme(side: str, new_price: float, old_price: float) -> bool:
    return float(new_price) < float(old_price) if str(side).upper()=="LOW" else float(new_price) > float(old_price)


def maybe_start_or_extend(
    current: Optional[HardCandidate],
    *,
    side: str,
    price: float,
    ts_ms: int,
    candidate_id: str,
    windows: Iterable[str],
    completed_m1_rows: Iterable[Mapping],
) -> Optional[HardCandidate]:
    """Start/reset lineage only on a genuine 6h candidate and a new extreme.

    Hourly stale-refreshes do not reset this lineage.  That is the entire point:
    HARD120 measures survival of the original same-side extreme.
    """
    wins=sorted({str(x) for x in windows})
    if REQUIRED_WINDOW not in wins:
        return current
    if current is not None and not more_extreme(side,price,current.extreme_price):
        return current
    pm=pre_move_180_bps(side,price,completed_m1_rows,ts_ms)
    # Never freeze a denominator from a partial post-restart window.
    if pm<=0:
        return current
    return HardCandidate(
        side=str(side).upper(),
        extreme_price=float(price),
        extreme_ts_ms=int(ts_ms),
        candidate_id=str(candidate_id),
        pre_move_180_bps=float(pm),
        origin_windows=wins,
        emitted=False,
    )


def gate_metrics(candidate: HardCandidate, *, now_ms: int, mark_price: float) -> dict:
    p=float(candidate.extreme_price)
    mark=float(mark_price)
    side=str(candidate.side).upper()
    age_s=max(0.0,(int(now_ms)-int(candidate.extreme_ts_ms))/1000.0)
    if p <= 0 or mark <= 0:
        retrace=0.0
    elif side=="LOW":
        retrace=(mark/p-1.0)*10_000.0
    else:
        retrace=(p/mark-1.0)*10_000.0
    pm=max(0.0,float(candidate.pre_move_180_bps))
    frac=(retrace/pm) if pm>0 else 0.0
    return {
        "age_s":age_s,
        "retrace_bps":retrace,
        "pre_move_180_bps":pm,
        "retrace_fraction_pre_180":frac,
        "has_6h_origin":REQUIRED_WINDOW in set(candidate.origin_windows),
        "age_ready":age_s>=HARD_AGE_S,
        "retrace_ready":retrace>=MIN_RETRACE_BPS,
        "fraction_ready":frac>=MIN_RETRACE_FRACTION,
    }


def next_signal(candidate: HardCandidate, *, now_ms: int, mark_price: float,
                expected_side: str | None = None) -> tuple[str | None,dict]:
    """Evaluate HARD120 exactly once at the causal checkpoint.

    Historical research sampled the 120-minute checkpoint. Live must not wait
    for a later recovery crossing and retroactively call it HARD120. The first
    observation at/after 120m consumes the checkpoint. A short grace tolerates
    normal scheduler/event jitter; a long restart gap marks it missed.
    """
    m=gate_metrics(candidate,now_ms=now_ms,mark_price=mark_price)
    expected_ok=expected_side is None or str(expected_side).upper()==str(candidate.side).upper()
    m["expected_side_ok"]=expected_ok
    m["checkpoint_grace_s"]=CHECKPOINT_GRACE_S
    m["evaluated_stages"]=list(candidate.evaluated_stages)

    if candidate.emitted:
        m["ready_stage"]=None;m["ready"]=False
        return None,m

    stage=None
    if m["age_s"]>=HARD_AGE_S and "HARD120" not in candidate.evaluated_stages:
        candidate.evaluated_stages.append("HARD120")
        within=m["age_s"]<=HARD_AGE_S+CHECKPOINT_GRACE_S
        m["hard120_within_checkpoint_window"]=within
        if (within and m["has_6h_origin"] and m["retrace_ready"]
                and m["fraction_ready"] and expected_ok):
            stage="HARD120"

    m["evaluated_stages"]=list(candidate.evaluated_stages)
    m["ready_stage"]=stage
    m["ready"]=stage is not None
    return stage,m


def should_emit(candidate: HardCandidate, *, now_ms: int, mark_price: float,
                expected_side: str | None = None) -> tuple[bool,dict]:
    """Backward-compatible boolean wrapper around the survival ladder."""
    stage,m=next_signal(candidate,now_ms=now_ms,mark_price=mark_price,expected_side=expected_side)
    return stage is not None,m


def contract() -> dict:
    return {
        "name":"INTERNAL_HARD120_CHECKPOINT_V2",
        "role":"TACTICAL_HARD_PAPER_ONLY",
        "age_s":HARD_AGE_S,
        "min_retrace_bps":MIN_RETRACE_BPS,
        "min_retrace_fraction_pre_180":MIN_RETRACE_FRACTION,
        "required_origin_window":REQUIRED_WINDOW,
        "same_side_invalidation":"any more-extreme same-side 6h candidate resets the clock",
        "stale_refresh_resets_clock":False,
        "checkpoint_semantics":"HARD120 is evaluated once; no late recovery crossing is retroactively accepted",
        "checkpoint_grace_s":CHECKPOINT_GRACE_S,
        "core_flip_authorized":False,
        "historical_selection_warning":"thresholds were selected on the 30D research archive; forward validation is mandatory",
    }
