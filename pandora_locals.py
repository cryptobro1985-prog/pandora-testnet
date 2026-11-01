"""Online forming extremes and closed H1/M15 confirmation, without lookahead."""
from h1_structure import analyze, _completed, _f, PIVOT_LOOKBACK


def _closed_m15_local(rows, now_ms):
    """Latest causal M15 reversal, including higher lows within a rising H1.

    A lower-timeframe pivot need not be a four-hour extreme. Requiring that
    previously prevented a confirmed higher low from changing an old SHORT.
    """
    candles=_completed(rows,now_ms,900_000)
    if len(candles)<PIVOT_LOOKBACK+2:return None
    if now_ms-candles[-1]['T']>1_020_000:return None
    if any(b['t']-a['t']!=900_000 for a,b in zip(candles,candles[1:])):return None
    high=low=anchor=None
    for index,bar in enumerate(candles):
        confirmations=[]
        if high is not None:
            if bar['h']>=high['h']:high=None
            elif bar['l']<high['l']:
                confirmations.append((-1,high));high=None
        if low is not None:
            if bar['l']<=low['l']:low=None
            elif bar['h']>low['h']:
                confirmations.append((1,low));low=None
        if len(confirmations)==1:
            side,pivot=confirmations[0]
            if anchor is None or pivot['t']>anchor['pivot_candle_time']:
                anchor=dict(entry_side=side,pivot_type='LOCAL_LOW' if side>0 else 'LOCAL_HIGH',
                    pivot_price=pivot['l'] if side>0 else pivot['h'],pivot_candle_time=pivot['t'],
                    signal_candle_time=bar['t'],signal_candle_close_time=bar['T'],
                    confirmation_candle_time=bar['t'],confirmation_close_time=bar['T'],
                    confirmation_close=bar['c'],m15_confirmation=True,
                    state='CONFIRMED_LOCAL_LOW' if side>0 else 'CONFIRMED_LOCAL_HIGH')
        if index>=PIVOT_LOOKBACK:
            preceding=candles[index-PIVOT_LOOKBACK:index]
            if bar['h']>=max(c['h'] for c in preceding):high=bar
            if bar['l']<=min(c['l'] for c in preceding):low=bar
    if anchor is None:return None
    # Preserve historical pivots but do not propose an already broken reference.
    later=[c for c in candles if c['t']>anchor['pivot_candle_time']]
    if anchor['entry_side']>0 and any(c['l']<=anchor['pivot_price'] for c in later):return None
    if anchor['entry_side']<0 and any(c['h']>=anchor['pivot_price'] for c in later):return None
    return anchor


def entry_structure_valid(analysis, mark, side):
    """A historical confirmed local never licenses entry beyond its invalidation."""
    mark=_f(mark);pivot=_f((analysis or {}).get('pivot_price'))
    if mark is None or pivot is None or min(mark,pivot)<=0 or side not in (-1,1):return False
    if int((analysis or {}).get('entry_side') or 0)!=side:return False
    if analysis.get('entry_blocked') or not analysis.get('live_structure_fresh',True):return False
    return mark>pivot if side>0 else mark<pivot


def _with_execution_local(analysis):
    out=dict(analysis)
    source=out.get('confirmation_source') or 'closed_H1_structure'
    out['execution_local']=({**{k:out.get(k) for k in (
        'pivot_type','pivot_price','pivot_candle_time','signal_candle_time',
        'signal_candle_close_time','entry_side')},'confirmation_source':source,
        'interval':'15m' if 'M15' in source else '1h'}
        if out.get('entry_side') in (-1,1) and out.get('pivot_price') is not None else None)
    return out


def live_locals(h1_rows, m15_rows, now_ms, symbol):
    confirmed = analyze(h1_rows, now_ms, symbol)
    out = dict(confirmed)
    out['confirmed_local'] = {k:confirmed.get(k) for k in (
        'pivot_type','pivot_price','pivot_candle_time','signal_candle_time','entry_side')}
    m15_anchor=_closed_m15_local(m15_rows,now_ms)
    out['m15_confirmed_local']=m15_anchor if m15_anchor and (
        m15_anchor['signal_candle_time']>int(confirmed.get('signal_candle_time') or 0)
        and m15_anchor['pivot_candle_time']>int(confirmed.get('pivot_candle_time') or 0)) else None
    closed = _completed(h1_rows,now_ms,3_600_000)
    if len(closed)<PIVOT_LOOKBACK:
        return out
    # Partial candles are usable only with an explicit time of observation.
    # REST snapshots/WS frames stamp this at ingestion; historical final OHLC is
    # never treated as an intrabar observation from an earlier time.
    partial=[]; observed_extremes={}; stale_partial=False
    for row in h1_rows or []:
        seen=_f(row.get('observed_at_ms'))
        if seen is None or seen<=0 or seen>now_ms: continue
        t,T=_f(row.get('t')),_f(row.get('T'))
        if t is not None and T is not None and t<=now_ms<T+1000:
            partial.extend(_completed([row],T+1001,3_600_000))
            observed_extremes[int(t)]=row
            stale_partial=now_ms-seen>15_000
    partial.sort(key=lambda row:row['t'])
    out['live_structure_fresh']=not stale_partial
    if stale_partial:out.update(entry_blocked=True,entry_block_reason='stale_live_structure')
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
            relevant=[r for r in m15 if r['t']>=candidate['pivot_candle_time']]
            consistent=all(r['l']>=candidate['pivot_price'] for r in relevant) if candidate['entry_side']>0 else all(r['h']<=candidate['pivot_price'] for r in relevant)
            candidate['m15_confirmation']=bool(not stale_partial and consistent and contiguous and after and (
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
    # Prefer a strictly newer closed-M15 reversal over the old H1 direction.
    # It is executable only when the actual tape confirms the same direction.
    m15=analysis.get('m15_confirmed_local') or {}
    if (analysis.get('live_structure_fresh',True) and m15.get('m15_confirmation')
            and flow.get('trade_data_fresh')
            and flow.get('sustained_control_side')==m15.get('entry_side')):
        return _with_execution_local({**analysis,**m15,'ready':True,'anchor_confirmed':True,
                'h1_direction_anchor':True,'entry_blocked':False,'entry_block_reason':None,
                'confirmation_source':'closed_M15_structure_and_executed_control'})
    forming=analysis.get('forming_local') or {}
    side=int(forming.get('entry_side') or 0)
    if not (analysis.get('live_structure_fresh',True) and side and forming.get('m15_confirmation') and flow.get('trade_data_fresh')
            and flow.get('sustained_control_side')==side):
        return _with_execution_local(analysis)
    return _with_execution_local({**analysis,**forming,'ready':True,'anchor_confirmed':True,
            'h1_direction_anchor':True,'entry_blocked':False,'entry_block_reason':None,
            'signal_candle_time':int(forming['confirmation_candle_time']),
            'signal_candle_close_time':int(forming['confirmation_close_time']),
            'confirmation_source':'observed_H1_extreme_closed_M15_and_executed_control'})
