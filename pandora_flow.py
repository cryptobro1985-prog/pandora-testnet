"""Executed notional, velocity, dominance and price response; no indicators."""
import math

WINDOWS = (5, 15, 30, 60, 180, 300)
# 0.20 imbalance means at least 60/40 executed notional. A bare majority
# is useful context, but is not sufficient evidence of trading control.
MIN_CONTROL_IMBALANCE = 0.20


def summarize(trades, epoch, coverage):
    """Input rows are validated (exchange_epoch, price, USD notional, B/A)."""
    rows = [r for r in trades if 0 <= epoch-r[0] <= 2*WINDOWS[-1]]
    coverage=max(0.,min(float(coverage),epoch-rows[0][0])) if rows else 0.
    windows = {}
    for seconds in WINDOWS:
        sample = [r for r in rows if epoch-r[0] <= seconds]
        buy = sum(r[2] for r in sample if r[3] == 'B')
        sell = sum(r[2] for r in sample if r[3] == 'A')
        total = buy+sell
        elapsed = max(.001, min(seconds, coverage))
        prior = [r for r in rows if seconds < epoch-r[0] <= 2*seconds]
        previous_volume = sum(r[2] for r in prior)
        earlier = [r for r in sample if epoch-r[0] > seconds/2]
        recent = [r for r in sample if epoch-r[0] <= seconds/2]
        def imbalance(items):
            volume = sum(r[2] for r in items)
            return sum(r[2]*(1 if r[3]=='B' else -1) for r in items)/volume if volume else 0.
        buy_response = sell_response = 0.
        for previous, current in zip(sample, sample[1:]):
            change = current[1]/previous[1]-1
            if current[3]=='B': buy_response += change
            else: sell_response -= change
        move = sample[-1][1]/sample[0][1]-1 if len(sample)>1 else 0.
        windows[str(seconds)] = dict(
            buy_volume=buy, sell_volume=sell,
            buy_quantity=sum(r[2]/r[1] for r in sample if r[3]=='B'),
            sell_quantity=sum(r[2]/r[1] for r in sample if r[3]=='A'),
            imbalance=(buy-sell)/total if total else 0., trade_count=len(sample),
            volume_velocity=total/elapsed, trade_velocity=len(sample)/elapsed,
            volume_change=total-previous_volume,
            volume_acceleration=(sum(r[2] for r in recent)-sum(r[2] for r in earlier))/(seconds/2),
            imbalance_change=imbalance(recent)-imbalance(earlier),
            price_return=move,
            price_high=max((r[1] for r in sample),default=None),
            price_low=min((r[1] for r in sample),default=None),
            price_range_fraction=(max(r[1] for r in sample)-min(r[1] for r in sample))/sample[-1][1] if sample else 0.,
            buy_price_response=buy_response,
            sell_price_response=sell_response,
            buy_absorbed=buy>sell and move<=0,
            sell_absorbed=sell>buy and move>=0,
            observed_seconds=min(seconds, max(0.,coverage)),
            complete=coverage>=seconds,
        )
    minute = windows['60']
    control = 1 if minute['imbalance']>0 else -1 if minute['imbalance']<0 else 0
    # Reconstruct the rolling 60s majority at both executions and expirations.
    # Expiring trades can change control even when no new execution arrives.
    balance=0.;dominance_start=epoch;previous_control=0
    arrivals=expirations=0
    while arrivals<len(rows) or expirations<len(rows):
        arrival=rows[arrivals][0] if arrivals<len(rows) else float('inf')
        expiry=rows[expirations][0]+60.000001 if expirations<len(rows) else float('inf')
        stamp=min(arrival,expiry)
        if stamp>epoch:break
        while expirations<len(rows) and rows[expirations][0]+60.000001<=stamp:
            old=rows[expirations];balance-=old[2]*(1 if old[3]=='B' else -1);expirations+=1
        while arrivals<len(rows) and rows[arrivals][0]<=stamp:
            row=rows[arrivals];balance+=row[2]*(1 if row[3]=='B' else -1);arrivals+=1
        observed_control=1 if balance>0 else -1 if balance<0 else 0
        if observed_control!=previous_control:dominance_start=stamp
        previous_control=observed_control
    if previous_control!=control:dominance_start=epoch
    dominance_duration=max(0.,epoch-dominance_start) if control else 0.
    # A few identical bootstrap prints do not establish independent horizons.
    # 15 seconds of actual observed tape are required, not just socket uptime.
    active=[windows[str(n)] for n in (5,15)]
    distinct=[r[1] for r in rows if epoch-r[0]<=60]
    last_price=distinct[-1] if distinct else None
    prior_price=next((price for price in reversed(distinct) if price!=last_price),None)
    last_direction=1 if prior_price is not None and last_price>prior_price else -1 if prior_price is not None and last_price<prior_price else 0
    fast_bias=1 if active[0]['imbalance']>0 else -1 if active[0]['imbalance']<0 else 0
    fast_response='buy_price_response' if fast_bias>0 else 'sell_price_response'
    fast_confirmed=bool(fast_bias and windows['15']['complete'] and all(
        w['complete'] and w['trade_count']>=2
        and w['imbalance']*fast_bias>=MIN_CONTROL_IMBALANCE
        and w[fast_response]>0 for w in active) and last_direction==fast_bias)
    fast_control=fast_bias if fast_confirmed else 0
    # Old minute volume must not veto a structurally confirmed risk-reducing
    # exit. New entries/reentries retain the conservative minute corroboration.
    response_key='buy_price_response' if control>0 else 'sell_price_response'
    sustained=bool(control and fast_control==control
                   and minute['imbalance']*control>=MIN_CONTROL_IMBALANCE
                   and minute[response_key]>0)
    return dict(windows=windows, volume_velocity=minute['volume_velocity'],
                trade_velocity=minute['trade_velocity'], imbalance_change=minute['imbalance_change'],
                volume_acceleration=windows['15']['volume_acceleration'],
                dominance_side=control, dominance_duration=dominance_duration,
                fast_control_side=fast_control,context_control_side=control,
                sustained_control_side=control if sustained else 0,
                minimum_control_imbalance=MIN_CONTROL_IMBALANCE,
                evidence_ready=windows['15']['complete'],evidence_required_seconds=15,
                buy_price_response=minute['buy_price_response'],
                sell_price_response=minute['sell_price_response'],
                buy_absorbed=minute['buy_absorbed'], sell_absorbed=minute['sell_absorbed'])
