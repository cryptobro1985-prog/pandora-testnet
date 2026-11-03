from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from statistics import median

SYMBOLS = ("ZEC", "HYPE", "NEAR", "SOL", "ENA", "1000PEPE", "DOGE", "SUI", "AAVE", "WLD")
EXIT_MODELS = ("combined", "flow_weakening", "opposite_flow", "price_reversal",
               "absorption", "mfe_recoil", "local_invalidation", "opposite_local", "structure_break")


@dataclass(frozen=True)
class Config:
    block_trades: int = 32
    baseline_blocks: int = 256
    warmup_blocks: int = 8
    confirmation_blocks: int = 2
    transfer_blocks: int = 2
    local_floor_bps: float = 5.0
    local_vol_multiplier: float = 1.5
    control_imbalance: float = 0.15
    absorption_z: float = 2.0
    fee_bps: float = 4.5
    slippage_bps: float = 2.0
    notional: float = 1000.0
    gap_seconds: float = 30.0
    post_exit_trades: int = 256
    outcome_trades: int = 128
    large_trade_z: float = 3.0
    min_evidence: int = 30
    exit_models: tuple[str, ...] = EXIT_MODELS

    def __post_init__(self):
        for name in ("block_trades", "baseline_blocks", "warmup_blocks", "confirmation_blocks", "transfer_blocks", "post_exit_trades", "outcome_trades", "min_evidence"):
            if type(getattr(self, name)) is not int:
                raise ValueError(name + " must be an integer")
        if self.block_trades < 2 or self.warmup_blocks < 2 or self.baseline_blocks < self.warmup_blocks:
            raise ValueError("Invalid block/baseline sizes")
        for name in ("confirmation_blocks", "transfer_blocks", "post_exit_trades", "outcome_trades", "min_evidence"):
            if getattr(self, name) < 1:
                raise ValueError(name + " must be positive")
        for name in ("local_floor_bps", "local_vol_multiplier", "fee_bps", "slippage_bps", "notional", "gap_seconds", "large_trade_z", "absorption_z"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(name + " must be finite and nonnegative")
        if self.notional == 0 or self.gap_seconds == 0 or self.local_floor_bps == 0:
            raise ValueError("notional, gap and local floor must be positive")
        if not 0 < self.control_imbalance < 1 or not self.exit_models or len(set(self.exit_models)) != len(self.exit_models) or not set(self.exit_models) <= set(EXIT_MODELS):
            raise ValueError("Invalid control or exit models")

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Trade:
    symbol: str
    ts: float
    price: float
    quantity: float
    side: int
    trade_id: str
    received_at: float | None = None

    @property
    def notional(self):
        return self.price * self.quantity

    def valid(self):
        if any(type(x) not in (int, float) for x in (self.ts, self.price, self.quantity)):
            return False
        if self.received_at is not None and type(self.received_at) not in (int, float):
            return False
        return (self.symbol in SYMBOLS and type(self.side) is int and self.side in (-1, 1) and isinstance(self.trade_id, str) and bool(self.trade_id) and self.trade_id != "None"
                and all(math.isfinite(x) and x > 0 for x in (self.ts, self.price, self.quantity))
                and math.isfinite(self.notional)
                and (self.received_at is None or math.isfinite(self.received_at) and self.received_at > 0))


def robust_z(value, history):
    """Only past samples; a constant history uses a scale floor, never epsilon z explosions."""
    if len(history) < 8:
        return 0.0
    center = median(history)
    mad = median(abs(x - center) for x in history)
    scale = max(1.4826 * mad, abs(center) * 0.1, 1e-8)
    return max(-10.0, min(10.0, (value - center) / scale))


def features(block, history, config):
    buy = sum(t.notional for t in block if t.side == 1)
    sell = sum(t.notional for t in block if t.side == -1)
    total = buy + sell
    elapsed = block[-1].ts - block[0].ts
    # Same-timestamp batches have unknown intensity, not infinite intensity.
    intensity = len(block) / elapsed if elapsed > 0 else None
    b_rate = buy / elapsed if elapsed > 0 else None
    s_rate = sell / elapsed if elapsed > 0 else None
    move = (block[-1].price / block[0].price - 1) * 10000
    buy_response = sell_response = 0.0
    for previous, current in zip(block, block[1:]):
        delta = (current.price / previous.price - 1) * 10000
        if current.side == 1:
            buy_response += delta
        else:
            sell_response += delta
    old = history[-1] if history else {}
    def acceleration(rate, key):
        prior = old.get(key)
        return (rate - prior) / max(abs(prior), 1.0) if rate is not None and prior is not None else None
    sizes = [t.notional for t in block]
    prior_sizes = [x["average_trade_size"] for x in history]
    large = [t for t in block if robust_z(t.notional, prior_sizes) >= config.large_trade_z]
    imb = (buy - sell) / total
    total_z = robust_z(total, [x["notional"] for x in history])
    price_scale = max(config.local_floor_bps, median([abs(x["move_bps"]) for x in history]) if history else 0)
    avg_z = robust_z(total / len(block), prior_sizes)
    buy_accel = acceleration(b_rate, "buy_rate")
    sell_accel = acceleration(s_rate, "sell_rate")
    return {
        "start_ts": block[0].ts, "ts": block[-1].ts, "first_price": block[0].price,
        "price": block[-1].price, "low": min(t.price for t in block), "high": max(t.price for t in block),
        "buy_notional": buy, "sell_notional": sell, "notional": total,
        "quantity": sum(t.quantity for t in block), "buy_count": sum(t.side == 1 for t in block),
        "sell_count": sum(t.side == -1 for t in block), "trade_count": len(block),
        "duration": elapsed, "trade_intensity": intensity, "buy_rate": b_rate, "sell_rate": s_rate,
        "average_trade_size": total / len(block), "max_trade_size": max(sizes),
        "large_trade_count": len(large), "large_trade_notional": sum(t.notional for t in large),
        "large_trades": [{"ts": t.ts, "price": t.price, "side": t.side, "quantity": t.quantity,
                           "notional": t.notional, "trade_id": t.trade_id,
                           "size_z_against_prior_block_means": robust_z(t.notional, prior_sizes)} for t in large],
        "large_trade_series": max_run([t.side if t in large else 0 for t in block]),
        "imbalance": imb, "imbalance_change": imb - old.get("imbalance", 0),
        "imbalance_z": robust_z(imb, [x["imbalance"] for x in history]),
        "buy_acceleration": buy_accel, "sell_acceleration": sell_accel,
        "buy_deceleration": max(-buy_accel, 0) if buy_accel is not None else None,
        "sell_deceleration": max(-sell_accel, 0) if sell_accel is not None else None,
        "move_bps": move, "buy_response_bps": buy_response, "sell_response_bps": sell_response,
        "buy_efficiency_bps_per_10k": buy_response / buy * 10000 if buy else None,
        "sell_efficiency_bps_per_10k": -sell_response / sell * 10000 if sell else None,
        "net_buy_efficiency": move / buy * 10000 if buy else None,
        "net_sell_efficiency": -move / sell * 10000 if sell else None,
        "notional_z": total_z, "average_size_z": avg_z,
        "intensity_z": robust_z(intensity, [x["trade_intensity"] for x in history if x["trade_intensity"] is not None]) if intensity is not None else None,
        "buy_absorption": buy > sell and total_z >= config.absorption_z and move < price_scale * 0.25,
        "sell_absorption": sell > buy and total_z >= config.absorption_z and move > -price_scale * 0.25,
        "price_scale_bps": price_scale,
    }


def max_run(sides):
    best = run = 0
    last = None
    for side in sides:
        run = run + 1 if side and side == last else int(bool(side))
        best = max(best, run)
        last = side
    return best


@dataclass
class Local:
    ident: int
    kind: str
    price: float
    extreme_ts: float
    formed_ts: float
    status: str = "FORMING"
    confirmed_ts: float | None = None
    evidence: int = 0
    invalidated: bool = False


@dataclass
class Position:
    ident: str
    side: int
    entry: float
    opened: float
    quantity: float
    local_id: int
    local_price: float
    entry_snapshot: dict
    reentry: bool = False
    parent_exit: str | None = None
    current: float = 0
    mfe: float = 0
    mae: float = 0
    mfe_ts: float | None = None
    net_mfe: float = 0
    net_mae: float = 0
    bars: int = 0
    opposite_streak: int = 0
    weakening_streak: int = 0

    def mark(self, price, ts, fee_bps, slippage_bps):
        # MFE/MAE are gross USD marks; net marks estimate immediate executable liquidation.
        gross = (price - self.entry) * self.side * self.quantity
        liquidation = price * (1 - self.side * slippage_bps / 10000)
        net = (liquidation - self.entry) * self.side * self.quantity - (self.entry + liquidation) * self.quantity * fee_bps / 10000
        self.current = gross
        if gross > self.mfe:
            self.mfe, self.mfe_ts = gross, ts
        self.mae = min(self.mae, gross)
        self.net_mfe = max(self.net_mfe, net)
        self.net_mae = min(self.net_mae, net)
        return gross, net
