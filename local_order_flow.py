"""H1 direction with event-driven pressure/price-response execution.

No candle interval determines entry, exit or re-entry. Comparison of two
consecutive traded-price auctions is a transparent causal hypothesis; its live
signal quality must be measured rather than inferred from synthetic tests.
"""
import copy,math
from pandora_flow import MIN_CONTROL_IMBALANCE
POLICY='H1 direction; executed pressure and causal price response'
EXIT_CONTROL_CONFIRM_SECONDS=3.0
EXIT_CONTROL_MAX_EVENT_GAP_SECONDS=5.0
EXIT_CONTROL_EVIDENCE_WINDOW_SECONDS=15.0


def _f(value):
 try:value=float(value)
 except (TypeError,ValueError,OverflowError):return None
 return value if math.isfinite(value) else None


def _event_epoch(flow):
 return _f((flow or {}).get('decision_event_epoch') or (flow or {}).get('latest_trade_epoch'))


def flow_profile(flow,side):
 side=int(side or 0)
 if side not in (-1,1) or not isinstance(flow,dict) or not flow.get('trade_data_fresh'):return None
 age=_f(flow.get('latest_trade_age_seconds'));limit=_f(flow.get('freshness_limit_seconds')) or 60.
 buy,sell=(_f(flow.get(k)) for k in ('buy_notional','sell_notional'))
 if age is None or not 0<=age<=limit or buy is None or sell is None or min(buy,sell)<0 or buy+sell<=0:return None
 imbalance=(buy-sell)/(buy+sell)
 dominant=1 if imbalance>=MIN_CONTROL_IMBALANCE else -1 if imbalance<=-MIN_CONTROL_IMBALANCE else 0
 direction=int(flow.get('price_direction') or 0)
 control=dominant if dominant==direction and direction in (-1,1) else 0
 entry_control=control
 # Fast corroborated control can reduce existing risk without waiting for old
 # minute volume to expire. New entry/reentry still requires minute context.
 # default explicit test flows without a fast key keep their sustained contract.
 if 'windows' in flow:
  rich=int(flow.get('sustained_control_side') or 0)
  entry_control=rich if rich==dominant and rich in (-1,1) else 0
  fast=int(flow.get('fast_control_side') or 0) if 'fast_control_side' in flow else entry_control
  exit_side=int(flow.get('exit_control_side',fast) or 0)
  control=exit_side if exit_side in (-1,1) else 0
 return {'event_epoch':_event_epoch(flow),'aligned_pressure':side*(buy-sell)/(buy+sell),'control_side':control,
         'entry_control_side':entry_control,
         'aligned_control':entry_control==side,'resumed':control==side,'counter_takeover':control==-side,
         'weakening':direction==-side or side*(buy-sell)<0,'price_direction':direction}


def dominance(flow):
 if not isinstance(flow,dict) or not flow.get('trade_data_fresh'):return None
 buy,sell=(_f(flow.get(k)) for k in ('buy_notional','sell_notional'))
 if buy is None or sell is None or min(buy,sell)<0 or buy+sell<=0:return None
 return 1 if buy>sell else -1 if sell>buy else 0


def _candidate(symbol,analysis,flow):
 side=int((analysis or {}).get('entry_side') or 0)
 h1=bool((analysis or {}).get('ready') and (analysis or {}).get('anchor_confirmed') and (analysis or {}).get('h1_direction_anchor') and not (analysis or {}).get('entry_blocked') and side in (-1,1))
 profile=flow_profile(flow,side)
 eligible=bool(h1 and profile and profile['aligned_control'])
 reason='h1_executed_control_entry' if eligible else 'waiting_for_h1_local' if not h1 else 'waiting_for_valid_executed_flow' if profile is None else 'waiting_for_executed_control_and_price_response'
 return {'symbol':symbol,'side':side,'eligible':eligible,'reason':reason,'policy':POLICY,
         'aligned_pressure':profile['aligned_pressure'] if profile else None,'event_epoch':profile['event_epoch'] if profile else None}


def initial_entry_candidate(symbol,analysis,execution_context,flow,stamp):return _candidate(symbol,analysis,flow)
def entry_candidate(symbol,analysis,execution_context,flow,stamp):
 side=int((analysis or {}).get('entry_side') or 0)
 h1=bool((analysis or {}).get('ready') and (analysis or {}).get('anchor_confirmed')
     and (analysis or {}).get('h1_direction_anchor') and not (analysis or {}).get('entry_blocked')
     and side in (-1,1))
 profile=flow_profile(flow,side)
 eligible=bool(h1 and profile and profile['resumed'])
 reason='h1_executed_control_reentry' if eligible else 'waiting_for_h1_local' if not h1 else 'waiting_for_valid_executed_flow' if profile is None else 'waiting_for_executed_control_resumption'
 return {'symbol':symbol,'side':side,'eligible':eligible,'reason':reason,'policy':POLICY,
         'aligned_pressure':profile['aligned_pressure'] if profile else None,
         'event_epoch':profile['event_epoch'] if profile else None}


