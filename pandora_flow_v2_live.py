"""PANDORA Flow V2: executed-trade control only. No candle or H1/M15 signals.

Uses existing vetted Bybit RollingMarketData flow, margin sizing, lease,
PAPER ledger, monitoring and maintenance guard. No exchange order API.
"""
import math, time, copy

MODE_ENV="PANDORA_FLOW_V2"
EXPERIMENT="PANDORA_FLOW_V2_400"
MIN_TURNOVER_24H=1_000_000.
COUNTER_CONFIRM_NEW_TRADES=3
MIN_CONTROL_IMBALANCE=.20
# Only price noise suppresses an exit. Fee/slippage also govern fresh entries.
NOISE_FRACTION=.0004

def enabled():
    import os
    return os.getenv(MODE_ENV,"0")=="1"

def event_epoch(flow):
    try:return float(flow.get("decision_event_epoch") or flow.get("latest_trade_epoch") or 0)
    except (TypeError,ValueError,OverflowError):return 0.

def current_side(flow):
    if not flow or not flow.get("trade_data_fresh") or not flow.get("evidence_ready"):return 0
    if float(flow.get("trade_coverage_seconds") or 0)<15:return 0
    sustained=int(flow.get("sustained_control_side") or 0)
    fast=int(flow.get("fast_control_side") or 0)
    context=int(flow.get("context_control_side") or 0)
    direction=int(flow.get("price_direction") or 0)
    # An isolated burst / simple BUY majority is not independent control.
    if sustained not in (-1,1) or context!=sustained or direction!=sustained:return 0
    if fast==-sustained:return 0
    if bool(flow.get("buy_absorbed" if sustained>0 else "sell_absorbed")):return 0
    if abs(float(flow.get("flow_imbalance") or 0))<MIN_CONTROL_IMBALANCE:return 0
    return sustained

def analysis_for_flow(side,flow,mark):
    """Compatibility metadata ONLY for existing risk/sizing/ledger signatures.
    Contains no candle-based direction, local price or hidden M15 filter.
    """
    event=event_epoch(flow)
    return dict(ready=True,entry_side=side,anchor_confirmed=True,
      h1_direction_anchor=False,entry_blocked=False,live_structure_fresh=True,
      pivot_type=None,pivot_price=None,pivot_candle_time=0,
      signal_candle_time=int(event*1000000),flow_v2=True,
      confirmation_source="EXECUTED_PUBLIC_TRADES_ONLY",
      flow_control_side=side,experiment=EXPERIMENT)

def entry_candidate(symbol,flow,*,last_exit_event=0):
    side=current_side(flow);event=event_epoch(flow)
    fresh=bool(side and event and event>float(last_exit_event or 0))
    return dict(symbol=symbol,side=side,eligible=fresh,flow_v2=True,
      reason="fresh_sustained_executed_buy_control" if fresh and side>0 else
             "fresh_sustained_executed_sell_control" if fresh else
             "waiting_new_executed_control_after_exit" if side else
             "waiting_fresh_sustained_executed_control",
      event_epoch=event)

def exit_reason(position,mark,flow):
    """Counter control needs three distinct exchange trade events plus price response.

    Positive LONG MFE isn't an exit by itself. SHORT bounces and LONG dips hold
    unless a real SELL/BUY control transfer occurs.
    """
    f=position.setdefault("features",{})
    state=f.get("exit_control_state") or {}
    side=int(position["side"])
    if not flow or not flow.get("trade_data_fresh") or mark is None:
        f["exit_decision"]={"reason":"DATA_UNCERTAIN_no_discretionary_exit"}
        return None
    event=event_epoch(flow);last=float(state.get("last_event_epoch") or 0)
    if event<=last:
        f["exit_decision"]={"reason":"no_new_executed_trade","observed_events":state.get("new_trade_count",0)}
        return None
    counter=int(flow.get("exit_control_side") or 0)==-side
    price_direction=int(flow.get("price_direction") or 0)
    ref=float(state.get("favorable_peak") or position.get("entry") or mark)
    peak=max(ref,float(mark)) if side>0 else min(ref,float(mark))
    change=side*(peak/float(mark)-1.0)
    # When no favorable MFE exists, genuine adverse flow still warrants exit.
    entry=float(position.get("entry") or mark)
    adverse=side*(entry/float(mark)-1.0)
    material=bool(change>=NOISE_FRACTION or adverse>=NOISE_FRACTION)
    qualified=bool(counter and price_direction==-side and material)
    count=int(state.get("new_trade_count") or 0)+1 if qualified and int(state.get("counter_side") or 0)==-side else (1 if qualified else 0)
    state={"last_event_epoch":event,"new_trade_count":count,
           "counter_side":-side if qualified else 0,
           "favorable_peak":peak,"phase":"OBSERVING" if count else "HOLD"}
    f["exit_control_state"]=state
    f["exit_decision"]={"reason":"confirmed_flow_counter_takeover" if count>=COUNTER_CONFIRM_NEW_TRADES else
             "counterflow_pending_independent_trades" if count else "flow_control_intact_or_micro_pullback",
             "observed_events":count,"required_events":COUNTER_CONFIRM_NEW_TRADES,
             "fast_control_side":flow.get("fast_control_side"),
             "sustained_control_side":flow.get("sustained_control_side"),
             "context_control_side":flow.get("context_control_side"),
             "exit_control_side":flow.get("exit_control_side"),
             "buy_notional":flow.get("buy_notional"),"sell_notional":flow.get("sell_notional"),
             "flow_imbalance":flow.get("flow_imbalance"),"event_epoch":event,
             "mark":mark,"adverse_from_entry":adverse,"giveback_from_peak":change}
    return "confirmed_counter_move_exit" if count>=COUNTER_CONFIRM_NEW_TRADES else None
