"""HIGH-only flow expansion V2 for HYPE HARD120.

Three-period development rule (Jul/Aug, Sep, Oct/Nov 2026). Because September
was inspected while selecting this rule, it is NOT untouched OOS evidence.
Promotion is forward-score only.

Primary HARD120 is unchanged. This shadow can only recover HIGH candidates in
the lower retrace-fraction band [0.35,0.45):
- retrace >= 40 bps
- first-15m executed seller flow <= -0.08
- and either retrace fraction < 0.41 OR absolute retrace >= 75 bps
- >=100 trades in first 15m
"""
from __future__ import annotations

MIN_RETRACE_BPS=40.0
MIN_FRACTION=0.35
PRIMARY_FRACTION=0.45
MAX_FLOW_IMBALANCE=-0.08
FRACTION_SOFT_CEILING=0.41
STRONG_RETRACE_BPS=75.0
MIN_TRADE_COUNT=100


def qualifies(*, side:str, primary_emitted:bool, expected_side_ok:bool,
              checkpoint_fresh:bool, retrace_bps:float,
              retrace_fraction_pre_180:float, flow_15:float|None,
              trade_count:int, already_emitted:bool=False)->tuple[bool,dict]:
    frac=float(retrace_fraction_pre_180)
    retr=float(retrace_bps)
    flow=None if flow_15 is None else float(flow_15)
    quality=(frac<FRACTION_SOFT_CEILING or retr>=STRONG_RETRACE_BPS)
    checks={
        "high_only":str(side).upper()=="HIGH",
        "primary_not_emitted":not bool(primary_emitted),
        "expected_side_ok":bool(expected_side_ok),
        "checkpoint_fresh":bool(checkpoint_fresh),
        "retrace_bps":retr>=MIN_RETRACE_BPS,
        "fraction_band":MIN_FRACTION<=frac<PRIMARY_FRACTION,
        "seller_flow":flow is not None and flow<=MAX_FLOW_IMBALANCE,
        "trade_count":int(trade_count)>=MIN_TRADE_COUNT,
        "quality":bool(quality),
        "not_already_emitted":not bool(already_emitted),
    }
    ready=all(checks.values())
    return ready,{
        "ready":ready,"checks":checks,"flow_15":flow,"trade_count":int(trade_count),
        "retrace_bps":retr,"retrace_fraction_pre_180":frac,
    }


def contract()->dict:
    return {
        "name":"HARD120_HIGH_FLOW_SHADOW_V2",
        "role":"HIGH_EXPANSION_SHADOW_ONLY",
        "side":"HIGH",
        "min_retrace_bps":MIN_RETRACE_BPS,
        "min_fraction":MIN_FRACTION,
        "primary_fraction_exclusive":PRIMARY_FRACTION,
        "max_flow_imbalance_first_15m":MAX_FLOW_IMBALANCE,
        "fraction_soft_ceiling":FRACTION_SOFT_CEILING,
        "strong_retrace_bps":STRONG_RETRACE_BPS,
        "min_trade_count_first_15m":MIN_TRADE_COUNT,
        "primary_contract_unchanged":True,
        "core_flip_authorized":False,
        "historical_status":"THREE_PERIOD_DEVELOPMENT_NOT_OOS",
        "promotion":"FORWARD_SCORE_ONLY",
    }
