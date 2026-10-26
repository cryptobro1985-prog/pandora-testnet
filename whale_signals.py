"""Causal, venue-scoped liquidation pressure helpers for PAPER research.

The floors and ratios below are conservative *research parameters*, not fitted
optimal levels. A danger-zone position is potential forced flow, not a confirmed
liquidation or complete view of the global derivatives market.
"""
import hashlib
import math


MIN_NOTIONAL_USD = {"BTC": 25_000_000.0, "ETH": 15_000_000.0, "SOL": 5_000_000.0}
DEFAULT_MIN_NOTIONAL_USD = 25_000.0
CLUSTER_WIDTH_BPS = 10.0
MARK_MAX_AGE_SECONDS = 15.0
MAX_INPUT_ROWS = 10_000


def _finite(value, positive=False):
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(value) or (positive and value <= 0):
        return None
    return value


def _epoch(value):
    value = _finite(value, positive=True)
    if value is not None and value >= 100_000_000_000:
        value /= 1000.0
    return value


def cluster_positions(rows, prices, contexts, epoch, max_age=180.0,
                      max_distance_pct=1.5):
    """Deduplicate wallets, then group nearby liquidation levels.

    ``side`` remains the victim's string side for compatibility with danger-zone
    records; ``trade_side`` is its opposite. ``cluster_id`` uses wallet identity,
    so a small quote/level update does not manufacture another confirmation.
    Missing wallet identity is rejected rather than counted as another whale.
    """
    epoch = _finite(epoch, positive=True)
    if epoch is None or not isinstance(rows, (list, tuple)):
        return []
    unique = {}
    for item in rows[:MAX_INPUT_ROWS]:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).upper()
        if not symbol:
            continue
        price = _finite(prices.get(symbol), positive=True)
        ctx = contexts.get(symbol, {})
        if not isinstance(ctx, dict):
            continue
        mark = _finite(ctx.get("mark_price"), positive=True)
        mark_epoch = _epoch(ctx.get("epoch"))
        if price is None or mark is None or mark_epoch is None or not 0 <= epoch-mark_epoch <= MARK_MAX_AGE_SECONDS:
            continue
        side = str(item.get("side", "")).lower()
        if side not in ("long", "short"):
            continue
        wallet = str(item.get("address") or item.get("user") or "").strip().lower()
        size = _finite(item.get("size_usd"), positive=True)
        level = _finite(item.get("liq_price"), positive=True)
        scanned = _epoch(item.get("scanned_at"))
        if not wallet or len(wallet) > 128 or size is None or level is None or scanned is None:
            continue
        if not 0 <= epoch-scanned <= max_age:
            continue
        if (side == "long" and level >= mark) or (side == "short" and level <= mark):
            continue
        distance = abs(mark-level)/mark*100.0
        if not 0.08 <= distance <= max_distance_pct:
            continue
        key = (symbol, side, wallet)
        record = {"symbol": symbol, "side": side, "address": wallet,
                  "size_usd": size, "liq_price": level, "scanned_at": scanned,
                  "mark_price": mark}
        old = unique.get(key)
        # A duplicate must never increase cluster notional. Deterministic tie
        # handling also prevents input ordering from changing accepted exposure.
        if old is None or (scanned, -size, level) > (old["scanned_at"], -old["size_usd"], old["liq_price"]):
            unique[key] = record

    groups = {}
    for row in unique.values():
        groups.setdefault((row["symbol"], row["side"]), []).append(row)
    out = []
    for (symbol, side), records in sorted(groups.items()):
        records.sort(key=lambda r: (r["liq_price"], r["address"]))
        clusters = []
        for row in records:
            if not clusters or (row["liq_price"]/clusters[-1][0]["liq_price"]-1.0)*10_000 > CLUSTER_WIDTH_BPS+1e-8:
                clusters.append([row])
            else:
                clusters[-1].append(row)
        for members in clusters:
            size = sum(r["size_usd"] for r in members)
            if not math.isfinite(size):
                continue
            level = sum((r["size_usd"]/size)*r["liq_price"] for r in members)
            wallets = sorted(r["address"] for r in members)
            ident = hashlib.sha256((symbol+":"+side+":"+",".join(wallets)).encode()).hexdigest()[:24]
            mark = members[0]["mark_price"]
            oldest = min(r["scanned_at"] for r in members)
            out.append({"symbol": symbol, "side": side, "victim_side": side,
                        "trade_side": -1 if side == "long" else 1,
                        "size_usd": size, "liq_price": level, "scanned_at": oldest,
                        "mark_price": mark, "distance_pct": abs(mark-level)/mark*100.0,
                        "position_age_seconds": epoch-oldest, "evaluated_at": epoch,
                        "cluster_id": ident, "wallet_count": len(wallets), "wallets": wallets,
                        "address": wallets[0] if len(wallets) == 1 else None,
                        "liquidation_range_low": min(r["liq_price"] for r in members),
                        "liquidation_range_high": max(r["liq_price"] for r in members),
                        "cluster_width_bps": CLUSTER_WIDTH_BPS,
                        "coverage": "observed_hyperliquid_wallets_only"})
    return sorted(out, key=lambda c: (-c["size_usd"], c["cluster_id"]))


