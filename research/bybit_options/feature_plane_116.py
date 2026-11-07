from __future__ import annotations

import math
from typing import Any

WINDOWS_MS = (15_000, 30_000, 60_000, 180_000, 300_000)


def f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _ts(row: dict[str, Any]) -> int:
    return int(f(row.get("T") or row.get("time") or row.get("execTime")))


def _trade_price(row: dict[str, Any]) -> float:
    return f(row.get("price") or row.get("p"))


def _trade_qty(row: dict[str, Any]) -> float:
    return abs(f(row.get("size") or row.get("v")))


def _trade_side(row: dict[str, Any]) -> str:
    return str(row.get("side") or row.get("S") or "").lower()


def _window(rows: list[dict[str, Any]], now_ms: int, width_ms: int) -> list[dict[str, Any]]:
    cutoff = now_ms - width_ms
    return [x for x in rows if cutoff <= _ts(x) <= now_ms]


def _trade_features(rows: list[dict[str, Any]], width_ms: int) -> tuple[list[str], list[float]]:
    tag = str(width_ms // 1000) + "s"
    rows = sorted(rows, key=_ts)
    notionals = [max(0.0, _trade_price(x) * _trade_qty(x)) for x in rows]
    buy_n = sum(n for n, x in zip(notionals, rows) if _trade_side(x) == "buy")
    sell_n = sum(n for n, x in zip(notionals, rows) if _trade_side(x) == "sell")
    total_n = buy_n + sell_n
    buys = sum(1 for x in rows if _trade_side(x) == "buy")
    sells = sum(1 for x in rows if _trade_side(x) == "sell")
    count = buys + sells
    prices = [_trade_price(x) for x in rows if _trade_price(x) > 0]
    ret = 0.0
    rv = 0.0
    rng = 0.0
    vwap_bias = 0.0
    efficiency = 0.0
    if len(prices) >= 2:
        ret = math.log(prices[-1] / prices[0])
        logs = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices)) if prices[i-1] > 0]
        rv = math.sqrt(sum(x*x for x in logs))
        rng = (max(prices) - min(prices)) / prices[0]
        path = sum(abs(x) for x in logs)
        efficiency = abs(ret) / path if path > 0 else 0.0
    if total_n > 0 and prices:
        vwap = sum(_trade_price(x) * n for x, n in zip(rows, notionals)) / total_n
        if vwap > 0:
            vwap_bias = (prices[-1] - vwap) / vwap
    max_share = max(notionals, default=0.0) / total_n if total_n > 0 else 0.0
    mean_n = total_n / max(count, 1)
    names = [
        f"trade_notional_imbalance_{tag}", f"trade_count_imbalance_{tag}",
        f"trade_buy_share_{tag}", f"trade_log_return_{tag}",
        f"trade_realized_vol_{tag}", f"trade_range_{tag}",
        f"trade_vwap_bias_{tag}", f"trade_rate_{tag}",
        f"trade_log_notional_{tag}", f"trade_max_share_{tag}",
        f"trade_log_mean_size_{tag}", f"trade_efficiency_{tag}",
    ]
    vals = [
        (buy_n - sell_n) / total_n if total_n else 0.0,
        (buys - sells) / count if count else 0.0,
        buy_n / total_n if total_n else 0.5,
        clamp(ret * 400.0),
        clamp(rv * 250.0, 0.0, 1.0),
        clamp(rng * 200.0, 0.0, 1.0),
        clamp(vwap_bias * 400.0),
        clamp(count / max(width_ms / 1000.0 * 8.0, 1.0), 0.0, 1.0),
        clamp(math.log1p(total_n) / 22.0, 0.0, 1.0),
        clamp(max_share, 0.0, 1.0),
        clamp(math.log1p(mean_n) / 18.0, 0.0, 1.0),
        clamp(efficiency, 0.0, 1.0),
    ]
    return names, vals


