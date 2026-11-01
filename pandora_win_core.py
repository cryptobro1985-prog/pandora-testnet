"""PAPER capital and pyramiding state machine, derived from the supplied core.

Entry notional is a cost basis; average entry is quantity weighted. Adds never
change realized equity. The full entry/exit commission is accounted on close.
"""
import copy
import math
from accounting import paper_pnl

STARTING_EQUITY=500.
MARGIN_FRACTION=.20
REFERENCE_LEVERAGE=25.


def allocation(equity, free, max_leverage, fraction=.20, fee=.00045):
    values=tuple(map(float,(equity,free,max_leverage,fraction,fee)))
    if not all(math.isfinite(x) for x in values) or min(values)<0 or max_leverage<1 or fraction>1:
        raise ValueError('invalid paper allocation')
    leverage=min(25.,max_leverage)
    margin=min(equity*fraction,free/(1+2*fee*leverage))
    return dict(margin=margin,leverage=leverage,notional=margin*leverage)


def pyramid_decision(position, analysis, flow, mark, max_adds=2):
    """Require profit, valid structure, stronger executed impulse and a new price extreme."""
    side=int(position['side']);f=position.get('features') or {}
    state=copy.deepcopy(f.get('pyramid_state') or {})
    level=int(f.get('pyramid_level',0))
    event=float(flow.get('decision_event_epoch') or flow.get('latest_trade_epoch') or 0)
    windows=flow.get('windows') or {};fast=windows.get('15',{})
    side_volume=float(fast.get('buy_volume' if side>0 else 'sell_volume',0))
    velocity=float(fast.get('volume_velocity',0))
    prior=float(state.get('last_impulse_price',position['entry']))
    reason='WAIT_NEW_IMPULSE'
    if level>=max_adds:reason='MAX_ADDS_REACHED'
    elif not flow.get('trade_data_fresh'):reason='FLOW_STALE'
    elif paper_pnl(position['notional'],position['entry'],mark,side)<=0:reason='POSITION_NOT_PROFITABLE'
    elif analysis.get('entry_blocked') or not analysis.get('anchor_confirmed') or int(analysis.get('entry_side') or 0)!=side:reason='LOCAL_STRUCTURE_NOT_ALIGNED'
    elif flow.get('sustained_control_side')!=side:reason='WAIT_SUSTAINED_CONTROL'
    elif flow.get('buy_absorbed' if side>0 else 'sell_absorbed'):reason='EXECUTED_VOLUME_ABSORBED'
    elif event<=float(state.get('last_add_event',0)):reason='EVENT_ALREADY_CONSUMED'
    elif side*(mark-prior)<=0:reason='WAIT_NEW_PRICE_IMPULSE'
    elif velocity<=float(state.get('baseline_velocity',0)) or side_volume<=float(state.get('baseline_side_volume',0)):reason='WAIT_STRONGER_EXECUTED_VOLUME'
    else:reason='CONFIRMED_PROFITABLE_CONTINUATION'
    state.update(phase='READY_TO_ADD' if reason=='CONFIRMED_PROFITABLE_CONTINUATION' else reason,
                 observed_event=event)
    return reason=='CONFIRMED_PROFITABLE_CONTINUATION',state


def apply_add(position, mark, margin, flow, analysis, timestamp):
    out=copy.deepcopy(position);features=out.setdefault('features',{})
    added_notional=float(margin)*float(out['leverage'])
    if margin<=0 or mark<=0 or not math.isfinite(added_notional+mark):raise ValueError('invalid add')
    total=float(out['notional'])+added_notional
    quantity=float(out['notional'])/float(out['entry'])+added_notional/mark
    average=total/quantity
    level=int(features.get('pyramid_level',0))+1
    fast=(flow.get('windows') or {}).get('15',{})
    record=dict(add_number=level,timestamp=timestamp,price=mark,added_margin=margin,
                added_notional=added_notional,total_notional=total,average_entry=average,
                flow_state=copy.deepcopy(flow),buy_volume=flow.get('buy_notional'),
                sell_volume=flow.get('sell_notional'),local_state=copy.deepcopy(analysis),
                mfe_before_add=features.get('peak_mfe_usd',0),
                mfe_after_add=features.get('peak_mfe_usd',0))
    features.setdefault('pyramid_adds',[]).append(record)
    features['original_entry']=features.get('original_entry',out['entry'])
    features['pyramid_level']=level
    features['pyramid_state']=dict(phase='WAIT_NEW_IMPULSE',last_impulse_price=mark,
        last_add_event=float(flow.get('decision_event_epoch') or flow.get('latest_trade_epoch') or 0),
        baseline_velocity=float(fast.get('volume_velocity',0)),
        baseline_side_volume=float(fast.get('buy_volume' if out['side']>0 else 'sell_volume',0)))
    out.update(entry=average,notional=total,margin=float(out['margin'])+margin)
    features['average_entry']=average
    return out,record


def mark_metrics(position,mark,flow,analysis,fee=.00045):
    out=copy.deepcopy(position);f=out.setdefault('features',{})
    pnl=paper_pnl(out['notional'],out['entry'],mark,out['side'],fee)
    peak=max(float(f.get('peak_mfe_usd',0)),pnl)
    worst=min(float(f.get('mae_usd',0)),pnl)
    f.update(current_mark=mark,current_pnl_usd=pnl,current_pnl_pct=pnl/float(out['margin'])*100,
             peak_mfe_usd=peak,mfe_usd=peak,mae_usd=worst,mfe_giveback_usd=peak-pnl,
             average_entry=out['entry'],pyramid_level=int(f.get('pyramid_level',0)),
             buy_volume=flow.get('buy_notional'),sell_volume=flow.get('sell_notional'),
             flow_imbalance=flow.get('flow_imbalance'),flow_state=copy.deepcopy(flow),
             local_state=copy.deepcopy(analysis),direction=analysis.get('entry_side'),position_side=out['side'])
    return out
