"""Online forming extremes and closed H1/M15 confirmation, without lookahead."""
from h1_structure import analyze, _completed, _f, PIVOT_LOOKBACK


def live_locals(h1_rows, m15_rows, now_ms, symbol):
    confirmed = analyze(h1_rows, now_ms, symbol)
    out = dict(confirmed)
    out['confirmed_local'] = {k:confirmed.get(k) for k in (
        'pivot_type','pivot_price','pivot_candle_time','signal_candle_time','entry_side')}
    closed = _completed(h1_rows,now_ms,3_600_000)
    if len(closed)<PIVOT_LOOKBACK:
        return out
    # Partial candles are usable only with an explicit time of observation.
    # REST snapshots/WS frames stamp this at ingestion; historical final OHLC is
    # never treated as an intrabar observation from an earlier time.
    partial=[]; observed_extremes={}
    for row in h1_rows or []:
        seen=_f(row.get('observed_at_ms'))
        if seen is None or seen>now_ms or now_ms-seen>15_000: continue
        t,T=_f(row.get('t')),_f(row.get('T'))
        if t is not None and T is not None and t<=now_ms<T+1000:
            partial.extend(_completed([row],T+1001,3_600_000))
            observed_extremes[int(t)]=row
    newest = partial[-1] if partial else closed[-1]
    prior = [r for r in closed if r['t']<newest['t']][-PIVOT_LOOKBACK:]
    if len(prior)<PIVOT_LOOKBACK: return out
    candidates=[]
    if newest['l']<=min(r['l'] for r in prior):
        candidates.append(dict(pivot_type='LOCAL_LOW',pivot_price=newest['l'],pivot_candle_time=newest['t'],entry_side=1))
    if newest['h']>=max(r['h'] for r in prior):
        candidates.append(dict(pivot_type='LOCAL_HIGH',pivot_price=newest['h'],pivot_candle_time=newest['t'],entry_side=-1))
    # A confirmed candle is historical, not a new pending extreme.
    candidates=[c for c in candidates if c['pivot_candle_time']>int(confirmed.get('pivot_candle_time') or 0)]
    out['forming_locals']=candidates
    out['forming_local']=candidates[0] if len(candidates)==1 else None
    m15=_completed(m15_rows,now_ms,900_000)
    for candidate in candidates:
        candidate['state']='FORMING_'+candidate['pivot_type']
        candidate['observed_at_ms']=int(now_ms)
        candidate['m15_confirmation']=False
        original=observed_extremes.get(candidate['pivot_candle_time'],{})
        observed=original.get('low_observed_at_ms' if candidate['entry_side']>0 else 'high_observed_at_ms')
        observed=float(observed if observed is not None else original.get('observed_at_ms',newest['T']))
        candidate['extreme_observed_at_ms']=observed
        if len(m15)>=2:
            a,b=m15[-2:]
            contiguous=b['t']-a['t']==900_000 and 0<=now_ms-b['T']<=901_000
            after=b['T']>=observed
            candidate['m15_confirmation']=bool(contiguous and after and (
                b['l']>a['l'] and b['h']>a['h'] and b['l']>candidate['pivot_price'] if candidate['entry_side']>0
                else b['h']<a['h'] and b['l']<a['l'] and b['h']<candidate['pivot_price']))
            if candidate['m15_confirmation']:
                candidate.update(confirmation_candle_time=b['t'],confirmation_close_time=b['T'])
    # Do not allocate from a broken old low/high while its extension is pending.
    side=int(confirmed.get('entry_side') or 0)
    invalidated=any(c['entry_side']==side and (
        c['pivot_price']<float(confirmed.get('pivot_price') or 0) if side>0
        else c['pivot_price']>float(confirmed.get('pivot_price') or float('inf')))
        for c in candidates) if side else False
    if invalidated:
        out.update(entry_blocked=True,entry_block_reason='forming_extension_of_confirmed_local')
    if len(candidates)==1:
        c=candidates[0]
        out.update(pending_pivot_type=c['pivot_type'],pending_pivot_price=c['pivot_price'],pending_pivot_candle_time=c['pivot_candle_time'])
    return out


def execution_anchor(analysis, flow):
    """M15 structure + sustained tape can confirm a new forming H1 extreme.

    The closed H1 anchor remains separately visible; an unconfirmed wick alone
    never flips the executable direction.
    """
    forming=analysis.get('forming_local') or {}
    side=int(forming.get('entry_side') or 0)
    if not (side and forming.get('m15_confirmation') and flow.get('trade_data_fresh')
            and flow.get('sustained_control_side')==side):
        return analysis
    return {**analysis,**forming,'ready':True,'anchor_confirmed':True,
            'h1_direction_anchor':True,'entry_blocked':False,'entry_block_reason':None,
            'signal_candle_time':int(forming['confirmation_candle_time']),
            'signal_candle_close_time':int(forming['confirmation_close_time']),
            'confirmation_source':'observed_H1_extreme_closed_M15_and_executed_control'}