def summarize_book(payload, depth_bps=10.0):
    """Measure notional depth inside a price band, retaining coverage limits.

    An aggregated l2Book ladder is often needed to span the band. A truncated
    ladder gives only a lower bound on depth and cannot prove large impact.
    """
    if not isinstance(payload, dict) or not 0 < depth_bps <= 100:
        return None
    levels = payload.get("levels")
    if not isinstance(levels, list) or len(levels) != 2:
        return None
    ladders = []
    for raw in levels:
        if not isinstance(raw, list):
            return None
        clean = []
        for row in raw[:1000]:
            if not isinstance(row, dict):
                return None
            px = _finite(row.get("px"), positive=True)
            sz = _finite(row.get("sz"), positive=True)
            if px is None or sz is None:
                return None
            clean.append((px, sz))
        if not clean:
            return None
        ladders.append(clean)
    bids = sorted(ladders[0], reverse=True)
    asks = sorted(ladders[1])
    best_bid, best_ask = bids[0][0], asks[0][0]
    if best_bid >= best_ask:
        return None
    mid = (best_bid+best_ask)/2.0
    low, high = mid*(1-depth_bps/10_000), mid*(1+depth_bps/10_000)
    bid_depth = sum(px*sz for px, sz in bids if px >= low)
    ask_depth = sum(px*sz for px, sz in asks if px <= high)
    total = bid_depth+ask_depth
    if not all(math.isfinite(v) for v in (bid_depth, ask_depth, total)):
        return None
    return {"bid_depth_usd": bid_depth, "ask_depth_usd": ask_depth,
            "imbalance": (bid_depth-ask_depth)/total if total else 0.0,
            "spread_bps": (best_ask-best_bid)/mid*10_000,
            "mid_price": mid, "depth_bps": depth_bps,
            "bid_depth_complete": bids[-1][0] <= low,
            "ask_depth_complete": asks[-1][0] >= high,
            "epoch": _epoch(payload.get("time"))}