def _liq_features(rows: list[dict[str, Any]], width_ms: int) -> tuple[list[str], list[float]]:
    tag = str(width_ms // 1000) + "s"
    notionals = [abs(f(x.get("p")) * f(x.get("v"))) for x in rows]
    bearish = sum(n for n, x in zip(notionals, rows) if str(x.get("S", "")).lower() == "buy")
    bullish = sum(n for n, x in zip(notionals, rows) if str(x.get("S", "")).lower() == "sell")
    total = bearish + bullish
    count = len(rows)
    names = [
        f"liq_imbalance_{tag}", f"liq_activity_{tag}",
        f"liq_rate_{tag}", f"liq_max_share_{tag}",
    ]
    vals = [
        (bullish - bearish) / total if total else 0.0,
        clamp(math.log1p(total) / 22.0, 0.0, 1.0),
        clamp(count / max(width_ms / 1000.0, 1.0), 0.0, 1.0),
        clamp(max(notionals, default=0.0) / total if total else 0.0, 0.0, 1.0),
    ]
    return names, vals


def _book_features(book: dict[str, Any]) -> tuple[list[str], list[float]]:
    data = book.get("result", book)
    bids = data.get("b") or data.get("bids") or []
    asks = data.get("a") or data.get("asks") or []
    def pq(row):
        return (f(row[0]), max(0.0, f(row[1]))) if isinstance(row, list) and len(row) >= 2 else (0.0, 0.0)
    b = [pq(x) for x in bids]
    a = [pq(x) for x in asks]
    def imb(levels: int) -> float:
        bq = sum(q for _, q in b[:levels]); aq = sum(q for _, q in a[:levels]); t = bq + aq
        return (bq - aq) / t if t else 0.0
    best_bid = b[0][0] if b else 0.0
    best_ask = a[0][0] if a else 0.0
    mid = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else max(best_bid, best_ask)
    spread = (best_ask - best_bid) / mid if mid > 0 and best_bid > 0 and best_ask > 0 else 1.0
    b10 = sum(q for _,q in b[:10]); a10 = sum(q for _,q in a[:10])
    bands = []
    for band in (0.001, 0.0025, 0.005, 0.01):
        bq = sum(q for p,q in b if mid > 0 and p >= mid*(1-band))
        aq = sum(q for p,q in a if mid > 0 and p <= mid*(1+band))
        t=bq+aq
        bands.append((bq-aq)/t if t else 0.0)
    micro = 0.0
    if best_bid > 0 and best_ask > 0 and b and a and (b[0][1] + a[0][1]) > 0 and mid > 0:
        microprice=(best_ask*b[0][1]+best_bid*a[0][1])/(b[0][1]+a[0][1])
        micro=(microprice-mid)/mid
    names=[
        "book_imbalance_l1","book_imbalance_l5","book_imbalance_l10",
        "book_log_bid_qty_l10","book_log_ask_qty_l10","book_spread_fraction",
        "book_band_imbalance_10bp","book_band_imbalance_25bp","book_band_imbalance_50bp","book_band_imbalance_100bp",
        "book_microprice_bias","book_bid_l1_concentration","book_ask_l1_concentration","book_depth_balance_l10",
    ]
    vals=[
        imb(1),imb(5),imb(10),
        clamp(math.log1p(b10)/10.0,0,1),clamp(math.log1p(a10)/10.0,0,1),clamp(spread*100.0,0,1),
        *bands,clamp(micro*1000.0),
        clamp((b[0][1]/b10) if b10 else 0,0,1),clamp((a[0][1]/a10) if a10 else 0,0,1),
        min(b10,a10)/max(b10,a10,1e-12),
    ]
    return names,vals


def _ticker_features(ticker: dict[str, Any]) -> tuple[list[str], list[float]]:
    last=f(ticker.get("lastPrice")); mark=f(ticker.get("markPrice")); index=f(ticker.get("indexPrice"))
    bid=f(ticker.get("bid1Price")); ask=f(ticker.get("ask1Price"))
    spread=(ask-bid)/((ask+bid)/2) if ask>0 and bid>0 else 1.0
    prev=f(ticker.get("prevPrice24h"))
    names=[
        "ticker_price24h_pct","ticker_funding","ticker_log_oi","ticker_log_oi_value",
        "ticker_log_turnover24h","ticker_log_volume24h","ticker_mark_index_basis",
        "ticker_best_spread","ticker_last_prev24h_return","ticker_mark_last_basis",
    ]
    vals=[
        clamp(f(ticker.get("price24hPcnt"))*8.0),
        clamp(f(ticker.get("fundingRate"))*200.0),
        clamp(math.log1p(max(f(ticker.get("openInterest")),0))/18.0,0,1),
        clamp(math.log1p(max(f(ticker.get("openInterestValue")),0))/24.0,0,1),
        clamp(math.log1p(max(f(ticker.get("turnover24h")),0))/28.0,0,1),
        clamp(math.log1p(max(f(ticker.get("volume24h")),0))/22.0,0,1),
        clamp(((mark-index)/index)*200.0 if index>0 else 0.0),
        clamp(spread*100.0,0,1),
        clamp(math.log(last/prev)*20.0 if last>0 and prev>0 else 0.0),
        clamp(((mark-last)/last)*200.0 if last>0 else 0.0),
    ]
    return names, vals


def build_feature_plane_116(context: dict[str, Any], candidate: Any, depth: dict[str, Any], now_ms: int) -> dict[str, Any]:
    names: list[str] = []
    values: list[float] = []
    trades = list(context.get("ws_recent_trades") or context.get("recent_trades") or [])
    liqs = list(context.get("liquidations") or [])
    for w in WINDOWS_MS:
        n,v=_trade_features(_window(trades,now_ms,w),w); names.extend(n); values.extend(v)
    for w in WINDOWS_MS:
        n,v=_liq_features(_window(liqs,now_ms,w),w); names.extend(n); values.extend(v)
    n,v=_book_features(context.get("ws_orderbook") or context.get("orderbook") or {}); names.extend(n); values.extend(v)
    ticker=context.get("ws_ticker") or context.get("ticker") or {}
    n,v=_ticker_features(ticker); names.extend(n); values.extend(v)

    underlying=max(f(getattr(candidate,"underlying",0.0)),1e-12)
    strike=f(getattr(candidate,"strike",0.0))
    ask=max(f(getattr(candidate,"ask",0.0)),1e-12)
    bid=f(getattr(candidate,"bid",0.0))
    spread=(ask-bid)/((ask+bid)/2) if bid>0 else 1.0
    moneyness=abs(strike-underlying)/underlying if strike>0 else 1.0
    opt_names=[
        "opt_delta","opt_gamma_eff","opt_vega_ratio","opt_theta_ratio","opt_mark_iv",
        "opt_log_oi","opt_log_volume24h","opt_spread_fraction","opt_moneyness",
        "opt_dte_scaled","opt_depth_balance","opt_exitability",
    ]
    opt_vals=[
        clamp(f(getattr(candidate,"delta",0.0))),
        clamp(abs(f(getattr(candidate,"gamma",0.0)))*underlying/ask/10.0,0,1),
        clamp(abs(f(getattr(candidate,"vega",0.0)))/ask,0,1),
        clamp(abs(f(getattr(candidate,"theta",0.0)))/ask,0,1),
        clamp(f(getattr(candidate,"mark_iv",0.0))/2.0,0,1),
        clamp(math.log1p(max(f(getattr(candidate,"open_interest",0.0)),0))/18.0,0,1),
        clamp(math.log1p(max(f(getattr(candidate,"volume24h",0.0)),0))/18.0,0,1),
        clamp(spread,0,1),clamp(moneyness*10.0,0,1),
        clamp(f(getattr(candidate,"dte_hours",0.0))/48.0,0,1),
        clamp(f(depth.get("depth_balance")),0,1),clamp(f(depth.get("exitability")),0,1),
    ]
    names.extend(opt_names); values.extend(opt_vals)
    if len(values) != 116:
        raise AssertionError(f"feature plane expected 116, got {len(values)}")
    return {"count":116,"names":names,"values":values,"map":dict(zip(names,values))}
