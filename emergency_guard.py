"""Fast, causal portfolio profit protection. No orders or I/O."""
from momentum_scanner import horizon_return
from accounting import paper_pnl

COOLDOWN_SECONDS = 60.0


def reversal(prices, history, epoch):
    for seconds, threshold in ((10, .0012), (30, .0020)):
        moves = {symbol: horizon_return(history.get(symbol, []), epoch, seconds, prices[symbol])
                 for symbol in ("BTC", "ETH", "SOL") if prices.get(symbol)}
        moves = {s: v for s, v in moves.items() if v is not None}
        if len(moves) < 2:
            continue
        for side in (-1, 1):
            aligned = sum(side * v >= threshold for v in moves.values())
            mean = sum(moves.values()) / len(moves)
            if aligned >= 2 and side * mean >= threshold:
                return {"triggered": True, "side": side, "horizon_seconds": seconds,
                        "threshold": threshold, "major_returns": moves, "mean_return": mean}
    return {"triggered": False}


def profit_targets(books, prices, shock, fee):
    """Close the profitable book only if the shock opposes a profitable holding."""
    profitable = []
    for strategy, book in books:
        for symbol, position in book.items():
            mark = prices.get(symbol)
            if not mark:
                continue
            net = paper_pnl(position["notional"], position["entry"], mark, position["side"], fee)
            if net > 0:
                profitable.append({"strategy": strategy, "symbol": symbol,
                                   "opened": position["opened"], "side": position["side"],
                                   "observed_net_pnl": net})
    if not shock.get("triggered") or not any(p["side"] == -shock["side"] for p in profitable):
        return []
    return profitable


def equity_drawdown_state(state, equity, epoch, has_positions, max_drawdown=.05, cooldown=900.):
    """Durable portfolio circuit breaker, independent of a market reversal.

    Peak starts at the first observed net equity, never an invented historical high.
    A triggered close remains latched until all positions are gone. Resume after
    cooldown from a new observed baseline rather than retriggering the old peak.
    """
    import math
    out=dict(state or {})
    if not math.isfinite(equity) or equity < 0 or not math.isfinite(epoch):
        raise ValueError('invalid portfolio equity')
    status=out.get('status','ARMED')
    if status=='CLOSING':
        if not has_positions:out['status']='PAUSED'
        return out
    if status=='PAUSED':
        if epoch < float(out.get('blocked_until',0)) or has_positions:return out
        return dict(status='ARMED',peak=equity,last_equity=equity,drawdown=0.,blocked_until=0.,max_drawdown=max_drawdown)
    peak=max(float(out.get('peak',equity)),equity)
    drawdown=(peak-equity)/peak if peak>0 else 0.
    out.update(status='ARMED',peak=peak,last_equity=equity,drawdown=drawdown,max_drawdown=max_drawdown)
    if drawdown >= max_drawdown:
        out.update(status='CLOSING' if has_positions else 'PAUSED',triggered_at=epoch,blocked_until=epoch+cooldown)
    return out
