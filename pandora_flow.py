"""Executed notional, velocity, dominance and price response; no indicators."""
import math

WINDOWS = (5, 15, 30, 60, 108, 300)
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
    dominance = 1 if minute['imbalance']>0 else -1 if minute['imbalance']<0 else 0
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
    if previous_control!=dominance:dominance_start=epoch
    dominance_duration=max(0.,epoch-dominance_start) if dominance else 0.
    # A few identical bootstrap prints do not establish independent horizons.
    # 15 seconds of actual observed tape are required, not just socket uptime.
    active=[windows[str(n)] for n in (5,15)]
    # A single contrary print cannot erase multi-trade executed control.
    # Price response is evaluated over each window, not by the last tick alone.
    def window_control(window, require_net_response=False, require_complete=True):
        bias=1 if window['imbalance']>=MIN_CONTROL_IMBALANCE else -1 if window['imbalance']<=-MIN_CONTROL_IMBALANCE else 0
        if not bias or (require_complete and not window['complete']) or window['trade_count']<2:return 0
        # Ignore only floating-point roundoff around an exactly flat auction.
        price_return=float(window['price_return'] or 0.)
        move=1 if price_return>1e-10 else -1 if price_return<-1e-10 else 0
        own='buy_price_response' if bias>0 else 'sell_price_response'
        opposite='sell_price_response' if bias>0 else 'buy_price_response'
        if move==-bias and window[opposite]>0:return -bias
        if window[own]<=0:return 0
        if require_net_response and move!=bias:return 0
        return bias
    fast_bias=window_control(active[0])
    fast_control=fast_bias if fast_bias and window_control(active[1])==fast_bias else 0
    # Existing exposure may be reduced from corroborated 15/30s volume and net
    # price movement even when the 5s window is briefly neutral. New entries
    # retain the faster corroboration and minute context below.
    medium=window_control(windows['15'],True)
    slow_exit=medium if medium and window_control(windows['30'],True)==medium else 0
    exit_control=fast_control or slow_exit
    exit_basis='fast_5_15' if fast_control else 'confirmed_15_30' if slow_exit else 'unconfirmed'
    # Old minute volume must not veto a structurally confirmed risk-reducing
    # exit. New entries/reentries retain the conservative minute corroboration.
    response_key='buy_price_response' if dominance>0 else 'sell_price_response'
    sustained=bool(dominance and fast_control==dominance
                   and minute['imbalance']*dominance>=MIN_CONTROL_IMBALANCE
                   and minute[response_key]>0)
    return dict(windows=windows, volume_velocity=minute['volume_velocity'],
                trade_velocity=minute['trade_velocity'], imbalance_change=minute['imbalance_change'],
                volume_acceleration=windows['15']['volume_acceleration'],
                dominance_side=dominance, dominance_duration=dominance_duration,
                fast_control_side=fast_control,context_control_side=dominance,
                exit_control_side=exit_control,exit_control_basis=exit_basis,
                sustained_control_side=dominance if sustained else 0,
                minimum_control_imbalance=MIN_CONTROL_IMBALANCE,
                evidence_ready=windows['15']['complete'],evidence_required_seconds=15,
                buy_price_response=minute['buy_price_response'],
                sell_price_response=minute['sell_price_response'],
                buy_absorbed=minute['buy_absorbed'], sell_absorbed=minute['sell_absorbed'])
