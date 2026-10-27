"""User-defined H1 direction with executed buy/sell dominance.
No candle-score, volume-size, price-extension or profit-only trade gates.
"""
import copy
import datetime
import math
from local_caterpillar import update_watch as m15_update_watch, reentry_ready as m15_reentry_ready
POLICY="Caterpillar 1.0 H1-M15 cycle v1.2"

def _f(x):
    try:
        n=float(x)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError,OverflowError):
        return None

def dominance(flow):
    if not isinstance(flow,dict) or not flow.get("trade_data_fresh"):
        return None
    age=_f(flow.get("latest_trade_age_seconds"))
    if age is None or not -1<=age<=15:
        return None
    buy,sell=_f(flow.get("buy_volume_60s")),_f(flow.get("sell_volume_60s"))
    if buy is not None and sell is not None:
        if min(buy,sell)<0:return None
        return 1 if buy>sell else (-1 if sell>buy else 0)
    imbalance=_f(flow.get("flow_imbalance"))
    if imbalance is None or not -1<=imbalance<=1:return None
    return 1 if imbalance>0 else (-1 if imbalance<0 else 0)

def entry_candidate(symbol,analysis,m15,flow,stamp):
    side=int((analysis or {}).get("entry_side") or 0)
    dom=dominance(flow)
    eligible=bool((analysis or {}).get("ready") and (analysis or {}).get("h1_direction_anchor")
                  and not (analysis or {}).get("entry_blocked") and side in (-1,1) and dom==side
                  and (m15 or {}).get("ready") and (m15 or {}).get("recovery_confirmed")
                  and int((m15 or {}).get("recovery_score") or 0)>=3
                  and int((m15 or {}).get("adverse_score") or 0)==0)
    imbalance=_f((flow or {}).get("flow_imbalance"))
    return dict(symbol=symbol,side=side,eligible=eligible,reason="h1_aligned_executed_flow" if eligible else
                ("waiting_for_fresh_executed_flow" if dom is None else "waiting_for_h1_side_dominance"),
                policy=POLICY,dominant_side=dom,buy_volume_60s=(flow or {}).get("buy_volume_60s"),
                sell_volume_60s=(flow or {}).get("sell_volume_60s"),
                aligned_flow=side*imbalance if imbalance is not None else None)

def pressure_exit(position,m15,mark,flow):
    """Avoid fee-generating churn on a single noisy 60-second flow reversal.

    A genuine H1 opposite pivot and the liquidation guard remain independent.
    """
    side=int((position or {}).get("side") or 0)
    if side not in (-1,1) or dominance(flow)!=-side:
        return None
    if not (m15 or {}).get("ready") or not (m15 or {}).get("strong_adverse_pressure"):
        return None
    if int((m15 or {}).get("adverse_score") or 0)<3:
        return None
    imbalance=_f((flow or {}).get("flow_imbalance"))
    count=_f((flow or {}).get("trade_count_60s"))
    notional=_f((flow or {}).get("observed_notional_60s"))
    coverage=_f((flow or {}).get("trade_coverage_seconds"))
    if (imbalance is None or side*imbalance>-.20 or count is None or count<8
            or notional is None or notional<250 or coverage is None or coverage<45):
        return None
    opened=_epoch((position or {}).get("opened"))
    observed=_f((flow or {}).get("observed_at_epoch"))
    if observed is None:
        import time
        observed=time.time()
    if opened is not None and observed-opened<30:
        return None
    return "executed_flow_counter_dominance"

def _epoch(value):
    n=_f(value)
    if n is not None:return n
    try:return datetime.datetime.fromisoformat(str(value).replace("Z","+00:00")).timestamp()
    except (ValueError,TypeError):return None

def update_watch(watch,mark,m15,flow,stamp):
    """Require a real M15-price pullback before watching for continuation."""
    normalized=copy.deepcopy(watch or {})
    context=normalized.setdefault("context",{})
    if context.get("phase")=="WAIT_RESUMPTION" and not context.get("pullback_confirmed_epoch"):
        context["phase"]="WAIT_PULLBACK"
    return m15_update_watch(normalized,mark,m15,flow,stamp)

def reentry_ready(side,m15,mark,watch,flow,stamp):
    """A fresh M15 recovery, completed pullback and aligned executed flow."""
    return bool(m15_reentry_ready(side,m15,mark,watch,flow,stamp)
                and dominance(flow)==int(side))
