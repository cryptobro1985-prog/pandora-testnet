from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from river import compose, linear_model, preprocessing, optim


def finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(float(v))


def clean_features(x: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in x.items():
        if finite(v):
            out[str(k)] = float(v)
    return out


def value_model():
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        linear_model.LinearRegression(
            optimizer=optim.SGD(0.001),
            intercept_lr=0.001,
            l2=1e-6,
            clip_gradient=1.0,
        ),
    )


@dataclass
class PendingSnapshot:
    ts_ms: int
    price: float
    x: dict[str, float]
    horizon_s: int
    mature_ts_ms: int
    max_price: float
    min_price: float


@dataclass
class PaperPosition:
    side: int
    entry_ts_ms: int
    entry_price: float
    mfe: float = 0.0
    mae: float = 0.0
    current_return: float = 0.0


class MovementSignatureLearner:
    """Research-only, Local-independent movement-value learner.

    Training labels may use future path after maturity. Predictions may use only
    the causal feature snapshot passed to observe().
    """

    VERSION = "hype-movement-signature-v1"
    HORIZONS_S = (30, 60, 180, 300, 900, 1800)
    SAMPLE_EVERY_MS = 30_000

    def __init__(self, round_trip_cost: float = 0.0012, adverse_penalty: float = 1.0):
        self.round_trip_cost = float(round_trip_cost)
        self.adverse_penalty = float(adverse_penalty)

        self.long_models = {h: value_model() for h in self.HORIZONS_S}
        self.short_models = {h: value_model() for h in self.HORIZONS_S}
        self.long_labels = {h: 0 for h in self.HORIZONS_S}
        self.short_labels = {h: 0 for h in self.HORIZONS_S}

        self.pending: list[PendingSnapshot] = []
        self.position: PaperPosition | None = None
        self.last_sample_ms = 0
        self.last_ts_ms: int | None = None
        self.last_price: float | None = None

        self.actions: list[dict[str, Any]] = []
        self.label_stats = {
            h: {"long_value_sum": 0.0, "short_value_sum": 0.0}
            for h in self.HORIZONS_S
        }

    def _position_features(self, ts_ms: int, price: float) -> dict[str, float]:
        if self.position is None:
            return {
                "pos_is_open": 0.0,
                "pos_side": 0.0,
                "pos_age_s": 0.0,
                "pos_current_return": 0.0,
                "pos_mfe": 0.0,
                "pos_mae": 0.0,
                "pos_mfe_recoil": 0.0,
            }

        p = self.position
        cur = p.side * (price / p.entry_price - 1.0)
        p.current_return = cur
        p.mfe = max(p.mfe, cur)
        p.mae = min(p.mae, cur)
        return {
            "pos_is_open": 1.0,
            "pos_side": float(p.side),
            "pos_age_s": max(0.0, (ts_ms - p.entry_ts_ms) / 1000.0),
            "pos_current_return": cur,
            "pos_mfe": p.mfe,
            "pos_mae": p.mae,
            "pos_mfe_recoil": max(0.0, p.mfe - cur),
        }

    def _advance_labels(self, ts_ms: int, price: float) -> None:
        keep: list[PendingSnapshot] = []
        for p in self.pending:
            p.max_price = max(p.max_price, price)
            p.min_price = min(p.min_price, price)
            if ts_ms < p.mature_ts_ms:
                keep.append(p)
                continue

            up_mfe = p.max_price / p.price - 1.0
            down_mfe = 1.0 - p.min_price / p.price
            long_value = up_mfe - self.adverse_penalty * down_mfe - self.round_trip_cost
            short_value = down_mfe - self.adverse_penalty * up_mfe - self.round_trip_cost

            self.long_models[p.horizon_s].learn_one(p.x, long_value)
            self.short_models[p.horizon_s].learn_one(p.x, short_value)
            self.long_labels[p.horizon_s] += 1
            self.short_labels[p.horizon_s] += 1
            self.label_stats[p.horizon_s]["long_value_sum"] += long_value
            self.label_stats[p.horizon_s]["short_value_sum"] += short_value

        self.pending = keep

    def _predict_values(self, x: dict[str, float]) -> dict[str, Any]:
        by_h: dict[int, dict[str, float | None]] = {}
        for h in self.HORIZONS_S:
            if self.long_labels[h] < 20:
                by_h[h] = {"long": None, "short": None}
                continue
            lv = self.long_models[h].predict_one(x)
            sv = self.short_models[h].predict_one(x)
            by_h[h] = {
                "long": float(lv or 0.0),
                "short": float(sv or 0.0),
            }

        ready = [z for z in by_h.values() if z["long"] is not None]
        if not ready:
            return {
                "ready": False,
                "by_horizon": by_h,
                "long_value": None,
                "short_value": None,
                "directional_edge": None,
            }

        # Robust median across ready horizons rather than letting one horizon dominate.
        longs = sorted(float(z["long"]) for z in ready)
        shorts = sorted(float(z["short"]) for z in ready)
        mid = len(longs) // 2
        long_med = longs[mid] if len(longs) % 2 else (longs[mid - 1] + longs[mid]) / 2
        short_med = shorts[mid] if len(shorts) % 2 else (shorts[mid - 1] + shorts[mid]) / 2
        return {
            "ready": True,
            "by_horizon": by_h,
            "long_value": long_med,
            "short_value": short_med,
            "directional_edge": long_med - short_med,
        }

    def _shadow_state(self, pred: dict[str, Any], posx: dict[str, float]) -> str:
        if not pred.get("ready"):
            return "LEARNING"

        lv = float(pred["long_value"])
        sv = float(pred["short_value"])
        min_edge = self.round_trip_cost

        if self.position is None:
            if max(lv, sv) <= min_edge:
                return "NEUTRAL"
            return "START_LONG" if lv > sv else "START_SHORT"

        side = self.position.side
        own = lv if side > 0 else sv
        opp = sv if side > 0 else lv
        recoil = float(posx.get("pos_mfe_recoil", 0.0))
        cur = float(posx.get("pos_current_return", 0.0))

        # State labels only. No real execution in this learner.
        if opp > max(own, min_edge) and own < 0:
            return "REVERSE_TO_SHORT" if side > 0 else "REVERSE_TO_LONG"
        if own <= 0 and (recoil > 0 or cur <= 0):
            return "WEAKEN_EXIT"
        if own > min_edge:
            return "HOLD_CONTINUE"
        return "HOLD_CAUTION"

    def observe(self, ts_ms: int, price: float, features: dict[str, Any]) -> dict[str, Any]:
        ts_ms = int(ts_ms)
        price = float(price)
        if price <= 0:
            raise ValueError("price must be positive")

        self._advance_labels(ts_ms, price)

        posx = self._position_features(ts_ms, price)
        x = clean_features({**features, **posx})
        pred = self._predict_values(x)
        state = self._shadow_state(pred, posx)

        if ts_ms - self.last_sample_ms >= self.SAMPLE_EVERY_MS:
            for h in self.HORIZONS_S:
                self.pending.append(
                    PendingSnapshot(
                        ts_ms=ts_ms,
                        price=price,
                        x=dict(x),
                        horizon_s=h,
                        mature_ts_ms=ts_ms + h * 1000,
                        max_price=price,
                        min_price=price,
                    )
                )
            self.last_sample_ms = ts_ms

        result = {
            "version": self.VERSION,
            "ts_ms": ts_ms,
            "price": price,
            "state": state,
            "predicted": pred,
            "position": None if self.position is None else {
                "side": "LONG" if self.position.side > 0 else "SHORT",
                "entry_price": self.position.entry_price,
                "entry_ts_ms": self.position.entry_ts_ms,
                "current_return": self.position.current_return,
                "mfe": self.position.mfe,
                "mae": self.position.mae,
                "mfe_recoil": max(0.0, self.position.mfe - self.position.current_return),
            },
            "research_only": True,
            "real_orders": False,
        }
        self.actions.append(result)
        self.last_ts_ms = ts_ms
        self.last_price = price
        return result

    def paper_open(self, ts_ms: int, price: float, side: int) -> None:
        if side not in (-1, 1):
            raise ValueError("side must be -1 or 1")
        self.position = PaperPosition(
            side=side,
            entry_ts_ms=int(ts_ms),
            entry_price=float(price),
        )

    def paper_close(self) -> None:
        self.position = None

    def report(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "research_only": True,
            "real_orders": False,
            "round_trip_cost": self.round_trip_cost,
            "adverse_penalty": self.adverse_penalty,
            "labels": {
                str(h): {
                    "long": self.long_labels[h],
                    "short": self.short_labels[h],
                    "mean_long_value": (
                        self.label_stats[h]["long_value_sum"] / self.long_labels[h]
                        if self.long_labels[h] else None
                    ),
                    "mean_short_value": (
                        self.label_stats[h]["short_value_sum"] / self.short_labels[h]
                        if self.short_labels[h] else None
                    ),
                }
                for h in self.HORIZONS_S
            },
            "pending": len(self.pending),
            "last_state": self.actions[-1] if self.actions else None,
        }