def significance(cluster, book, ctx, floors=None, oi_fraction=0.0025,
                 flow_multiple=2.0, min_impact=0.5):
    """Require material potential flow relative to this venue's OI and depth.

    All thresholds are prospective research settings. The 20% first-slice model
    follows Hyperliquid's partial-liquidation rule, and is a scenario estimate.
    No unavailable data is replaced by zero or by a global market assumption.
    """
    floors = MIN_NOTIONAL_USD if floors is None else floors
    result = {"allowed": False, "reason": "invalid_cluster",
              "policy": "conservative_research_v1_not_calibrated",
              "coverage": "observed_hyperliquid_wallets_only"}
    if not isinstance(cluster, dict) or not isinstance(ctx, dict):
        return result
    symbol = cluster.get("symbol")
    size = _finite(cluster.get("size_usd"), positive=True)
    floor = _finite(floors.get(symbol, floors.get("__DEFAULT__", DEFAULT_MIN_NOTIONAL_USD)), positive=True)
    stamp = _epoch(cluster.get("evaluated_at"))
    mark = _finite(ctx.get("mark_price"), positive=True)
    ctx_epoch = _epoch(ctx.get("epoch"))
    if size is None or floor is None or stamp is None:
        return result
    result.update({"floor_notional_usd": floor, "minimum_notional_usd": floor,
                   "min_notional": floor, "whale_size_usd": size})
    if mark is None or ctx_epoch is None or not 0 <= stamp-ctx_epoch <= MARK_MAX_AGE_SECONDS:
        return dict(result, reason="stale_or_missing_mark")
    oi_units = _finite(ctx.get("open_interest"), positive=True)
    oi_usd = _finite(ctx.get("open_interest_usd"), positive=True)
    if oi_usd is None and oi_units is not None:
        oi_usd = oi_units*mark
    if oi_usd is None or not math.isfinite(oi_usd):
        return dict(result, reason="missing_open_interest")
    coverage = _finite(ctx.get("trade_coverage_seconds"))
    buy = _finite(ctx.get("buy_volume_60s"))
    sell = _finite(ctx.get("sell_volume_60s"))
    if (ctx.get("volume_source") != "hyperliquid_ws_trades" or
            ctx.get("trade_data_fresh") is not True or coverage is None or coverage < 60 or
            buy is None or sell is None or min(buy, sell) < 0):
        return dict(result, reason="missing_observed_trade_flow")
    flow = buy+sell
    minimum = max(floor, oi_fraction*oi_usd, flow_multiple*flow)
    result.update({"minimum_notional_usd": minimum, "min_notional": minimum,
                   "open_interest_usd": oi_usd, "size_to_oi": size/oi_usd,
                   "observed_volume_60s_usd": flow,
                   "size_to_60s_flow": size/flow if flow > 0 else None,
                   "forced_flow_first_slice_usd": size*0.20,
                   "oi_fraction_threshold": oi_fraction,
                   "flow_multiple_threshold": flow_multiple,
                   "minimum_flow_to_depth": min_impact})
    if size < minimum:
        return dict(result, reason="insignificant_cluster_notional")
    if not isinstance(book, dict):
        return dict(result, reason="missing_orderbook")
    victim = cluster.get("victim_side", cluster.get("side"))
    if victim not in ("long", "short"):
        return dict(result, reason="invalid_cluster_side")
    prefix = "bid" if victim == "long" else "ask"
    depth = _finite(book.get(prefix+"_depth_usd"), positive=True)
    spread = _finite(book.get("spread_bps"))
    if book.get(prefix+"_depth_complete") is not True:
        return dict(result, reason="insufficient_book_depth_coverage")
    if depth is None or spread is None or not 0 <= spread <= 12:
        return dict(result, reason="invalid_or_wide_orderbook")
    book_stamp = _epoch(book.get("epoch"))
    if book_stamp is None or not 0 <= stamp-book_stamp <= 5.0:
        return dict(result, reason="stale_or_missing_orderbook_time")
    impact = size*0.20/depth
    result.update({"opposing_depth_usd": depth, "liquidation_flow_to_depth": impact,
                   "depth_bps": book.get("depth_bps"), "spread_bps": spread})
    if impact < min_impact:
        return dict(result, reason="insignificant_liquidation_impact")
    return dict(result, allowed=True, reason="material_venue_liquidation_pressure")


def update_streaks(candidates, prior, scan_id):
    """Annotate one confirmation per cluster per scan; absent clusters reset.

    ``prior`` and the return value map cluster IDs to ``{count, scan_id}``.
    Passing the same scan ID twice cannot create a second confirmation.
    """
    result = {}
    for candidate in candidates:
        key = candidate.get("cluster_id")
        if not key:
            candidate["confirmation_streak"] = 0
            continue
        if key not in result:
            old = prior.get(key, {})
            count = int(old.get("count", 0))
            result[key] = {"count": count if old.get("scan_id") == scan_id else count+1,
                           "scan_id": scan_id}
        candidate["confirmation_streak"] = result[key]["count"]
    return result


PRICE_TO_VALUE_POLICY = "price_to_value_liquidation_v1"
PTV_MAX_ENTRY_DISTANCE_PCT = 0.95
PTV_MIN_CONTRACTION_PCT = 0.015


class PriceToValueTracker:
    """Track whether price is actually moving toward a liquidation cluster."""

    def __init__(self):
        self._history = {}
        self._last_scan = {}

    def observe(self, candidates, scan_id, epoch):
        out = []
        for raw in candidates:
            x = dict(raw)
            key = str(x.get("cluster_id") or "")
            if not key:
                continue
            distance = _finite(x.get("distance_pct"))
            if distance is None or distance < 0:
                continue
            hist = self._history.setdefault(key, [])
            last_scan = self._last_scan.get(key)
            if last_scan is not None and scan_id-last_scan > 3:
                hist.clear()
            if not hist or hist[-1][0] != scan_id:
                hist.append((scan_id, float(epoch), distance))
            hist[:] = [row for row in hist if 0 <= float(epoch)-row[1] <= 45.0][-12:]
            self._last_scan[key] = scan_id

            values = [row[2] for row in hist]
            contraction = values[0]-values[-1] if len(values) >= 2 else 0.0
            last_step = values[-2]-values[-1] if len(values) >= 2 else 0.0
            non_widening = len(values) >= 2 and last_step >= -0.005
            approaching = (
                len(values) >= 2
                and non_widening
                and (contraction >= PTV_MIN_CONTRACTION_PCT or last_step >= 0.01)
            )
            x["ptv_policy"] = PRICE_TO_VALUE_POLICY
            x["ptv_distance_history_pct"] = [round(v, 6) for v in values]
            x["ptv_distance_contraction_pct"] = round(contraction, 6)
            x["ptv_last_distance_step_pct"] = round(last_step, 6)
            x["ptv_approaching"] = bool(approaching)
            out.append(x)

        for key, last in list(self._last_scan.items()):
            if scan_id-last > 20:
                self._last_scan.pop(key, None)
                self._history.pop(key, None)
        return out


