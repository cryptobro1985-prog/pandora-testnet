"""Executed notional, velocity, dominance and price response; no indicators."""
import math

WINDOWS = (5, 15, 30, 60, 180, 300)


def summarize(trades, epoch, coverage):
    """Input rows are validated (exchange_epoch, price, USD notional, B/A)."""
    rows = [r for r in trades if 0 <= epoch-r[0] <= WINDOWS[-1]]
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
            price_return=move, buy_price_response=buy_response,
            sell_price_response=sell_response,
            buy_absorbed=buy>sell and move<=0,
            sell_absorbed=sell>buy and move>=0,
            observed_seconds=min(seconds, max(0.,coverage)),
            complete=coverage>=seconds,
        )
    minute = windows['60']
    control = 1 if minute['imbalance']>0 else -1 if minute['imbalance']<0 else 0
    # How long the current volume majority has persisted in the observed tape.
    balance=0.; dominance_start=rows[-1][0] if rows else epoch
    for row in reversed(rows):
        balance += row[2]*(1 if row[3]=='B' else -1)
        if balance*control<=0: break
        dominance_start=row[0]
    active = [windows[str(n)] for n in (5,15,60) if windows[str(n)]['trade_count']>=2]
    sustained = bool(control and len(active)>=2 and all(
        w['imbalance']*control>0 and w['price_return']*control>0 for w in active))
    return dict(windows=windows, volume_velocity=minute['volume_velocity'],
                trade_velocity=minute['trade_velocity'], imbalance_change=minute['imbalance_change'],
                volume_acceleration=windows['15']['volume_acceleration'],
                dominance_side=control, dominance_duration=max(0.,epoch-dominance_start),
                sustained_control_side=control if sustained else 0,
                buy_price_response=minute['buy_price_response'],
                sell_price_response=minute['sell_price_response'],
                buy_absorbed=minute['buy_absorbed'], sell_absorbed=minute['sell_absorbed'])