def advance_structure(state,direction,mark,control,event_epoch):
    """Confirm counter-movement from market structure, never a minute/ROI gate.

    A small bounce remains provisional. A fresh favorable extreme absorbs it and
    learns its size as observed noise. Transfer requires opposite executed
    control plus either a break of the previous absorbed-bounce boundary, or a
    failed continuation retest followed by a new counter extreme. The move must
    exceed previously observed absorbed reactions. No hindsight is used.
    """
    out=copy.deepcopy(state or {});price=_f(mark);event=_f(event_epoch)
    if price is None or price<=0 or event is None:return out,False
    if event<=float(out.get('last_event_epoch') or 0):return out,False
    out['last_event_epoch']=event;x=direction*price
    best=_f(out.get('best'))
    if best is None:out.update(best=x,phase='HOLDING',noise=0.);return out,False
    noise=max(0.,_f(out.get('noise')) or 0.)
    candidate=out.get('candidate')
    if x>best:
        if candidate:
            noise=max(noise,best-float(candidate['counter_extreme']))
            out['barrier']=float(candidate['counter_extreme'])
        out.update(best=x,noise=noise,candidate=None,phase='HOLDING')
        return out,False
    if not candidate and x<best:
        candidate={'counter_extreme':x,'retest_best':None}
        out['candidate']=candidate;out['phase']='WEAKENING_OBSERVE'
    if not candidate:return out,False
    previous_counter=float(candidate['counter_extreme'])
    barrier=_f(out.get('barrier'))
    material=best-x>noise
    structural_break=barrier is not None and x<barrier
    failed_retest=(candidate.get('retest_best') is not None and
                   float(candidate['retest_best'])<best and x<previous_counter)
    if control==-direction and material and (structural_break or failed_retest):
        out['phase']='COUNTER_MOVE_CONFIRMED';out['confirmation_epoch']=event
        out['confirmation_basis']='prior_structure_break' if structural_break else 'failed_continuation_retest'
        return out,True
    if control==direction and x>previous_counter:
        candidate['retest_best']=max(x,float(candidate.get('retest_best') or x))
        out['phase']='CHECK_CONTINUATION'
    if x<previous_counter:
        candidate['counter_extreme']=x
        # A continuing counter leg is not a new retest.
        if control==-direction and candidate.get('retest_best') is None:out['phase']='WEAKENING_OBSERVE'
    return out,False


def _confirmed_counter_control(position,profile):
    """Accumulate fresh counter evidence; brief neutral prints pause it.

    Neutral intervals never add confirmation time. Own-side control, unknown
    tape, a >5s event gap or evidence older than 15s invalidate the observation.
    Re-reading an execution cannot advance either duration or confirmation.
    """
    features=position.setdefault('features',{})
    event=profile['event_epoch'] if profile else None
    previous=features.get('exit_control_state') or {}
    if not profile or event is None:
        features['exit_control_state']={'phase':'UNKNOWN','reason':'fresh_executed_flow_required','observed_seconds':0.}
        return False
    if profile['control_side']==int(position['side']):
        features['exit_control_state']={'phase':'HOLD','reason':'own_side_control','observed_seconds':0.}
        return False
    last=_f(previous.get('last_event_epoch'))
    start=_f(previous.get('first_event_epoch'))
    elapsed=max(0.,_f(previous.get('observed_seconds')) or 0.)
    if (start is None or last is None or event<last or event-last>EXIT_CONTROL_MAX_EVENT_GAP_SECONDS
            or event-start>EXIT_CONTROL_EVIDENCE_WINDOW_SECONDS):
        start=event;last=event;elapsed=0.
    if not profile['counter_takeover']:
        features['exit_control_state']={'phase':'PAUSED','reason':'counter_control_temporarily_unconfirmed',
            'first_event_epoch':start,'last_event_epoch':event,'observed_seconds':elapsed,
            'required_seconds':EXIT_CONTROL_CONFIRM_SECONDS,'control_side':0}
        return False
    if event>last and previous.get('phase') in ('OBSERVING','CONFIRMED'):
        elapsed+=event-last
    ready=elapsed>=EXIT_CONTROL_CONFIRM_SECONDS
    features['exit_control_state']={'phase':'CONFIRMED' if ready else 'OBSERVING',
        'reason':'counter_control_confirmed' if ready else 'more_counter_executions_required',
        'first_event_epoch':start,'last_event_epoch':event,'observed_seconds':elapsed,
        'required_seconds':EXIT_CONTROL_CONFIRM_SECONDS,'control_side':profile['control_side']}
    return ready


