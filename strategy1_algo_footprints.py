"""Public microstructure footprints consistent with systematic execution.

This module does not identify proprietary exchange algorithms. It extracts
observable patterns from public trades that systematic/algorithmic participants
commonly leave: persistence, burst intensity, impact efficiency, absorption,
exhaustion, and renewed participation.
"""
import math
import statistics


def _f(x,default=0.0):
    try:
        v=float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def _robust_z(value, history):
    vals=[_f(x,None) for x in history]
    vals=[x for x in vals if x is not None]
    if len(vals)<8:return 0.0
    med=statistics.median(vals)
    mad=statistics.median(abs(x-med) for x in vals)
    if mad<=1e-12:return 0.0
    return max(-8.0,min(8.0,(value-med)/(1.4826*mad)))


def footprint(side, mark, prev_mark, flow, recent):
    """Return side-aligned microstructure features using only past/current data.

    recent is a list of prior dicts with keys: mark, count60, notional60,
    aligned15, aligned30, aligned60, range_move.
    """
    side=int(side or 0)
    if side not in (-1,1):return {}
    mark=_f(mark,None);prev=_f(prev_mark,None)
    if mark is None:return {}
    a15=side*_f((flow or {}).get("flow_imbalance_15s"))
    a30=side*_f((flow or {}).get("flow_imbalance_30s"))
    a60=side*_f((flow or {}).get("flow_imbalance"))
    a300=side*_f((flow or {}).get("flow_imbalance_300s"))
    count=max(0.0,_f((flow or {}).get("trade_count_60s")))
    notional=max(0.0,_f((flow or {}).get("observed_notional_60s")))
    ret=side*(mark/prev-1.0) if prev and prev>0 else 0.0
    count_z=_robust_z(count,[x.get("count60") for x in recent])
    notional_z=_robust_z(notional,[x.get("notional60") for x in recent])
    # Aggressive flow persistence across horizons. Systematic execution tends
    # to persist instead of appearing in one isolated 15s burst.
    persistence=(max(-1,min(1,a15))+max(-1,min(1,a30))+max(-1,min(1,a60)))/3.0
    short_accel=a15-a60
    medium_accel=a30-a300
    # Price impact efficiency: favorable price response per unit of current
    # aggressive imbalance. Large imbalance with little/no price response is
    # treated as absorption rather than continuation.
    demand=max(.02,abs(a15)*.5+abs(a30)*.3+abs(a60)*.2)
    impact_eff=ret/demand
    aligned_pressure=max(0.0,a15)*.5+max(0.0,a30)*.3+max(0.0,a60)*.2
    absorption=(aligned_pressure>=.18 and ret<=.00015 and (count_z>=.5 or notional_z>=.5))
    exhaustion=(a60>=.10 and a15<=a60-.12 and ret<=0.0)
    burst=(count_z>=1.25 or notional_z>=1.25) and a15>=.16 and a30>=.10
    renewed=(burst and persistence>=.12 and ret>0.0)
    counter_absorption=(a15<=-.15 and a30<=-.10 and ret>=-.00010 and (count_z>=.5 or notional_z>=.5))
    return {
        "aligned15":a15,"aligned30":a30,"aligned60":a60,"aligned300":a300,
        "persistence":persistence,"short_accel":short_accel,"medium_accel":medium_accel,
        "trade_intensity_z":count_z,"notional_intensity_z":notional_z,
        "impact_efficiency":impact_eff,"aligned_return_15s":ret,
        "absorption":bool(absorption),"counter_absorption":bool(counter_absorption),
        "exhaustion":bool(exhaustion),"burst":bool(burst),"renewed":bool(renewed),
    }


def append_recent(recent, mark, flow, fp, maxlen=80):
    row={"mark":mark,"count60":_f((flow or {}).get("trade_count_60s")),
         "notional60":_f((flow or {}).get("observed_notional_60s")),
         "aligned15":_f((fp or {}).get("aligned15")),"aligned30":_f((fp or {}).get("aligned30")),
         "aligned60":_f((fp or {}).get("aligned60"))}
    out=list(recent or [])
    out.append(row)
    if len(out)>maxlen:out=out[-maxlen:]
    return out
