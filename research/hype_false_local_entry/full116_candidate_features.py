"""Causal, point-addressable decision states for the strict HYPE local replay.

Availability is represented by absent values. The archived M1 plane and the
certified snapshot plane use separate adapters because their clocks differ.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from research.hype_false_local_entry import early_trajectory_features as m1
from research.hype_quant.feature_contract import INPUT_IDS

EARLY_AGES = (*m1.AGES_S, 3600)
COMPARATOR_AGES = (5400, 7200, 12900, 15000)
AGES = (*EARLY_AGES, *COMPARATOR_AGES)
WINDOWS = (5, 15, 30, 60, 180, 300)
LIQ_WINDOWS = (5, 15, 60, 180, 300)
MICRO_CONTRACT = "decoded-liquidations-continuous-book-v1"
HISTORICAL_POINTS = frozenset({
    1, *range(4, 21), *range(23, 44), 63, 64, 79, 80,
})
# The tape preserves aggregate evidence for these IDs, not the original stream
# or an exchange-published trailing statistic.
AGGREGATED_POINTS = frozenset({12, 13, 14, 15, 16, 63, 64})
# These refer to the observable candidate lineage, not future terminal outcomes.
PROXY_POINTS = frozenset({41, 42, 43})
PRICE_POINTS = frozenset({1, *range(4, 12), *range(35, 44), 63, 64})


def put(out, point, **values):
    if point not in INPUT_IDS:
        raise ValueError(f"point {point} is forbidden in predictors")
    for name, value in values.items():
        if value is not None and math.isfinite(value):
            out[f"p{point:03d}_{name}"] = float(value)


def point_id(name):
    point = int(name[1:4])
    if name[:1] != "p" or name[4:5] != "_" or point not in INPUT_IDS:
        raise ValueError(f"invalid predictor name: {name}")
    return point


def available_points(values):
    return {point_id(name) for name, value in values.items() if math.isfinite(value)}


def candidate_timeline(tape, start, stop, side):
    """Positions of current-hour extremes and their first stricter replacement."""
    sign = 1 if side == "LOW" else -1
    extreme = tape.low if side == "LOW" else tape.high
    stamps = tape.low_ts if side == "LOW" else tape.high_ts
    oriented = -sign * extreme
    # Next stricter bar for each M1 observation. Equal prices keep the original.
    next_ext = np.full(stop - start, stop, dtype=np.int64)
    stack = []
    for i in range(stop - 1, start - 1, -1):
        while stack and oriented[stack[-1]] <= oriented[i]:
            stack.pop()
        if stack:
            next_ext[i - start] = stack[-1]
        stack.append(i)
    first = int(np.searchsorted(tape.start, m1.ready_at(tape.start[start])))
    for hour in range(first, stop, 60):
        for i in m1.side_candidates(oriented, hour, min(stop, hour + 60)):
            yield int(i), int(stamps[i]), float(extreme[i]), int(next_ext[i - start])


def tape_amounts(rows, name):
    out = np.asarray([
        r.get(name, np.nan) if r.get("flow_observed", True) else np.nan for r in rows
    ], dtype=float)
    out[(out < 0) | ~np.isfinite(out)] = np.nan
    return out


def causal_decision_bars(tape, candidate_ts_ms, end_bar, start_bar=0):
    """Yield completed M1 bar indices strictly after a candidate, before replacement.

    This is a causal event clock, not a fixed candidate-age grid. A completed
    bar is the finest decision event available on the archived M1 plane;
    tick/L50 events require their own timestamped adapter. No oracle labels
    or future same-side extrema are used to select decision timestamps.
    """
    first = max(start_bar, int(np.searchsorted(tape.end, candidate_ts_ms, side="right")))
    for k in range(first, end_bar):
        if int(tape.end[k]) > candidate_ts_ms:
            yield k


def m1_states(rows, ages=AGES):
    """Return chronological decision rows and outcome-free candidate identities."""
    tape = m1.tape_from_rows(rows)
    opens = np.asarray([r["open"] for r in rows], dtype=float)
    volume, turnover, trade_count = [
        tape_amounts(rows, key) for key in ("volume", "turnover", "trade_count")
    ]
    states, candidates = [], []
    for start, stop in m1.segments(tape):
        close = tape.close[start:stop]
        logret = np.r_[np.nan, np.diff(np.log(close))] * 10_000
        for side in m1.SIDES:
            sign = 1 if side == "LOW" else -1
            lineage = list(candidate_timeline(tape, start, stop, side))
            prior = []
            new, old = (tape.buy, tape.sell) if sign == 1 else (tape.sell, tape.buy)
            for i, ts, price, end in lineage:
                candidate = dict(side=side, candidate_id=f"{side}-{ts}", candidate_ts_ms=ts,
                                 price=price, bar_idx=i)
                candidates.append(candidate)
                # A prior attempt is an observed extension, not a teacher label.
                recent = [entry for entry in prior if entry[0] >= i - 360]
                prior = [*recent, (i, price, end)]
                pre_hi, pre_lo = tape.high[i-180:i].max(), tape.low[i-180:i].min()
                pre_move = (pre_hi / price - 1 if sign == 1 else price / pre_lo - 1) * 10_000
                for age in ages:
                    k = int(np.searchsorted(tape.end, ts + age * 1000))
                    if k >= end:
                        break
                    now = int(tape.end[k])
                    mark = float(tape.close[k])
                    retrace = sign * (mark / price - 1) * 10_000
                    values = {}
                    put(values, 1, last_trade_close_change=sign*(mark/tape.close[k-1]-1))
                    for n, point in ((1, 4), (3, 5), (5, 6), (60, 7)):
                        # Absolute-time aligned, completed candles only.
                        j = k - (now // m1.MINUTE) % n
                        a = j + 1 - n
                        if a < start:
                            continue
                        lo, hi = tape.low[a:j+1].min(), tape.high[a:j+1].max()
                        put(values, point, direction_return=sign*(tape.close[j]/opens[a]-1),
                            range_bps=(hi/lo-1)*10_000,
                            volume_log=np.log1p(volume[a:j+1].sum()),
                            turnover_log=np.log1p(turnover[a:j+1].sum()))
                    put(values, 8, pre_move_180_bps=pre_move)
                    for n, point in ((60, 9), (360, 10), (1440, 11)):
                        a = k+1-n
                        if a < start:
                            continue
                        lo, hi = tape.low[a:k+1].min(), tape.high[a:k+1].max()
                        pos = (mark-lo)/(hi-lo) if hi > lo else np.nan
                        put(values, point, position=pos, range_bps=(hi/lo-1)*10_000,
                            normalized_recovery=retrace/((hi/lo-1)*10_000) if hi > lo else np.nan)
                    if k+1-1440 >= start:
                        put(values, 63, rolling_volume_log=np.log1p(volume[k+1-1440:k+1].sum()))
                        put(values, 64, rolling_turnover_log=np.log1p(turnover[k+1-1440:k+1].sum()))
                    post = sign * logret[i+1-start:k+1-start]
                    put(values, 35, persistence=np.mean(post > 0) if post.size else np.nan,
                        realized_volatility=float(np.linalg.norm(post)))
                    put(values, 36, retrace_bps=retrace)
                    put(values, 37, survival_seconds=(now-ts)/1000)
                    put(values, 38, running_high_distance=tape.high[i:k+1].max()/mark-1)
                    put(values, 39, running_low_distance=mark/tape.low[i:k+1].min()-1)
                    replaced = [entry for entry in recent if entry[2] <= i]
                    put(values, 40, minutes_since_prior_extension=i-max(r[2] for r in replaced) if replaced else None)
                    put(values, 41, proposals_last_6h=len(recent))
                    put(values, 42, replaced_proposals_last_6h=len(replaced))
                    put(values, 43, price_vs_last_replaced=sign*(price/replaced[-1][1]-1) if replaced else None)
                    put(values, 79, decision_segment_gap=0)
                    put(values, 80, consecutive_completed_minutes=k+1-start)
                    if age in EARLY_AGES:
                        trade_trajectories(values, tape, i, k, start, sign, new, old,
                                           logret, opens, volume, trade_count)
                    states.append(dict(candidate, age_s=age, signal_ts_ms=now,
                                       signal_price=mark, retrace_bps=retrace,
                                       pre_move_180_bps=float(pre_move), features=values))
    states.sort(key=lambda row: (row["signal_ts_ms"], row["candidate_ts_ms"], row["side"]))
    return tape, states, candidates


def trade_trajectories(out, tape, i, k, start, sign, new, old, logret, opens, volume, count):
    """Compare nonoverlapping executed-flow windows, excluding the extreme bar."""
    post_bps = sign * logret[i+1-start:k+1-start]
    put(out, 32, m1_displacement=sign*(tape.close[k]/opens[k]-1))
    for n, point in ((3, 33), (5, 34)):
        if post_bps.size >= n:
            put(out, point, signed_return_bps=post_bps[-n:].sum())
    for n in (1, 3, 5, 10, 15, 30, 60):
        a = k+1-n
        if a < start:
            continue
        put(out, 12, **{f"m{n}_log_total": np.log1p((tape.buy[a:k+1]+tape.sell[a:k+1]).sum())})
        put(out, 17, **{f"m{n}_log_buy": np.log1p(tape.buy[a:k+1].sum())})
        put(out, 18, **{f"m{n}_log_sell": np.log1p(tape.sell[a:k+1].sum())})
        tr = count[a:k+1].sum()
        put(out, 19, **{f"m{n}_log_count": np.log1p(tr)})
        if not np.isfinite(tr) or tr <= 0:
            continue
        buy, sell = tape.buy[a:k+1].sum(), tape.sell[a:k+1].sum()
        total = buy+sell
        if not np.isfinite(total) or total <= 0:
            continue
        ret = (tape.close[k]/opens[a]-1)*10_000
        imb = sign*(buy-sell)/total
        put(out, 13, **{f"m{n}_new_side_share": (1+imb)/2})
        qty = volume[a:k+1].sum()
        put(out, 14, **{f"m{n}_vwap_vs_close": total/qty/tape.close[k]-1 if qty > 0 else None})
        put(out, 15, **{f"m{n}_avg_qty_log": np.log1p(qty/tr)})
        put(out, 16, **{f"m{n}_largest_share": tape.max_trade[a:k+1].max()/total})
        put(out, 23 if n == 1 else 20, **{f"m{n}_imbalance": imb})
        put(out, 25, **{f"m{n}_signed_cvd_log": np.sign(imb)*np.log1p(abs(buy-sell))})
        put(out, 26, **{f"m{n}_response": ret*buy/total})
        put(out, 27, **{f"m{n}_response": -ret*sell/total})
        put(out, 28, **{f"m{n}_bps_per_100k": max(ret, 0)*100_000/buy if buy > 0 else None})
        put(out, 29, **{f"m{n}_bps_per_100k": max(-ret, 0)*100_000/sell if sell > 0 else None})
    mid = i+1+post_bps.size//2
    if i+1 < mid <= k:
        early = m1.flow_stats(sign*logret[i+1-start:mid-start], new[i+1:mid],
                              old[i+1:mid], tape.max_trade[i+1:mid])
        late = m1.flow_stats(sign*logret[mid-start:k+1-start], new[mid:k+1],
                             old[mid:k+1], tape.max_trade[mid:k+1])
        put(out, 24, post_imbalance_change=late[2]-early[2])
        put(out, 30, old_impact_decay=early[1]-late[1])
        put(out, 31, new_impact_growth=late[0]-early[0],
            concentration_change=late[3]-early[3],
            new_minus_old_impact=late[0]-late[1])


def snapshot_index(records):
    """Read market fields only. An exact anchor match is required before use."""
    index = defaultdict(dict)
    for row in records:
        side = row["side"]
        extreme, snap, delay = (int(row[k]) for k in ("candidate_ts_ms", "snapshot_ts_ms", "delay_s"))
        price = float(row["extreme_price"])
        if side not in m1.SIDES or not (price > 0 and math.isfinite(price)):
            raise ValueError("invalid snapshot identity")
        if snap != extreme+delay*1000 or delay < 0:
            raise ValueError("snapshot clock disagrees with candidate age")
        key = (side, extreme, price)
        if snap in index[key]:
            raise ValueError("duplicate snapshot timestamp")
        index[key][snap] = row["features"]
    return {key: sorted(frames.items()) for key, frames in index.items()}


def clean_micro_features(row, index):
    """Attach only certified, on-time features to the same executed extreme."""
    now = row["signal_ts_ms"]
    key = (row["side"], row["candidate_ts_ms"], row["price"])
    frames = [(t, f) for t, f in index.get(key, ()) if t <= now]
    if not frames or now-frames[-1][0] >= m1.MINUTE:
        return {}
    ts, f = frames[-1]
    prior = [frame for frame in frames[:-1] if ts-frame[0] <= 300_000]
    out = {}
    put(out, 78, snapshot_age_ms=now-ts)
    book_ok = f.get("fullmicro_book_valid") == 1
    put(out, 56, book_valid=float(book_ok))
    put(out, 57, gap_count=f.get("fullmicro_book_gap_count"))
    if book_ok:
        put(out, 44, spread_bps=f.get("fullmicro_spread_bps"))
        for side, point in (("bid", 45), ("ask", 46)):
            for level in range(1, 51):
                key = f"{side}_{level:02d}"
                dist = f.get(f"fullmicro_{key}_dist_bps")
                qty = f.get(f"fullmicro_{key}_log_qty")
                put(out, point, **{key: dist})
                put(out, 47, **{key: dist})
                put(out, 48, **{key: qty})
        for depth in (5, 10, 25, 50):
            name = f"fullmicro_book_imbalance_{depth}"
            value = f.get(name)
            put(out, 55, **{f"l{depth}_imbalance": value})
            if prior and value is not None:
                previous = prior[0][1]
                contiguous = f.get("fullmicro_book_window_valid_300s") == 1
                earlier = previous.get(name)
                if contiguous and previous.get("fullmicro_book_valid") == 1 and earlier is not None:
                    put(out, 55, **{f"l{depth}_transfer": value-earlier})
        for sec in WINDOWS:
            if f.get(f"fullmicro_book_window_valid_{sec}s") != 1:
                continue
            for point, name in ((49, "book_churn_notional"), (50, "bid_replenish_notional"),
                                (50, "ask_replenish_notional"), (51, "bid_remove_notional"),
                                (51, "ask_remove_notional"), (52, "bid_cancel_proxy_notional"),
                                (52, "ask_cancel_proxy_notional"), (53, "bid_absorption_proxy"),
                                (54, "ask_absorption_proxy")):
                field = f"{name}_{sec}s"
                put(out, point, **{field: f.get("fullmicro_"+field)})
    liq = {}
    for sec in LIQ_WINDOWS:
        if f.get(f"fullmicro_liq_stream_valid_{sec}s") != 1:
            continue
        lng = f[f"fullmicro_long_liq_notional_{sec}s"]
        sht = f[f"fullmicro_short_liq_notional_{sec}s"]
        liq[sec] = lng if row["side"] == "LOW" else sht
        put(out, 69, **{f"total_{sec}s": np.log1p(lng+sht)})
        put(out, 70, **{f"long_{sec}s": np.log1p(lng)})
        put(out, 71, **{f"short_{sec}s": np.log1p(sht)})
        put(out, 72, **{f"count_{sec}s": f[f"fullmicro_liq_count_{sec}s"]})
    if 60 in liq and 300 in liq and liq[300] > 0:
        decay = liq[60]/(liq[300]/5)
        put(out, 73, same_side_decay=decay)
        put(out, 74, decay_x_retrace=decay*row["retrace_bps"])
        flow = row["features"].get("p023_m1_imbalance")
        put(out, 75, decay_x_flow=decay*flow if flow is not None else None)
    # Scalars are carried forward by the producer. The adapter requires a
    # measured receipt age and drops stale carried values rather than backfill.
    oi_age = f.get("fullmicro_open_interest_age_ms")
    put(out, 60, oi_age_ms=oi_age)
    oi_key = "fullmicro_open_interest_sum_open_interest"
    oi = f.get(oi_key)
    if oi_age is not None and 0 <= oi_age+now-ts <= 300_000 and oi is not None and oi > 0:
        put(out, 58, open_interest_log=np.log1p(oi))
        notional = f.get("fullmicro_open_interest_sum_open_interest_value", oi*row["signal_price"])
        put(out, 115, oi_notional_log=np.log1p(notional) if notional >= 0 else None)
        for pt, p in reversed(prior):
            past = p.get(oi_key)
            age = p.get("fullmicro_open_interest_age_ms")
            if past is not None and past > 0 and age is not None and 0 <= age <= 300_000 and pt-age < ts-oi_age:
                delta = oi/past-1
                put(out, 59, oi_delta=delta)
                put(out, 61, oi_x_retrace=delta*row["retrace_bps"])
                if 60 in liq:
                    put(out, 76, oi_x_liquidation=delta*np.log1p(liq[60]))
                break
    mark_age = f.get("fullmicro_mark_price_age_ms")
    if mark_age is not None and 0 <= mark_age+now-ts <= 300_000:
        mark = f.get("fullmicro_mark_price_mark_price")
        idx = f.get("fullmicro_mark_price_index_price")
        put(out, 2, mark=mark)
        put(out, 3, index=idx)
        put(out, 62, funding=f.get("fullmicro_mark_price_funding_rate"))
        if mark is not None and idx is not None and idx > 0:
            put(out, 114, basis_bps=(mark/idx-1)*10_000)
    ticker_age = f.get("fullmicro_ticker_age_ms")
    if ticker_age is not None and 0 <= ticker_age+now-ts <= 300_000:
        put(out, 63, ticker_volume=f.get("fullmicro_ticker_base_asset_volume"))
        put(out, 64, ticker_turnover=f.get("fullmicro_ticker_quote_asset_volume"))
    ratio_age = f.get("fullmicro_account_ratio_age_ms")
    if ratio_age is not None and 0 <= ratio_age+now-ts <= 1_800_000:
        for name in ("buy_ratio", "sell_ratio", "long_short_ratio"):
            put(out, 113, **{name: f.get("fullmicro_account_"+name)})
    return out
