"""Read-only executable option quote calculations for paper alerts."""
from __future__ import annotations
from typing import Any


def walk_book(book: dict[str, Any], action: str, quantity: float) -> dict[str, Any]:
    """Estimate full-size execution from Bybit option orderbook levels.

    Prices are premium per unit as supplied by Bybit. Notional conversion and
    fees must be supplied by the caller before displaying USDT total.
    """
    if action not in {"BUY", "SELL"}:
        raise ValueError("action must be BUY or SELL")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    data = book.get("result", book)
    levels = data.get("a" if action == "BUY" else "b", [])
    parsed = []
    for row in levels:
        try:
            price, size = float(row[0]), float(row[1])
        except (IndexError, ValueError, TypeError):
            continue
        if price > 0 and size > 0:
            parsed.append((price, size))
    parsed.sort(key=lambda x: x[0], reverse=action == "SELL")
    if not parsed:
        return {"executable": False, "reason": "empty_book"}
    best = parsed[0][0]
    filled = cost = 0.0
    for price, size in parsed:
        take = min(size, quantity - filled)
        filled += take
        cost += price * take
        if filled >= quantity - 1e-10:
            break
    if filled < quantity - 1e-10:
        return {"executable": False, "reason": "insufficient_depth", "filled": filled, "requested": quantity}
    vwap = cost / filled
    return {"executable": True, "action": action, "quantity": filled, "best_price": best,
            "vwap": vwap, "premium_units": cost,
            "slippage_fraction": (vwap / best - 1) if action == "BUY" else (1 - vwap / best)}


def round_trip_quote(book: dict[str, Any], quantity: float, multiplier: float,
                     buy_fee_rate: float, sell_fee_rate: float) -> dict[str, Any]:
    if multiplier <= 0 or min(buy_fee_rate, sell_fee_rate) < 0:
        raise ValueError("invalid multiplier or fee")
    buy, sell = walk_book(book, "BUY", quantity), walk_book(book, "SELL", quantity)
    if not buy["executable"] or not sell["executable"]:
        return {"executable": False, "buy": buy, "sell": sell}
    entry = buy["premium_units"] * multiplier
    exit_value = sell["premium_units"] * multiplier
    entry_fee = entry * buy_fee_rate
    exit_fee = exit_value * sell_fee_rate
    return {"executable": True, "buy": buy, "sell": sell,
            "entry_total": entry + entry_fee, "exit_total": exit_value - exit_fee,
            "immediate_round_trip_pnl": exit_value - exit_fee - entry - entry_fee,
            "fees": entry_fee + exit_fee}


def paper_action(previous: str, direction_score: float, thesis_side: str,
                 quote_fresh: bool, exit_depth_ok: bool, invalidated: bool) -> str:
    """Conservative state transition, not an exchange order."""
    if previous not in {"FLAT", "HOLD"} or thesis_side not in {"CALL", "PUT"}:
        raise ValueError("invalid state")
    if previous == "HOLD":
        if not quote_fresh or not exit_depth_ok:
            return "DATA_RISK_REVIEW"
        if invalidated or (direction_score < 0 if thesis_side == "CALL" else direction_score > 0):
            return "EMERGENCY_SELL"
        return "HOLD"
    if not quote_fresh or not exit_depth_ok or invalidated:
        return "WAIT"
    return "BUY_CALL" if thesis_side == "CALL" and direction_score > 0 else (
        "BUY_PUT" if thesis_side == "PUT" and direction_score < 0 else "WAIT")