def pressure_exit(position,execution_context,mark,flow,*,opposite_local_confirmed=False):
    if not isinstance(position,dict):return None
    side=int((position or {}).get('side') or 0);entry=_f((position or {}).get('entry'));price=_f(mark)
    features=position.setdefault('features',{})
    if opposite_local_confirmed:
        features['exit_control_state']={'phase':'CONFIRMED','reason':'opposite_active_local','observed_seconds':0.}
        features['exit_decision']={'counter_control_ready':True,'structure_ready':True,
            'opposite_local_confirmed':True,'control_basis':'confirmed_active_local',
            'reason':'opposite_confirmed_h1_local'}
        return 'opposite_confirmed_h1_local'
    profile=flow_profile(flow,side)
    if entry is None or entry<=0 or price is None or price<=0 or profile is None:
        features['exit_control_state']={'phase':'UNKNOWN','reason':'fresh_executed_flow_required','observed_seconds':0.}
        features['exit_decision']={'counter_control_ready':False,'structure_ready':False,
            'opposite_local_confirmed':False,'control_basis':'unavailable',
            'reason':'fresh_executed_flow_and_valid_mark_required'}
        return None
    state=features.get('pressure_state') or {'best':side*entry,'noise':0.,'phase':'HOLDING'}
    state,confirmed=advance_structure(state,side,price,profile['control_side'],profile['event_epoch'])
    features['pressure_state']=state
    takeover=bool(profile['counter_takeover'])
    features['exit_control_state']={'phase':'CONFIRMED' if takeover and confirmed else 'OBSERVING' if takeover else 'HOLD',
        'reason':'counter_control_and_price_transfer_confirmed' if takeover and confirmed
            else 'price_transfer_not_confirmed' if takeover else 'counter_control_not_confirmed',
        'observed_seconds':0.,'control_side':profile['control_side'],
        'last_event_epoch':profile['event_epoch']}
    features['exit_decision']={'counter_control_ready':takeover,'structure_ready':bool(confirmed),
        'opposite_local_confirmed':False,
        'control_basis':(flow or {}).get('exit_control_basis','explicit_flow'),
        'reason':'confirmed_counter_move_exit' if takeover and confirmed
            else 'price_structure_not_confirmed' if takeover else 'counter_control_not_confirmed'}
    return 'confirmed_counter_move_exit' if takeover and confirmed else None

def update_watch(watch,mark,execution_context,flow,stamp):
    out=copy.deepcopy(watch or {});side=int(out.get('side') or 0);price=_f(mark)
    if side not in (-1,1) or price is None or price<=0:return out
    context=out.setdefault('context',{});profile=flow_profile(flow,side)
    if profile is None:return out
    event=profile['event_epoch']
    if profile['counter_takeover']:
        context['counter_pressure_seen']=True
        context['last_opposite_trade_epoch']=event
        # Preserve the actual observed pullback extreme. This is causal market
        # structure, not a percentage stop or an invented threshold.
        x=side*price
        prior=_f(context.get('counter_extreme_x'))
        context['counter_extreme_x']=x if prior is None else min(prior,x)
        context['phase']='WAIT_RESUMPTION'
        context['resumption_confirmed']=False
    elif context.get('counter_pressure_seen') and profile['resumed']:
        previous=_f(context.get('last_opposite_trade_epoch'))
        if previous is not None and event is not None and event>previous:
            context.update(phase='REENTRY_READY',resumption_confirmed=True,confirmation_epoch=event)
    elif not context.get('counter_pressure_seen'):
        context['phase']='WAIT_COUNTER_CONTROL'
    context['last_observed_epoch']=stamp
    return out

def reentry_ready(side,execution_context,mark,watch,flow,stamp):
    if not watch or int(watch.get('side') or 0)!=int(side or 0):return False
    context=watch.get('context') or {};profile=flow_profile(flow,side)
    previous=_f(context.get('last_opposite_trade_epoch'))
    return bool(context.get('counter_pressure_seen') and profile and profile['resumed']
        and previous is not None and profile['event_epoch'] is not None
        and profile['event_epoch']>previous)
