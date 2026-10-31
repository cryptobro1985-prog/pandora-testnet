"""H1 direction with event-driven pressure/price-response execution.

No candle interval determines entry, exit or re-entry. Comparison of two
consecutive traded-price auctions is a transparent causal hypothesis; its live
signal quality must be measured rather than inferred from synthetic tests.
"""
import copy,math
POLICY='H1 direction; executed pressure and causal price response'


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
 dominant=1 if buy>sell else -1 if sell>buy else 0
 direction=int(flow.get('price_direction') or 0)
 control=dominant if dominant==direction and direction in (-1,1) else 0
 return {'event_epoch':_event_epoch(flow),'aligned_pressure':side*(buy-sell)/(buy+sell),'control_side':control,
         'aligned_control':control==side,'resumed':control==side,'counter_takeover':control==-side,
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
 out=_candidate(symbol,analysis,flow)
 if out['eligible']:out['reason']='h1_executed_control_reentry'
 return out


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


def pressure_exit(position,execution_context,mark,flow):
    side=int((position or {}).get('side') or 0);entry=_f((position or {}).get('entry'));price=_f(mark)
    profile=flow_profile(flow,side)
    if entry is None or entry<=0 or price is None or price<=0 or profile is None:return None
    features=position.setdefault('features',{})
    state=features.get('pressure_state') or {'best':side*entry,'noise':0.,'phase':'HOLDING'}
    state,confirmed=advance_structure(state,side,price,profile['control_side'],profile['event_epoch'])
    features['pressure_state']=state
    return 'confirmed_counter_move_exit' if confirmed else None


def update_watch(watch,mark,execution_context,flow,stamp):
    out=copy.deepcopy(watch or {});side=int(out.get('side') or 0);price=_f(mark)
    if side not in (-1,1) or price is None or price<=0:return out
    context=out.setdefault('context',{});profile=flow_profile(flow,side)
    if profile is None:return out
    if profile['counter_takeover']:
        context['counter_pressure_seen']=True
        context['last_opposite_trade_epoch']=profile['event_epoch']
    state=context.get('resumption_state')
    if state is None:
        original=context.get('exit_pressure_state') or {}
        state={'best':-side*float(out.get('exit_price') or price),
               'noise':max(0.,float(original.get('noise') or 0.)),
               'barrier':-float(original['best']) if original.get('best') is not None else None,
               'phase':'HOLDING'}
    state,confirmed=advance_structure(state,-side,price,profile['control_side'],profile['event_epoch'])
    context['resumption_state']=state
    if confirmed and context.get('counter_pressure_seen'):
        context.update(phase='REENTRY_READY',resumption_confirmed=True,confirmation_epoch=profile['event_epoch'])
    elif not context.get('resumption_confirmed'):
        context['phase']='WAIT_RESUMPTION_STRUCTURE' if context.get('counter_pressure_seen') else 'WAIT_COUNTER_CONTROL'
    context['last_observed_epoch']=stamp
    return out


def reentry_ready(side,execution_context,mark,watch,flow,stamp):
    if not watch or int(watch.get('side') or 0)!=int(side or 0):return False
    context=watch.get('context') or {};profile=flow_profile(flow,side)
    previous=_f(context.get('last_opposite_trade_epoch'))
    return bool(context.get('counter_pressure_seen') and context.get('resumption_confirmed') and
        profile and profile['resumed'] and previous is not None and profile['event_epoch'] is not None and
        profile['event_epoch']>previous)
