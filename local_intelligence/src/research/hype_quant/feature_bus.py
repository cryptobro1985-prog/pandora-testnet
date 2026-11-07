"""Small, dependency-free causal feature boundary shared by replay and live.

The contract describes *families*, not 116 scalar dimensions. An observation can
belong to several input families. Missing data stay missing; the bus never imputes
zero, invents receive times, or permits target/metadata IDs as predictors.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from typing import Any

from .feature_contract import INPUT_IDS


_TARGET_NAMES = frozenset({
    "label", "target", "y", "strict_true", "internal_true", "strict_label_id",
    "internal_label_id", "label_id", "label_available_ms", "reference_finalized",
    "reference_finalized_ms", "confirmed_side", "expected_side", "candidate_ts_ms",
    "snapshot_ts_ms", "signal_ts_ms", "confirmation_ts_ms", "accepted_true",
    "signal_delay", "signal_price_error", "precision", "recall", "false_local_rate",
    "last_confirmed_high", "last_confirmed_low", "active_swing_direction",
})


def is_predictive_name(name: str) -> bool:
    """Reject common target/provenance aliases, including namespaced aliases."""
    name = str(name).lower()
    parts = re.split(r"__|[.:/]", name)
    for part in parts:
        if part in _TARGET_NAMES or part.startswith(("target_", "label_", "post_analysis_", "metadata_", "provenance_")):
            return False
        match = re.fullmatch(r"(?:point|feature|id)[_-]?(\d+)", part)
        if match and int(match.group(1)) not in INPUT_IDS:
            return False
    return True


@dataclass(frozen=True)
class FeatureObservation:
    name: str
    point_ids: tuple[int, ...]
    value: float | None
    source_ts_ms: int | None
    received_ts_ms: int | None
    source: str
    max_age_ms: int | None = None
    quality: float = 1.0
    missing_reason: str | None = None
    historical: bool = False

    def evaluate(self, as_of_ms: int) -> dict[str, Any]:
        state = "available"
        reason = self.missing_reason
        if not self.point_ids or any(i not in INPUT_IDS for i in self.point_ids) or not is_predictive_name(self.name):
            state, reason = "forbidden", "target_metadata_or_unmapped_feature"
        elif self.value is None or isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not math.isfinite(self.value):
            state, reason = "missing", reason or "nonfinite_or_absent"
        elif reason:
            state = "unreliable"
        elif self.source_ts_ms is not None and self.source_ts_ms > as_of_ms:
            state, reason = "future", "source_after_prediction"
        elif self.received_ts_ms is not None and self.received_ts_ms > as_of_ms:
            state, reason = "future", "received_after_prediction"
        elif self.source_ts_ms is not None and self.received_ts_ms is not None and self.source_ts_ms > self.received_ts_ms:
            state, reason = "unreliable", "source_clock_after_receipt"
        elif self.received_ts_ms is None and not self.historical:
            state, reason = "missing", "unknown_receive_time"
        elif self.source_ts_ms is None and self.received_ts_ms is None:
            state, reason = "missing", "unknown_source_and_receive_time"
        elif not 0 < self.quality <= 1:
            state, reason = "unreliable", "invalid_quality"
        reference = self.source_ts_ms if self.source_ts_ms is not None else self.received_ts_ms
        age = None if reference is None else as_of_ms - reference
        if state == "available" and self.max_age_ms is not None and age is not None and age > self.max_age_ms:
            state, reason = "stale", "freshness_limit_exceeded"
        if state == "available" and self.historical and self.received_ts_ms is None:
            state = "source_time_only"
        elif state == "available" and self.source_ts_ms is None:
            state = "receive_time_only"
        return {
            **asdict(self), "feature_id": list(self.point_ids),
            "availability_state": state, "freshness_ms": age,
            "missing_or_unreliable": state not in {"available", "source_time_only", "receive_time_only"},
            "missing_reason": reason,
        }


@dataclass(frozen=True)
class FeatureSnapshot:
    as_of_ms: int
    observations: tuple[FeatureObservation, ...]

    @property
    def model_values(self) -> dict[str, float]:
        return {o.name: float(o.value) for o in self.observations
                if not o.evaluate(self.as_of_ms)["missing_or_unreliable"]}

    def as_dict(self) -> dict[str, Any]:
        evidence=[o.evaluate(self.as_of_ms) for o in self.observations]
        coverage={}
        for point in sorted(INPUT_IDS):
            rows=[r for r in evidence if point in r["point_ids"]]
            valid=[r for r in rows if not r["missing_or_unreliable"]]
            coverage[str(point)]={"availability_state":"available" if valid else "unavailable",
                                  "feature_count":len(valid),"example_feature_names":[r["name"] for r in valid[:3]],
                                  "missing_reason":None if valid else "no_usable_observation"}
        return {"version": "causal-feature-bus-v1", "as_of_ms": self.as_of_ms,
                "features": evidence,"contract_input_availability":coverage}


def _base_feature_spec(name: str) -> tuple[tuple[int, ...], str, int | None] | None:
    """Map audited numeric names to contract families, sources and freshness.

    Unknown names are rejected, so a new target alias cannot enter through the
    old unrestricted ``live__`` passthrough. TTLs are data safeguards, not fitted
    model parameters; transport ages remain available to describe stale feeds.
    """
    if not is_predictive_name(name):
        return None
    n = name.removeprefix("live__")
    if n in {"m1__side","m1__age_s"} or n.startswith("seq__"):
        return ((35,37),"micro",30_000)
    if n.startswith("log_") and n not in {"log_last_price", "log_oi_notional"}:
        return feature_spec(n[4:])
    if n.startswith("m1__"):
        return ((4,), "candles:1", 180_000)
    for prefix, ident, tf in (("m1_", 4, "1"), ("m3_", 5, "3"), ("m5_", 6, "5"), ("h1_", 7, "60")):
        if n.startswith(prefix):
            return ((ident,), "candles:" + tf, {"1": 180_000, "3": 540_000, "5": 900_000, "60": 10_800_000}[tf])
    if n in {"last_price", "log_last_price", "age_s", "retrace_bps", "reversal_attempts"} or n.startswith(("ret_", "rev_ret_", "running_", "dist_running_", "retracement_", "survival_", "positive_persistence_", "negative_persistence_")):
        return ((1, 35, 36, 37), "micro", 30_000)
    if n.startswith(("hist_mark_",)) or n == "mark_price":
        return ((2,), "ticker:markPrice", 120_000)
    if n.startswith(("hist_index_",)) or n == "index_price":
        return ((3,), "ticker:indexPrice", 120_000)
    if n in {"basis_bps", "basis_bps_raw", "hist_basis_bps"}:
        return ((114,), "basis", 120_000)
    if n in {"funding_rate", "hist_funding_rate", "hist_funding_available"}:
        return ((62,), "ticker:fundingRate", 600_000)
    if n in {"volume_24h", "volume_24h_log"}:
        return ((63,), "ticker:volume24h", 120_000)
    if n in {"turnover_24h", "turnover_24h_log"}:
        return ((64,), "ticker:turnover24h", 120_000)
    if n.startswith(("oi_", "hist_oi_", "hist_open_interest_", "price_oi_")) or n in {"open_interest", "open_interest_full", "ticker_open_interest", "log_oi_notional"}:
        return ((58, 59, 60, 61, 115), "ticker:openInterest", 600_000)
    if n.startswith(("trade_", "buy_efficiency_", "sell_efficiency_", "buy_price_response_", "sell_price_response_", "flow_imbalance_raw_", "last_trade_", "dominance_", "current_vs_prior_", "current_reversal_", "rev_eff_", "old_eff_", "rev_flow_", "imbalance_", "buy_", "sell_", "total_", "max_trade_")):
        return ((12, 20, 25, 26, 27), "trade", 900_000)
    if n.startswith(("l50_", "book_", "raw_best_", "raw_spread_", "bid_absorption_", "ask_absorption_")):
        if "invalidations" in n:
            return ((57,),"transport",None)
        if "valid" in n:
            return ((56, 57), "micro", 30_000)
        return ((44, 49, 50, 51, 52, 55), "book", 60_000)
    if n.startswith(("liq_", "last_liq_")):
        return ((65, 69, 70, 71, 72, 73, 74, 75, 76), "liquidation", 900_000)
    if n.startswith(("rolling_", "dist_rolling_", "position_", "distance_low_", "distance_high_")):
        return ((9, 10, 11), "structural", 180_000)
    if n in {"volatility_60m", "atr_h1_frac"} or n.startswith("directional_"):
        return ((4, 7), "candles:1" if n == "volatility_60m" else "candles:60", 10_800_000)
    if n.startswith("instrument_"):
        return ((112,), "instrument", 86_400_000)
    if n.startswith(("account_", "struct_long_", "struct_short_")):
        return ((113,), "account_ratio", 900_000)
    if n.startswith("struct_"):
        spec = feature_spec(n[7:])
        return (spec[0], "structural", min(spec[2] or 180_000, 180_000)) if spec else None
    if n in {"initial_backfill_seen", "rest_only_complete", "rest_relay_configured"}:
        return ((8,), "market_context", 600_000)
    if n.startswith("micro_gap_") or n=="channel_coverage_seconds":
        return ((77, 78, 79, 80, 111, 116), "micro", 30_000)
    if n.startswith(("raw_", "receipt_", "subscription_", "control_", "ws_")) or "latency_" in n:
        return ((77, 78, 79, 80, 111, 116), "transport", None)
    micro_names = {"spread_bps", "book_imbalance_5", "book_imbalance_25", "bid_depth_5", "ask_depth_5", "bid_depth_25", "ask_depth_25", "oi_change_since_prev_poll_pct", "ask_replenishment_proxy_ratio_60s", "bid_replenishment_proxy_ratio_60s"}
    if n in micro_names or n.startswith(("flow_imbalance_", "long_liq_notional_", "short_liq_notional_")):
        return ((55, 78), "micro", 30_000)
    if n in {"ticker_last_price", "high_24h", "low_24h", "price_24h_pct"}:
        return ((1,), "ticker:" + {"ticker_last_price":"lastPrice", "high_24h":"highPrice24h", "low_24h":"lowPrice24h", "price_24h_pct":"price24hPcnt"}[n], 120_000)
    return None


def feature_spec(name: str) -> tuple[tuple[int, ...], str, int | None] | None:
    spec=_base_feature_spec(name)
    if spec is None:return None
    n=name.removeprefix("live__")
    while n.startswith("log_") and n not in {"log_last_price","log_oi_notional"}:n=n[4:]
    if n.startswith("struct_"):n=n[7:]
    ids=None
    if n in {"last_price","log_last_price","ticker_last_price"} or n.startswith(("ret_","rev_ret_")):ids=(1,)
    elif n in {"age_s","m1__age_s"} or n.startswith("survival_"):ids=(37,)
    elif n.startswith("running_high_"):ids=(38,)
    elif n.startswith("running_low_"):ids=(39,)
    elif n=="retrace_bps" or n.startswith(("dist_running_","retracement_")):ids=(36,)
    elif n.startswith(("positive_persistence_","negative_persistence_")):ids=(35,)
    elif n.startswith("last_trade_"):
        ids=(13,) if "side" in n else (14,) if "price" in n else (15,) if "qty" in n else (16,)
    elif n.startswith("trade_buy_notional_"):ids=(17,)
    elif n.startswith("trade_sell_notional_"):ids=(18,)
    elif n.startswith(("trade_count_","trade_buy_count_","trade_sell_count_")):ids=(19,)
    elif n.startswith(("trade_buy_qty_","trade_sell_qty_")):ids=(15,)
    elif n.startswith("trade_cvd_"):ids=(25,)
    elif n.startswith(("flow_imbalance_","imbalance_","rev_flow_")):
        window=n.rsplit("_",1)[-1];ids=(20,)+((21,) if window=="5s" else (22,) if window=="15s" else (23,) if window=="60s" else ())
    elif n.startswith("dominance_"):ids=(24,)
    elif n.startswith("buy_price_response_"):ids=(26,)
    elif n.startswith("sell_price_response_"):ids=(27,)
    elif n.startswith("buy_efficiency_"):ids=(28,)
    elif n.startswith("sell_efficiency_"):ids=(29,)
    elif n.startswith("old_eff_"):ids=(30,)
    elif n.startswith("rev_eff_"):ids=(31,)
    elif n in {"reversal_attempts","current_reversal_attempt_active"}:ids=(41,)
    elif n.startswith("current_vs_prior_"):ids=(43,)
    elif n.startswith("l50_"):
        ids=(44,45 if "bid_" in n else 46,47 if "dist_bps" in n else 48)
    elif n in {"book_bid_levels","book_ask_levels"}:ids=(45,) if "bid" in n else (46,)
    elif n.startswith("bid_absorption_"):ids=(53,)
    elif n.startswith("ask_absorption_"):ids=(54,)
    elif n.startswith("book_bid_add_") or n.startswith("book_ask_add_"):ids=(49,50)
    elif n.startswith("book_bid_cancel_") or n.startswith("book_ask_cancel_"):ids=(49,51,52)
    elif "book_imbalance" in n:ids=(55,)
    elif "book_valid" in n:ids=(56,)
    elif n in {"book_sequence_raw","book_update_id_raw","book_invalidations_raw","book_invalidations"}:ids=(57,)
    elif n in {"open_interest","open_interest_full","ticker_open_interest","hist_open_interest_log","hist_oi_available"}:ids=(58,)
    elif n.startswith(("oi_delta_","hist_oi_delta_","oi_change_")):ids=(59,)
    elif n=="oi_age_ms":ids=(60,)
    elif n.startswith("price_oi_"):ids=(61,)
    elif n in {"oi_notional","log_oi_notional","hist_oi_notional_log"}:ids=(115,)
    elif n.startswith(("liq_count_",)):ids=(72,)
    elif n.startswith("liq_long_"):ids=(70,)
    elif n.startswith("liq_short_"):ids=(71,)
    elif n.startswith("last_liq_"):ids=(68,) if "side" in n else (66,) if "price" in n else (67,) if "qty" in n else (69,)
    elif n.startswith("liq_cluster_"):ids=(73,)
    elif n.startswith("liq_burst_x_price_"):ids=(74,)
    elif n.startswith("liq_burst_x_flow_"):ids=(75,)
    elif n.startswith("liq_burst_x_oi_"):ids=(76,)
    return (ids if ids is not None else spec[0],spec[1],spec[2])