def price_to_value_entry(candidate, regime_side=0):
    """Score trend, nearest target, approach and micro pressure without unanimity."""
    x = dict(candidate)
    reasons = []
    side = int(x.get("side") or 0)
    distance = _finite(x.get("distance_pct"))
    if side not in (-1, 1) or distance is None:
        x["ptv_qualified"] = False
        x["ptv_reject_reasons"] = ["invalid_direction_or_distance"]
        return x

    dynamic = _finite(x.get("dynamic_entry_distance_pct"))
    if dynamic is None or dynamic <= 0:
        dynamic = PTV_MAX_ENTRY_DISTANCE_PCT
    entry_cap = min(PTV_MAX_ENTRY_DISTANCE_PCT, max(0.25, dynamic))
    if distance > entry_cap:
        reasons.append("outside_entry_distance")

    r15 = _finite(x.get("r15")) or 0.0
    r60 = _finite(x.get("r60")) or 0.0
    r300 = _finite(x.get("r300"))
    r900 = _finite(x.get("r900"))
    fast_votes = int(side*r15 >= 0.00015) + int(side*r60 >= 0.00035)
    slow_votes = 0
    slow_count = 0
    if r300 is not None:
        slow_count += 1
        slow_votes += int(side*r300 >= -0.00025)
    if r900 is not None:
        slow_count += 1
        slow_votes += int(side*r900 >= -0.00075)
    strong_slow_against = (
        (r300 is not None and side*r300 <= -0.0020)
        or (r900 is not None and side*r900 <= -0.0035)
    )
    trend_ok = fast_votes >= 1 and fast_votes+slow_votes >= 2 and not strong_slow_against
    if not trend_ok:
        reasons.append("trend_not_toward_liquidation")

    approaching = bool(x.get("ptv_approaching"))
    approach_ok = approaching or (distance <= 0.30 and fast_votes >= 1)
    if not approach_ok:
        reasons.append("target_not_approaching")

    flow = _finite(x.get("flow_imbalance")) or 0.0
    book = _finite(x.get("orderbook_imbalance")) or 0.0
    spread = _finite(x.get("spread_bps"))
    impact = _finite(x.get("liquidation_flow_to_depth")) or 0.0
    burst = _finite(x.get("volume_burst_ratio")) or 0.0
    vol_z = _finite(x.get("volume_rate_z"))
    micro_votes = 0
    micro_votes += int(side*flow >= 0.04)
    micro_votes += int(side*book >= 0.03 and (spread is None or spread <= 15.0))
    micro_votes += int(impact >= 0.25)
    micro_votes += int(burst >= 1.15 or (vol_z is not None and vol_z >= 1.3))
    micro_required = 1 if distance <= 0.30 else 2
    if micro_votes < micro_required:
        reasons.append("micro_pressure_too_weak")

    regime_side = int(regime_side or 0)
    regime_conflict = regime_side in (-1, 1) and regime_side != side
    if regime_conflict and not (distance <= 0.45 and fast_votes == 2 and micro_votes >= 2):
        reasons.append("market_regime_conflict")

    proximity = max(0.0, 1.0-distance/max(entry_cap, 0.01))
    contraction = max(0.0, _finite(x.get("ptv_distance_contraction_pct")) or 0.0)
    slow_ratio = slow_votes/max(1, slow_count)
    quality = (
        25.0*proximity
        + 22.0*(fast_votes/2.0)
        + 13.0*slow_ratio
        + 15.0*min(1.0, contraction/0.08)
        + 15.0*min(1.0, micro_votes/3.0)
        + 10.0*min(1.0, impact/1.0)
    )
    if distance <= 0.30 and fast_votes >= 1:
        quality += 5.0
    quality = min(100.0, quality)

    x["ptv_entry_distance_cap_pct"] = round(entry_cap, 6)
    x["ptv_fast_trend_votes"] = fast_votes
    x["ptv_slow_trend_votes"] = slow_votes
    x["ptv_micro_votes"] = micro_votes
    x["ptv_regime_side"] = regime_side
    x["ptv_quality_score"] = round(quality, 2)
    x["ptv_reject_reasons"] = reasons
    x["ptv_qualified"] = not reasons and quality >= 60.0
    if not x["ptv_qualified"] and not reasons:
        x["ptv_reject_reasons"] = ["quality_below_min"]
    return x
