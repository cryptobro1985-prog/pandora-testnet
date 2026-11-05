from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class AgentDecision:
    consensus: float
    quorum: int
    approved: bool
    votes: dict[str, float]


def evaluate_agents(candidate: Any, plane: dict[str, Any], depth: dict[str, Any], cheapest_valid_ask: float) -> AgentDecision:
    m = plane["map"]
    side = str(getattr(candidate, "side", ""))
    sign = 1.0 if side == "CALL" else -1.0

    directional_raw = (
        0.30*m["trade_notional_imbalance_60s"] +
        0.25*m["trade_notional_imbalance_180s"] +
        0.20*m["book_imbalance_l10"] +
        0.15*m["liq_imbalance_60s"] +
        0.10*m["ticker_last_prev24h_return"]
    ) * sign
    direction = clamp(0.5 + 0.5*directional_raw)

    flow_raw = (
        0.30*m["trade_count_imbalance_30s"] +
        0.30*m["trade_vwap_bias_60s"] +
        0.20*m["trade_efficiency_60s"]*sign +
        0.20*m["liq_imbalance_30s"]*sign
    )
    flow = clamp(0.5 + 0.5*flow_raw)

    convexity = clamp(
        0.35*m["opt_gamma_eff"] +
        0.20*(1.0-m["opt_theta_ratio"]) +
        0.15*(1.0-m["opt_moneyness"]) +
        0.15*(1.0-m["opt_mark_iv"]) +
        0.15*m["opt_dte_scaled"]
    )

    spread = float(depth.get("spread_fraction", 1.0))
    execution = clamp(
        0.35*float(depth.get("liquidity_score",0.0)) +
        0.25*float(depth.get("depth_balance",0.0)) +
        0.25*float(depth.get("exitability",0.0)) +
        0.15*clamp(1.0-spread/0.12)
    )

    ask = max(float(getattr(candidate, "ask", 0.0)), 1e-12)
    cheapness = clamp(cheapest_valid_ask / ask) if cheapest_valid_ask > 0 else 0.0
    value = clamp(
        0.45*cheapness +
        0.20*(1.0-m["opt_spread_fraction"]) +
        0.15*m["opt_log_oi"] +
        0.10*m["opt_log_volume24h"] +
        0.10*(1.0-m["opt_moneyness"])
    )

    votes = {
        "direction": direction,
        "flow": flow,
        "gamma_vol": convexity,
        "execution_liquidity": execution,
        "value_price": value,
    }
    consensus = (
        0.27*direction + 0.22*flow + 0.19*convexity +
        0.20*execution + 0.12*value
    )
    quorum = sum(1 for x in votes.values() if x >= 0.60)
    approved = quorum >= 4 and consensus >= 0.64 and execution >= 0.55 and direction >= 0.58
    return AgentDecision(consensus=consensus, quorum=quorum, approved=approved, votes=votes)
