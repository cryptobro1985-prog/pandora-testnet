"""Sequential first-accepted-local evaluation, separate from live features."""
from __future__ import annotations

import math

from .labels import completed_hours


def quantile(values, p):
    if not values:
        return None
    values = sorted(values)
    x = (len(values)-1)*p
    lo, hi = math.floor(x), math.ceil(x)
    return values[lo] + (values[hi]-values[lo])*(x-lo)


def wilson(successes, n, z=1.959963984540054):
    if not n:
        return [None, None]
    p = successes/n
    center = (p+z*z/(2*n))/(1+z*z/n)
    radius = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return [max(0.,center-radius), min(1.,center+radius)]


def evaluate(engine, rows, labels, start_ms, end_ms, exclusions=()):
    """Match immutable accepted extremes one-to-one, not best candidates.

    The unit of matching is the observed extreme interval and price, NOT a
    nearby later pivot. Events without sufficient right-hand label support are
    censored. Delay is an interval for OHLC inputs. MAE/MFE end at the next
    reference opposite extreme, using only bars fully inside that interval.
    """
    eligible_labels = [x for x in labels if start_ms <= x['extreme_interval_start_ms'] < end_ms and x.get('reference_finalized',True)]
    used, ledger, censored = set(), [], []
    # A right boundary is supplied by caller after the final 2-hour label margin.
    accepted = [x for x in engine.confirmed if start_ms <= x['confirmation_ts_ms'] < end_ms]
    for event in accepted:
        if any(x['hour_ms'] <= event['extreme_interval_start_ms'] < x['hour_ms']+3_600_000 for x in exclusions):
            censored.append({**event,'evaluation_status':'reference_unknown_censored'})
            continue
        if event['extreme_interval_start_ms'] < start_ms:
            censored.append({**event, 'evaluation_status':'left_boundary_censored'})
            continue
        match = None
        for label in eligible_labels:
            if label['label_id'] in used or label['side'] != event['side']:
                continue
            overlap = (event['extreme_interval_start_ms'] < label['extreme_interval_end_ms'] and
                label['extreme_interval_start_ms'] < event['extreme_interval_end_ms'])
            if event['extreme_interval_start_ms']==event['extreme_interval_end_ms']:
                overlap = label['extreme_interval_start_ms'] <= event['extreme_interval_start_ms'] <= label['extreme_interval_end_ms']
            if overlap and math.isclose(event['extreme_price'], label['extreme_price'], rel_tol=1e-10, abs_tol=1e-10):
                match = label
                break
        if match:
            used.add(match['label_id'])
        label = match or event
        confirmation = event['confirmation_ts_ms']
        distance = abs(event['confirmation_price']/event['extreme_price']-1)*100
        next_labels = [x for x in labels if x['side'] != event['side'] and
                       x['extreme_interval_start_ms'] > event['extreme_interval_start_ms']]
        horizon = next_labels[0]['extreme_interval_start_ms'] if next_labels else None
        late = horizon is not None and horizon <= confirmation
        # Do not give final events shorter horizons and present them as comparable.
        horizon = horizon if horizon is not None and confirmation < horizon < end_ms else None
        observed = [r for r in rows if horizon is not None and r['start_ms'] >= confirmation and r['ts_ms'] <= horizon]
        entry = event['confirmation_price']
        if observed:
            high, low = max(r['high'] for r in observed), min(r['low'] for r in observed)
            mae = max(0., high/entry-1) if event['side']=='HIGH' else max(0.,1-low/entry)
            mfe = max(0., 1-low/entry) if event['side']=='HIGH' else max(0.,high/entry-1)
        else:
            mae = mfe = None
        ledger.append({**event, 'evaluation_status':'true' if match else 'false',
            'matched_label_id':match['label_id'] if match else None,
            'delay_min_lower':max(0, confirmation-label['extreme_interval_end_ms'])/60000,
            'delay_min_upper':max(0, confirmation-label['extreme_interval_start_ms'])/60000,
            'entry_distance_pct':distance, 'mae_pct':None if mae is None else mae*100,
            'mfe_pct':None if mfe is None else mfe*100,
            'excursion_status':'late_after_opposite' if late else 'observed' if observed else 'censored',
            'late_after_opposite':late,
            'new_extreme_after_candidate': any(
                (r['high']>event['extreme_price'] if event['side']=='HIGH' else r['low']<event['extreme_price'])
                for r in rows if r['start_ms']>=event['candidate_ts_ms'] and r['ts_ms']<=confirmation),
            'post_confirmation_extreme_extension': (any(
                (r['high']>event['extreme_price'] if event['side']=='HIGH' else r['low']<event['extreme_price'])
                for r in rows if r['start_ms']>=confirmation and r['ts_ms']<=horizon) if horizon is not None else None),
            'forensic':{'features_at_acceptance':event.get('features'),
                'reason':'matched strict offline reference' if match else 'no matching offline structural extreme',
                'causal_explanation_of_future':'not identifiable from observations alone'}})
    # A false HIGH -> false LOW can create another machine episode within the
    # SAME true swing. Never let a later successful HIGH erase that first error.
    # Reference intervals are offline evaluation groups only, never live anchors.
    first, reference_censored = [],set()
    for label in eligible_labels:
        previous = [x for x in labels if x['side']!=label['side'] and
                    x['extreme_interval_start_ms']<label['extreme_interval_start_ms']]
        following = [x for x in labels if x['side']!=label['side'] and
                     x['extreme_interval_start_ms']>label['extreme_interval_start_ms']]
        begin = max(start_ms,previous[-1]['extreme_interval_end_ms'] if previous else start_ms)
        finish = min(end_ms,following[0]['extreme_interval_start_ms'] if following else end_ms)
        all_options = sorted((x for x in ledger+censored if x['side']==label['side'] and
                          begin<=x['confirmation_ts_ms']<finish),key=lambda x:x['confirmation_ts_ms'])
        if all_options and all_options[0]['evaluation_status'].endswith('_censored'):
            reference_censored.add(label['label_id'])
            continue
        options = [x for x in all_options if not x['evaluation_status'].endswith('_censored')]
        if options:
            row = {**options[0],'reference_episode_label_id':label['label_id'],
                   'earlier_or_later_same_side_acceptances':len(options)-1}
            row['evaluation_status'] = 'true' if row['matched_label_id']==label['label_id'] else 'false'
            first.append(row)
    first_used = {x['matched_label_id'] for x in first if x['evaluation_status']=='true'}
    # Regime boundaries are derived only from completed pre-evaluation hours.
    pre = completed_hours([r for r in rows if r['ts_ms']<=start_ms])
    ranges, normalized = [],[]
    for i,h in enumerate(pre):
        previous_close = pre[i-1]['close'] if i else h['open']
        ranges.append(max(h['high']-h['low'],abs(h['high']-previous_close),abs(h['low']-previous_close)))
        if len(ranges)>=14:
            normalized.append(sum(ranges[-14:])/14/h['close'])
    cutoffs = [quantile(normalized,1/3),quantile(normalized,2/3)]
    for row in first:
        atr = (row.get('features') or {}).get('atr_h1')
        fraction = atr/row['confirmation_price'] if atr is not None else None
        row['volatility_regime'] = ('unknown' if fraction is None or cutoffs[0] is None else
            'low' if fraction<=cutoffs[0] else 'high' if fraction>cutoffs[1] else 'medium')
    missed = [{**x,'evaluation_status':'missed', 'reason':'first accepted signal in reference swing absent or false'}
              for x in eligible_labels if x['label_id'] not in first_used|reference_censored]
    true = sum(x['evaluation_status']=='true' for x in first)
    delays = [x['delay_min_upper'] for x in first if x['evaluation_status']=='true']
    distances = [x['entry_distance_pct'] for x in first if x['evaluation_status']=='true']
    candidates = [x for x in engine.candidates if start_ms <= x['candidate_ts_ms'] < end_ms]
    metrics = dict(accepted=len(first), true=true, false=len(first)-true,
        engine_episode_accepted=len(ledger),
        engine_episode_precision=sum(x['evaluation_status']=='true' for x in ledger)/len(ledger) if ledger else None,
        reference_locals=len(eligible_labels), reference_censored=len(reference_censored),
        reference_locals_evaluable=len(eligible_labels)-len(reference_censored),
        missed=len(missed), censored_accepted=len(censored),
        first_accepted_precision=true/len(first) if first else None,
        precision_wilson_95=wilson(true,len(first)),
        false_local_rate=(len(first)-true)/len(first) if first else None,
        recall=true/(len(eligible_labels)-len(reference_censored)) if len(eligible_labels)>len(reference_censored) else None,
        missed_local_rate=len(missed)/(len(eligible_labels)-len(reference_censored)) if len(eligible_labels)>len(reference_censored) else None,
        median_delay_min_upper=quantile(delays,.5), p90_delay_min_upper=quantile(delays,.9),
        median_entry_distance_pct=quantile(distances,.5), p90_entry_distance_pct=quantile(distances,.9),
        candidate_invalidation_rate=sum(x.get('status')=='INVALIDATED' for x in candidates)/len(candidates) if candidates else None,
        confidence_is_calibrated_probability=False)
    metrics['by_side'] = {side:dict(accepted=sum(x['side']==side for x in first),
        true=sum(x['side']==side and x['evaluation_status']=='true' for x in first)) for side in ('HIGH','LOW')}
    for part in metrics['by_side'].values():
        part['precision'] = part['true']/part['accepted'] if part['accepted'] else None
    metrics['volatility_cutoffs_from_pre_evaluation_history'] = cutoffs
    metrics['by_volatility_regime'] = {}
    for regime in ('low','medium','high','unknown'):
        group = [x for x in first if x['volatility_regime']==regime]
        correct = sum(x['evaluation_status']=='true' for x in group)
        metrics['by_volatility_regime'][regime] = dict(accepted=len(group),true=correct,
            precision=correct/len(group) if group else None)
    return dict(metrics=metrics, accepted=ledger, first_accepted=first,
        false_locals=[x for x in ledger if x['evaluation_status']=='false'],
        missed_locals=missed, censored=censored)
