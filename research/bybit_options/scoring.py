from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Iterable


def f(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def logistic01(x: float) -> float:
    x = clamp(x, -30.0, 30.0)
    return 1.0 / (1.0 + math.exp(-x))


def _symbol_tokens(symbol: str) -> list[str]:
    return [x for x in symbol.upper().split("-") if x]


def parse_strike(symbol: str) -> float:
    # Bybit crypto option symbols can include a settlement suffix:
    # BTC-6NOV26-80000-P-USDT / ETH-6NOV26-2400-C-USDT.
    # Find C/P and read the token immediately before it instead of relying on [-2].
    parts = _symbol_tokens(symbol)
    for i, token in enumerate(parts):
        if token in {"C", "P", "CALL", "PUT"} and i > 0:
            return f(parts[i - 1])
    return 0.0


def option_side(row: dict[str, Any], instrument: dict[str, Any] | None = None) -> str:
    t = (instrument or {}).get("optionsType") or row.get("optionsType")
    if t:
        name = str(t).upper()
        return "CALL" if name in {"CALL", "C"} else "PUT" if name in {"PUT", "P"} else "UNKNOWN"
    parts = _symbol_tokens(str(row.get("symbol", "")))
    if "C" in parts or "CALL" in parts:
        return "CALL"
    if "P" in parts or "PUT" in parts:
        return "PUT"
    return "UNKNOWN"


def hours_to_expiry(instrument: dict[str, Any], now_ms: int) -> float:
    delivery = f(instrument.get("deliveryTime"))
    if not delivery:
        return 1e9
    return max(0.0, (delivery - now_ms) / 3_600_000.0)


def _notional_trade_imbalance(trades: Iterable[dict[str, Any]]) -> tuple[float, float]:
    buy = sell = 0.0
    for t in trades:
        n = abs(f(t.get("price") or t.get("p")) * f(t.get("size") or t.get("v")))
        side = str(t.get("side") or t.get("S") or "").lower()
        if side == "buy":
            buy += n
        elif side == "sell":
            sell += n
    total = buy + sell
    return ((buy - sell) / total if total > 0 else 0.0, total)


def _book_imbalance(book: dict[str, Any], levels: int = 10) -> float:
    data = book.get("result", book)
    bids = data.get("b") or data.get("bids") or []
    asks = data.get("a") or data.get("asks") or []
    bid_qty = sum(max(0.0, f(x[1] if isinstance(x, list) and len(x) > 1 else 0)) for x in bids[:levels])
    ask_qty = sum(max(0.0, f(x[1] if isinstance(x, list) and len(x) > 1 else 0)) for x in asks[:levels])
    total = bid_qty + ask_qty
    return (bid_qty - ask_qty) / total if total > 0 else 0.0


def _liquidation_pressure(liquidations: Iterable[dict[str, Any]]) -> tuple[float, float]:
    # Bybit docs: S=Buy means a long position was liquidated; treat that as bearish pressure.
    bearish = bullish = 0.0
    for x in liquidations:
        n = abs(f(x.get("p")) * f(x.get("v")))
        side = str(x.get("S", "")).lower()
        if side == "buy":
            bearish += n
        elif side == "sell":
            bullish += n
    total = bearish + bullish
    return ((bullish - bearish) / total if total > 0 else 0.0, total)


def underlying_features(context: dict[str, Any]) -> dict[str, float]:
    # Prefer the causal WS cache when available; REST recent trades are the fallback.
    recent = context.get("ws_recent_trades") or context.get("recent_trades", [])
    trade_imb, trade_notional = _notional_trade_imbalance(recent)
    book_imb = _book_imbalance(context.get("orderbook", {}))
    liq_imb, liq_notional = _liquidation_pressure(context.get("liquidations", []))
    ticker = context.get("ticker", {})
    mom24 = clamp(f(ticker.get("price24hPcnt")) * 8.0)
    funding = clamp(f(ticker.get("fundingRate")) * 200.0)
    short_mom = 0.0
    if len(recent) >= 2:
        ordered = sorted(
            recent,
            key=lambda x: f(x.get("T") or x.get("time") or x.get("execTime")),
        )
        p_old = f(ordered[0].get("price") or ordered[0].get("p"))
        p_new = f(ordered[-1].get("price") or ordered[-1].get("p"))
        if p_old > 0 and p_new > 0:
            short_mom = clamp(math.log(p_new / p_old) * 300.0)
    direction = clamp(
        0.34 * trade_imb
        + 0.24 * book_imb
        + 0.20 * liq_imb
        + 0.14 * short_mom
        + 0.06 * mom24
        - 0.02 * funding
    )
    activity = clamp(math.log1p(trade_notional) / 18.0, 0.0, 1.0)
    liq_activity = clamp(math.log1p(liq_notional) / 18.0, 0.0, 1.0)
    return {
        "direction": direction,
        "trade_imbalance": trade_imb,
        "book_imbalance": book_imb,
        "liquidation_imbalance": liq_imb,
        "short_momentum": short_mom,
        "activity": activity,
        "liquidation_activity": liq_activity,
        "funding_pressure": funding,
    }


@dataclass
class Candidate:
    symbol: str
    base_coin: str
    side: str
    expiry_ms: int
    dte_hours: float
    strike: float
    underlying: float
    bid: float
    ask: float
    mark: float
    mark_iv: float
    delta: float
    gamma: float
    vega: float
    theta: float
    open_interest: float
    volume24h: float
    score: float
    components: dict[str, float]


def build_candidates(
    tickers: list[dict[str, Any]],
    instruments: dict[str, dict[str, Any]],
    context: dict[str, Any],
    now_ms: int,
    min_hours: float,
    max_hours: float,
    max_spread_fraction: float,
) -> list[Candidate]:
    uf = underlying_features(context)
    rows: list[dict[str, Any]] = []
    ivs: list[float] = []
    for row in tickers:
        inst = instruments.get(str(row.get("symbol")), {})
        dte = hours_to_expiry(inst, now_ms)
        if not (min_hours <= dte <= max_hours):
            continue
        bid = f(row.get("bid1Price") or row.get("bidPrice"))
        ask = f(row.get("ask1Price") or row.get("askPrice"))
        mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else max(bid, ask)
        if ask <= 0 or mid <= 0:
            continue
        spread = (ask - bid) / mid if bid > 0 else 1.0
        if spread > max_spread_fraction:
            continue
        iv = f(row.get("markIv") or row.get("markPriceIv"))
        if iv > 0:
            ivs.append(iv)
        rows.append({"row": row, "inst": inst, "dte": dte, "spread": spread})
    median_iv = statistics.median(ivs) if ivs else 0.0

    out: list[Candidate] = []
    for item in rows:
        row, inst = item["row"], item["inst"]
        symbol = str(row.get("symbol", ""))
        side = option_side(row, inst)
        base_coin = str(inst.get("baseCoin") or symbol.split("-")[0] or "")
        underlying = f(row.get("underlyingPrice") or row.get("indexPrice"))
        strike = parse_strike(symbol)
        bid = f(row.get("bid1Price") or row.get("bidPrice"))
        ask = f(row.get("ask1Price") or row.get("askPrice"))
        mark = f(row.get("markPrice"))
        mid = (bid + ask) / 2.0 if bid > 0 else ask
        spread_fraction = (ask - bid) / mid if mid > 0 and bid > 0 else 1.0
        delta, gamma, vega, theta = (f(row.get(k)) for k in ("delta", "gamma", "vega", "theta"))
        oi = f(row.get("openInterest"))
        volume = f(row.get("volume24h"))
        iv = f(row.get("markIv") or row.get("markPriceIv"))
        dte = float(item["dte"])

        directional = uf["direction"] if side == "CALL" else -uf["direction"] if side == "PUT" else 0.0
        dir_component = logistic01(3.0 * directional)
        liquidity = clamp(1.0 - spread_fraction / max(max_spread_fraction, 1e-6), 0.0, 1.0)
        activity = clamp((math.log1p(oi) + math.log1p(volume)) / 16.0, 0.0, 1.0)
        moneyness = abs(strike - underlying) / underlying if underlying > 0 and strike > 0 else 1.0
        atm = math.exp(-12.0 * moneyness)
        gamma_eff = abs(gamma) * max(underlying, 1.0) / max(ask, 1e-9)
        gamma_score = clamp(math.log1p(gamma_eff) / 8.0, 0.0, 1.0)
        theta_ratio = abs(theta) / max(ask, 1e-9)
        theta_penalty = clamp(math.log1p(theta_ratio) / 5.0, 0.0, 1.0)
        cheap_iv = 0.5
        if iv > 0 and median_iv > 0:
            cheap_iv = clamp(0.5 + (median_iv - iv) / max(median_iv, 1e-9), 0.0, 1.0)
        expiry_score = clamp(1.0 - abs(dte - 18.0) / 36.0, 0.0, 1.0)
        burst = clamp(
            0.22 * uf["activity"]
            + 0.22 * uf["liquidation_activity"]
            + 0.28 * abs(uf["direction"])
            + 0.28 * abs(uf["short_momentum"]),
            0.0, 1.0,
        )
        score = clamp(
            0.31 * dir_component
            + 0.14 * liquidity
            + 0.13 * gamma_score
            + 0.08 * cheap_iv
            + 0.08 * expiry_score
            + 0.08 * activity
            + 0.08 * atm
            + 0.10 * burst
            - 0.10 * theta_penalty,
            0.0, 1.0,
        )
        components = {
            "directional": dir_component, "liquidity": liquidity, "gamma": gamma_score,
            "cheap_iv": cheap_iv, "expiry": expiry_score, "activity": activity, "atm": atm,
            "burst": burst, "theta_penalty": theta_penalty, **uf,
        }
        out.append(Candidate(
            symbol=symbol, base_coin=base_coin, side=side,
            expiry_ms=int(f(inst.get("deliveryTime"))), dte_hours=dte,
            strike=strike, underlying=underlying, bid=bid, ask=ask, mark=mark,
            mark_iv=iv, delta=delta, gamma=gamma, vega=vega, theta=theta,
            open_interest=oi, volume24h=volume, score=score, components=components,
        ))
    return sorted(out, key=lambda x: x.score, reverse=True)


def depth_metrics(orderbook: dict[str, Any], reference_price: float, band: float = 0.01) -> dict[str, float]:
    data = orderbook.get("result", orderbook)
    bids = data.get("b") or []
    asks = data.get("a") or []
    bid_qty = ask_qty = 0.0
    for p, q, *_ in bids:
        if reference_price > 0 and f(p) >= reference_price * (1.0 - band):
            bid_qty += f(q)
    for p, q, *_ in asks:
        if reference_price > 0 and f(p) <= reference_price * (1.0 + band):
            ask_qty += f(q)
    total = bid_qty + ask_qty
    return {
        "bid_qty_1pct": bid_qty,
        "ask_qty_1pct": ask_qty,
        "depth_imbalance_1pct": (bid_qty - ask_qty) / total if total else 0.0,
    }


def candidate_to_signal(c: Candidate, depth: dict[str, float] | None, now_ms: int) -> dict[str, Any]:
    return {
        "ts_ms": now_ms,
        "strategy": "GAMMA_BURST_DIRECTIONAL",
        "action": "BUY_OPTION",
        "symbol": c.symbol,
        "base_coin": c.base_coin,
        "option_type": c.side,
        "expiry_ms": c.expiry_ms,
        "dte_hours": round(c.dte_hours, 4),
        "strike": c.strike,
        "underlying": c.underlying,
        "entry_reference_ask": c.ask,
        "entry_reference_bid": c.bid,
        "entry_reference_mark": c.mark,
        "max_loss_pct_of_premium": -100.0,
        "paper_only": True,
        "score": round(c.score, 6),
        "greeks": {"delta": c.delta, "gamma": c.gamma, "vega": c.vega, "theta": c.theta, "mark_iv": c.mark_iv},
        "liquidity": {"open_interest": c.open_interest, "volume24h": c.volume24h, **(depth or {})},
        "components": {k: round(v, 6) for k, v in c.components.items()},
        "exit_policy": {
            "hard_max_loss": "premium_paid",
            "no_naked_short": True,
            "research_rule": "Track bid/mark MFE/MAE and exit/reversal conditions; do not place a real order."
        }
    }
