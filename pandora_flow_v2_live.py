"""PANDORA Flow V2: executed-trade control only. No candle or H1/M15 signals.

Uses existing vetted Bybit RollingMarketData flow, margin sizing, lease,
PAPER ledger, monitoring and maintenance guard. No exchange order API.
"""
import math, time, copy, threading
from pandora_pump_structure import advance as pump_advance, candidate as pump_candidate, exit_reason as pump_exit

MODE_ENV="PANDORA_FLOW_V2"
EXPERIMENT="PANDORA_PUMP_STRUCTURE_V3_400"
MIN_TURNOVER_24H=1_000_000.
COUNTER_CONFIRM_NEW_TRADES=3
MIN_CONTROL_IMBALANCE=.20
# Only price noise suppresses an exit. Fee/slippage also govern fresh entries.
NOISE_FRACTION=.0004

_STRUCTURE_LOCK=threading.RLock()
_STRUCTURES={}

def restore_structure(state):
 with _STRUCTURE_LOCK:
  _STRUCTURES.clear();_STRUCTURES.update(copy.deepcopy(state or {}))

def snapshot_structure():
 with _STRUCTURE_LOCK:return copy.deepcopy(_STRUCTURES)

def observe_structure(symbol,flow,mark=None):
 with _STRUCTURE_LOCK:
  value=pump_advance(_STRUCTURES.get(symbol),flow,mark or (flow or {}).get("last_price"))
  _STRUCTURES[symbol]=value
  return copy.deepcopy(value)

def enabled():
    import os
    return os.getenv(MODE_ENV,"0")=="1"

def event_epoch(flow):
    try:return float(flow.get("decision_event_epoch") or flow.get("latest_trade_epoch") or 0)
    except (TypeError,ValueError,OverflowError):return 0.

def current_side(flow):
 if not flow or not flow.get("trade_data_fresh"):return 0
 # Monitor-only; never advertises a SHORT without a confirmed support break.
 return 1 if (flow.get("sustained_control_side")==1 and flow.get("evidence_ready")) else 0

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
 structure=observe_structure(symbol,flow)
 return {**pump_candidate(symbol,flow,structure,last_exit_event),
         "flow_v2":True,"event_epoch":event_epoch(flow)}

def exit_reason(position,mark,flow):
 structure=observe_structure(position["symbol"],flow,mark)
 return pump_exit(position,mark,flow,structure)
