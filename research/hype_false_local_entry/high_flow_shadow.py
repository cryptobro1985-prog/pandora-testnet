"""HIGH-only flow shadow challenger for HYPE HARD120.

This module does NOT alter the primary INTERNAL_HARD120_CHECKPOINT_V2 signal.
It is a cross-period-tuned shadow experiment intended to recover HIGH locals
that are slightly below the primary retrace-fraction threshold.

Historical development observation (Oct + Jul/Aug, no longer untouched OOS):
- keep the same 6h-origin / 120m-survival / 40 bps retrace contract;
- allow retrace_fraction_pre_180 in [0.35, 0.45) ONLY for HIGH;
- require first-15m executed-trade flow <= -0.05 (seller-dominant).

The early-flow window is captured once, shortly after it completes. It is never
reconstructed retroactively after a long restart/gap.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Mapping, Optional

FLOW_WINDOW_MS=15*60_000
FLOW_CAPTURE_GRACE_MS=90_000
MIN_TRADE_COUNT=100
MIN_RETRACE_BPS=40.0
MIN_FRACTION=0.35
PRIMARY_FRACTION=0.45
MAX_FLOW_IMBALANCE=-0.05


@dataclass
class HighFlowShadowState:
    candidate_id: str
    flow_15: Optional[float]=None
    flow_15_trade_count: int=0
    flow_15_sample_end_ms: Optional[int]=None
    flow_15_missed: bool=False
    emitted: bool=False

    def to_dict(self)->dict:
        return asdict(self)


def _window(candidate_ts_ms:int)->tuple[int,int]:
    # Historical compact replay uses the 15 COMPLETE M1 bars after the
    # candidate's own minute.
    bar_end=(int(candidate_ts_ms)//60_000)*60_000+60_000
    return bar_end,bar_end+FLOW_WINDOW_MS


def capture_flow15(state:HighFlowShadowState, *, candidate_ts_ms:int,
                   trades:Iterable[Mapping], observed_ms:int)->dict:
    if state.flow_15 is not None or state.flow_15_missed:
        return {"ready":state.flow_15 is not None,"missed":state.flow_15_missed,
                "flow_15":state.flow_15,"trade_count":state.flow_15_trade_count}

    start,end=_window(candidate_ts_ms)
    if int(observed_ms)<end:
        return {"ready":False,"missed":False,"target_end_ms":end}

    delay=int(observed_ms)-end
    if delay>FLOW_CAPTURE_GRACE_MS:
        state.flow_15_missed=True
        return {"ready":False,"missed":True,"target_end_ms":end,
                "observation_delay_ms":delay}

    rows=[]
    for r in trades:
        ts=int(r.get("ts_ms") or 0)
        if start<=ts<end:
            rows.append(r)
    buy=sum(float(r.get("notional") or 0.0) for r in rows if float(r.get("side") or 0)>0)
    sell=sum(float(r.get("notional") or 0.0) for r in rows if float(r.get("side") or 0)<0)
    count=len(rows)
    den=buy+sell
    if count<MIN_TRADE_COUNT or den<=0:
        state.flow_15_missed=True
        return {"ready":False,"missed":True,"target_end_ms":end,
                "trade_count":count,"reason":"insufficient_executed_trade_tape"}

    state.flow_15=(buy-sell)/den
    state.flow_15_trade_count=count
    state.flow_15_sample_end_ms=end
    return {"ready":True,"missed":False,"flow_15":state.flow_15,
            "trade_count":count,"target_end_ms":end}


def should_emit_shadow(*, side:str, primary_emitted:bool, expected_side_ok:bool,
                       checkpoint_fresh:bool, retrace_bps:float,
                       retrace_fraction_pre_180:float,
                       state:HighFlowShadowState)->tuple[bool,dict]:
    side=str(side).upper()
    frac=float(retrace_fraction_pre_180)
    flow=state.flow_15
    checks={
        "high_only":side=="HIGH",
        "primary_not_emitted":not bool(primary_emitted),
        "expected_side_ok":bool(expected_side_ok),
        "checkpoint_fresh":bool(checkpoint_fresh),
        "retrace_bps":float(retrace_bps)>=MIN_RETRACE_BPS,
        "fraction_band":MIN_FRACTION<=frac<PRIMARY_FRACTION,
        "flow_captured":flow is not None and not state.flow_15_missed,
        "seller_flow":flow is not None and float(flow)<=MAX_FLOW_IMBALANCE,
        "not_already_emitted":not state.emitted,
    }
    ready=all(checks.values())
    return ready,{
        "ready":ready,"checks":checks,
        "flow_15":flow,"flow_15_trade_count":state.flow_15_trade_count,
        "retrace_bps":float(retrace_bps),
        "retrace_fraction_pre_180":frac,
    }


def contract()->dict:
    return {
        "name":"HARD120_HIGH_FLOW_SHADOW_V1",
        "role":"SHADOW_CHALLENGER_ONLY",
        "side":"HIGH",
        "min_retrace_bps":MIN_RETRACE_BPS,
        "min_retrace_fraction_pre_180":MIN_FRACTION,
        "max_retrace_fraction_pre_180_exclusive":PRIMARY_FRACTION,
        "max_flow_imbalance_first_15m":MAX_FLOW_IMBALANCE,
        "min_trade_count_first_15m":MIN_TRADE_COUNT,
        "flow_capture_grace_s":FLOW_CAPTURE_GRACE_MS/1000,
        "core_flip_authorized":False,
        "primary_contract_unchanged":True,
        "historical_status":"CROSS_PERIOD_TUNED_NOT_OOS",
        "promotion":"FORWARD_SCORE_ONLY",
    }
