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
