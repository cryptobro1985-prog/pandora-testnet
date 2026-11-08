"""EARLY60 strong-reversal shadow for HYPE INTERNAL locals.

Research/paper only. This challenger NEVER changes the primary HARD120 contract
and NEVER authorizes a core flip.

Frozen historical-tuned contract:
- reuse the same 6h-origin HardCandidate lineage;
- sample exactly once at the first completed M1 close at/after +60 minutes;
- retrace >= 80 bps;
- retrace / causal pre-move-180 >= 0.60;
- first 15 complete M1 minutes after the candidate must show reversal-direction
  executed-trade flow >= +0.20 (LOW: buyers dominate, HIGH: sellers dominate);
- at least 100 trades in that 15m tape;
- no retroactive signal after a long restart.

The rule cleared the historical 80/40 gate on both inspected periods but was
selected after inspecting history. It remains FORWARD_SCORE_ONLY.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Mapping, Optional

AGE_S=3_600
MIN_RETRACE_BPS=80.0
MIN_RETRACE_FRACTION=0.60
MIN_REVERSAL_FLOW=0.20
MIN_TRADE_COUNT=100
FLOW_WINDOW_MS=15*60_000
FLOW_CAPTURE_GRACE_MS=90_000
CHECKPOINT_GRACE_S=90


@dataclass
class Early60State:
    candidate_id: str
    flow_15: Optional[float]=None
    flow_15_trade_count: int=0
    flow_15_sample_end_ms: Optional[int]=None
    flow_15_missed: bool=False
    checkpoint_evaluated: bool=False
    checkpoint_missed: bool=False
    emitted: bool=False

    def to_dict(self)->dict:
        return asdict(self)


def _flow_window(candidate_ts_ms:int)->tuple[int,int]:
    candidate_bar_end=(int(candidate_ts_ms)//60_000)*60_000+60_000
    return candidate_bar_end,candidate_bar_end+FLOW_WINDOW_MS


def capture_flow15(state:Early60State, *, candidate_ts_ms:int,
                   trades:Iterable[Mapping], observed_ms:int)->dict:
    if state.flow_15 is not None or state.flow_15_missed:
        return {"ready":state.flow_15 is not None,"missed":state.flow_15_missed,
                "flow_15":state.flow_15,"trade_count":state.flow_15_trade_count}
    start,end=_flow_window(candidate_ts_ms)
    if int(observed_ms)<end:
        return {"ready":False,"missed":False,"target_end_ms":end}
    delay=int(observed_ms)-end
    if delay>FLOW_CAPTURE_GRACE_MS:
        state.flow_15_missed=True
        return {"ready":False,"missed":True,"target_end_ms":end,
                "observation_delay_ms":delay}
    rows=[r for r in trades if start<=int(r.get("ts_ms") or 0)<end]
    buy=sum(float(r.get("notional") or 0.0) for r in rows if float(r.get("side") or 0)>0)
    sell=sum(float(r.get("notional") or 0.0) for r in rows if float(r.get("side") or 0)<0)
    count=len(rows);den=buy+sell
    if count<MIN_TRADE_COUNT or den<=0:
        state.flow_15_missed=True
        return {"ready":False,"missed":True,"target_end_ms":end,
                "trade_count":count,"reason":"insufficient_executed_trade_tape"}
    state.flow_15=(buy-sell)/den
    state.flow_15_trade_count=count
    state.flow_15_sample_end_ms=end
    return {"ready":True,"missed":False,"flow_15":state.flow_15,
            "trade_count":count,"target_end_ms":end}


def checkpoint_sample(candidate_ts_ms:int, completed_m1_rows:Iterable[Mapping],
                      observed_ms:int)->Optional[dict]:
    target=int(candidate_ts_ms)+AGE_S*1000
    best=None
    for r in completed_m1_rows:
        start=int(r.get("start_ms",r.get("ts_ms",0)) or 0)
        end=int(r.get("bar_end_ms",start+60_000) or (start+60_000))
        if end<target or end>int(observed_ms):
            continue
        try:close=float(r["close"])
        except Exception:continue
        if close<=0:continue
        if best is None or end<best["sample_ts_ms"]:
            best={"sample_ts_ms":end,"mark_price":close}
    if best is None:return None
    best["target_ts_ms"]=target
    best["observation_delay_s"]=max(0.0,(int(observed_ms)-int(best["sample_ts_ms"]))/1000.0)
    best["fresh_observation"]=best["observation_delay_s"]<=CHECKPOINT_GRACE_S
    return best


def metrics(*, side:str, extreme_price:float, pre_move_180_bps:float,
            mark_price:float, state:Early60State, expected_side:str|None=None)->dict:
    side=str(side).upper();p=float(extreme_price);mark=float(mark_price)
    if p<=0 or mark<=0:
        retrace=0.0
    elif side=="LOW":
        retrace=(mark/p-1.0)*10_000.0
    else:
        retrace=(p/mark-1.0)*10_000.0
    pre=max(0.0,float(pre_move_180_bps))
    frac=retrace/pre if pre>0 else 0.0
    raw=state.flow_15
    rev_flow=None if raw is None else (float(raw) if side=="LOW" else -float(raw))
    expected_ok=expected_side is None or str(expected_side).upper()==side
    return {
        "retrace_bps":retrace,
        "pre_move_180_bps":pre,
        "retrace_fraction_pre_180":frac,
        "flow_15":raw,
        "reversal_flow_15":rev_flow,
        "flow_15_trade_count":state.flow_15_trade_count,
        "expected_side_ok":expected_ok,
        "retrace_ready":retrace>=MIN_RETRACE_BPS,
        "fraction_ready":frac>=MIN_RETRACE_FRACTION,
        "flow_ready":rev_flow is not None and rev_flow>=MIN_REVERSAL_FLOW,
        "trade_count_ready":state.flow_15_trade_count>=MIN_TRADE_COUNT,
    }


def evaluate_once(state:Early60State, *, side:str, extreme_price:float,
                  pre_move_180_bps:float, sample:Optional[Mapping],
                  expected_side:str|None=None)->tuple[bool,dict]:
    """Consume the +60m checkpoint once. No late crossing is accepted."""
    if state.emitted:
        return False,{"ready":False,"reason":"already_emitted"}
    if state.checkpoint_evaluated:
        return False,{"ready":False,"reason":"checkpoint_already_consumed",
                      "checkpoint_missed":state.checkpoint_missed}
    if sample is None:
        return False,{"ready":False,"reason":"waiting_checkpoint"}

    state.checkpoint_evaluated=True
    fresh=bool(sample.get("fresh_observation"))
    if not fresh:
        state.checkpoint_missed=True

    m=metrics(side=side,extreme_price=extreme_price,
              pre_move_180_bps=pre_move_180_bps,
              mark_price=float(sample.get("mark_price") or 0.0),
              state=state,expected_side=expected_side)
    m.update({
        "checkpoint_fresh":fresh,
        "sample_ts_ms":int(sample.get("sample_ts_ms") or 0),
        "target_ts_ms":int(sample.get("target_ts_ms") or 0),
        "observation_delay_s":float(sample.get("observation_delay_s") or 0.0),
        "flow_captured":state.flow_15 is not None and not state.flow_15_missed,
        "checkpoint_missed":state.checkpoint_missed,
    })
    ready=all((
        fresh,m["expected_side_ok"],m["retrace_ready"],m["fraction_ready"],
        m["flow_ready"],m["trade_count_ready"],m["flow_captured"],
    ))
    m["ready"]=bool(ready)
    if ready:
        state.emitted=True
    return bool(ready),m


def contract()->dict:
    return {
        "name":"EARLY60_STRONG_REVERSAL_SHADOW_V1",
        "role":"TACTICAL_EARLY_SHADOW_ONLY",
        "age_s":AGE_S,
        "min_retrace_bps":MIN_RETRACE_BPS,
        "min_retrace_fraction_pre_180":MIN_RETRACE_FRACTION,
        "min_reversal_flow_first_15m":MIN_REVERSAL_FLOW,
        "min_trade_count_first_15m":MIN_TRADE_COUNT,
        "required_origin_window":"6h",
        "checkpoint_semantics":"one-shot first completed M1 close at/after +60m",
        "checkpoint_grace_s":CHECKPOINT_GRACE_S,
        "flow_capture_grace_s":FLOW_CAPTURE_GRACE_MS/1000,
        "same_side_invalidation":"inherits HardCandidate 6h lineage replacement",
        "core_flip_authorized":False,
        "primary_contract_unchanged":True,
        "historical_status":"DUAL_PERIOD_TUNED_ZERO_ADDED_FALSE_NOT_UNTOUCHED_OOS",
        "promotion":"FORWARD_SCORE_ONLY",
    }
