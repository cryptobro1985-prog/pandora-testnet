import gzip
import json

import numpy as np
import pytest

from research.hype_local_only.full_history_features import (
    AUX_LAG_MS, HOUR, MINUTE, SOURCE_FILES, FullHistoryFeatures,
)

BASE = 1_791_072_000_000


def minute(i):
    start = BASE + i * MINUTE
    price = 100 + i / 100
    return {"start_ms": start, "bar_end_ms": start + MINUTE, "ts_ms": start + MINUTE,
            "open": price, "high": price + .1, "low": price - .1, "close": price + .02,
            "high_ts_ms": start + 40_000, "low_ts_ms": start + 10_000,
            "quantity": 10., "volume": 10., "turnover": 1000., "buy_notional": 600.,
            "sell_notional": 400., "buy_count": 6, "sell_count": 4, "trade_count": 10,
            "max_trade_notional": 200., "flow_observed": True, "gap": False}


def auxiliary(n):
    bars = [{"ts_ms": BASE + i * MINUTE, "open": 100 + i / 100,
             "high": 101 + i / 100, "low": 99 + i / 100, "close": 100.5 + i / 100}
            for i in range(n)]
    return {"mark": bars, "index": [dict(row, close=row["close"] + 1) for row in bars],
            "oi": [{"ts_ms": BASE + i * MINUTE, "open_interest": 1000 + i}
                   for i in range(0, n, 5)],
            "funding": [{"ts_ms": BASE, "funding_rate": .0001}]}


def write_sources(root, minutes, aux):
    sources = {"minutes": minutes, **aux}
    for name, rows in sources.items():
        path = root / "artifacts" / SOURCE_FILES[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")


def test_exact_completed_bar_and_one_second_auxiliary_availability():
    history = FullHistoryFeatures.from_records([minute(i) for i in range(4)], auxiliary(4))
    end = BASE + MINUTE
    assert history.at(end - 1) == {}
    before = history.at(end + AUX_LAG_MS - 1)
    assert before["m1__close"] == pytest.approx(100.02)
    assert before["mark__observed"] == 0
    assert np.isnan(before["mark__price_rel"])
    after = history.at(end + AUX_LAG_MS)
    assert after["mark__observed"] == 1
    assert after["mark__price_rel"] == pytest.approx(100.5 / 100.02 - 1)
    clocks = history.source_clocks(end + AUX_LAG_MS)
    assert clocks["mark"]["source_ts_ms"] == BASE
    assert clocks["mark"]["source_end_ms"] == end
    assert clocks["mark"]["assumed_available_at_ms"] == end + AUX_LAG_MS
    assert clocks["mark"]["received_ts_ms"] is None
    assert clocks["mark"]["historical_receipt_unknown"] is True


def test_oi_funding_source_lag_excludes_exact_boundary_new_values():
    history = FullHistoryFeatures.from_records([minute(i) for i in range(10)], auxiliary(10))
    boundary = BASE + 5 * MINUTE
    before = history.at(boundary)
    after = history.at(boundary + AUX_LAG_MS)
    assert before["oi__log"] == pytest.approx(np.log1p(1000))
    assert after["oi__log"] == pytest.approx(np.log1p(1005))
    assert after["oi__change_5m"] == pytest.approx(.005)
    assert before["funding__rate"] == pytest.approx(.0001)
    assert after["oi__source_time_only"] == 1
    assert after["oi__received_clock_known"] == 0


def test_future_sources_cannot_change_prior_features():
    minutes = [minute(i) for i in range(125)]
    aux = auxiliary(125)
    before = FullHistoryFeatures.from_records(minutes, aux)
    altered = [dict(row) for row in minutes]
    for row in altered[70:]:
        row.update(open=900., close=999., high=1000., low=800., buy_notional=10**12)
    future_aux = {name: [dict(row) for row in rows] for name, rows in aux.items()}
    for name in ("mark", "index"):
        for row in future_aux[name][70:]:
            row.update(open=900., close=999., high=1000., low=800.)
    after = FullHistoryFeatures.from_records(altered, future_aux)
    assert before.names == after.names
    np.testing.assert_allclose(before.features[:70], after.features[:70], equal_nan=True)
    prefix = FullHistoryFeatures.from_records(minutes[:70], {
        name: [row for row in rows if row["ts_ms"] < BASE + 70 * MINUTE] for name, rows in aux.items()})
    np.testing.assert_allclose(before.features[:70], prefix.features, equal_nan=True)


def test_missing_minute_invalidates_windows_and_its_hour():
    rows = [minute(i) for i in range(121) if i != 10]
    history = FullHistoryFeatures.from_records(rows)
    result = history.at(BASE + 12 * MINUTE)
    assert result["w1m__observed"] == 1
    assert result["w3m__observed"] == 0
    assert np.isnan(result["w3m__return_bps"])
    assert history.at(BASE + HOUR)["h1__observed"] == 0
    assert history.at(BASE + 2 * HOUR)["h1__observed"] == 1
    assert history.coverage["missing_minute_slots"] == 1


def test_missing_flow_stays_nan_instead_of_zero():
    rows = [minute(i) for i in range(6)]
    rows[3]["flow_observed"] = False
    history = FullHistoryFeatures.from_records(rows)
    result = history.at(BASE + 4 * MINUTE)
    assert result["m1__observed"] == 1
    assert result["m1__flow_observed"] == 0
    assert np.isnan(result["m1__buy_notional"])
    assert result["w3m__observed"] == 1
    assert result["w3m__flow_observed"] == 0
    assert np.isnan(result["w3m__flow_imbalance"])
    assert result["mark__observed"] == 0
    assert np.isnan(result["mark__price_rel"])


def test_flow_concentration_and_window_warmup():
    history = FullHistoryFeatures.from_records([minute(i) for i in range(361)])
    result = history.at(BASE + 3 * MINUTE)
    assert result["w3m__flow_imbalance"] == pytest.approx(.2)
    assert result["w3m__count_imbalance"] == pytest.approx(.2)
    assert result["w3m__max_trade_share"] == pytest.approx(200 / 3000)
    assert result["m1__high_elapsed_fraction"] == pytest.approx(2 / 3)
    assert result["m1__high_before_low"] == 0
    assert result["w360m__observed"] == 0
    assert history.at(BASE + 360 * MINUTE)["w360m__observed"] == 1
    assert history.features.dtype == np.float32
    assert history.ends.dtype == np.int64
    assert len(history.names) <= 200


def test_hour_context_appears_only_after_complete_hour():
    rows = [minute(i) for i in range(361)]
    history = FullHistoryFeatures.from_records(rows)
    assert history.at(BASE + HOUR - 1)["h1__observed"] == 0
    result = history.at(BASE + HOUR)
    assert result["h1__observed"] == 1
    assert result["h1__return_bps"] == pytest.approx((rows[59]["close"] / rows[0]["open"] - 1) * 10_000)
    assert np.isnan(result["h1__return_3h_bps"])
    result = history.at(BASE + 3 * HOUR)
    assert np.isfinite(result["h1__return_3h_bps"])
    assert np.isnan(result["h1__return_6h_bps"])


def test_stale_channels_have_observation_age_but_no_measurement():
    aux = auxiliary(1)
    history = FullHistoryFeatures.from_records([minute(i) for i in range(1000)], aux)
    result = history.at(BASE + 16 * MINUTE)
    assert result["mark__observed"] == 1
    assert result["mark__stale"] == 1
    assert np.isnan(result["mark__price_rel"])
    assert result["oi__source_age_s"] == 960
    assert result["oi__stale"] == 1
    assert np.isnan(result["oi__log"])
    result = history.at(BASE + 13 * HOUR)
    assert result["funding__stale"] == 1
    assert np.isnan(result["funding__rate"])
    late = history.at(BASE + 1002 * MINUTE)
    assert late["m1__observed"] == 0
    assert np.isnan(late["m1__close"])


def test_known_future_receive_cannot_enter_auxiliary_features():
    aux = auxiliary(3)
    for row in aux["mark"]:
        row["received_ts_ms"] = row["ts_ms"] + 3 * MINUTE
    history = FullHistoryFeatures.from_records([minute(i) for i in range(5)], aux)
    assert history.at(BASE + 2 * MINUTE)["mark__observed"] == 0
    result = history.at(BASE + 3 * MINUTE)
    assert result["mark__observed"] == 1
    assert result["mark__received_clock_known"] == 1
    assert result["mark__source_time_only"] == 0
    assert history.source_clocks(BASE + 3 * MINUTE)["mark"]["received_ts_ms"] == BASE + 3 * MINUTE


def test_invalid_or_future_received_minute_price_cannot_enter_auxiliary_ratios():
    rows = [minute(i) for i in range(4)]
    rows[2]["received_ts_ms"] = BASE + 10 * MINUTE
    rows[2].update(open=900., high=1001., low=899., close=1000.)
    history = FullHistoryFeatures.from_records(rows, auxiliary(4))
    index = 2
    for key in ("m1__close", "mark__price_rel", "index__price_rel", "oi__notional_log"):
        assert np.isnan(history.features[index, history.names.index(key)])
    assert history.at(BASE + 3 * MINUTE)["m1__close"] == pytest.approx(rows[1]["close"])


def test_known_delayed_minute_becomes_available_at_its_actual_receipt():
    rows = [minute(i) for i in range(65)]
    for row in rows:
        row["received_ts_ms"] = row["bar_end_ms"] + 1000
    history = FullHistoryFeatures.from_records(rows, auxiliary(65))
    end = BASE + MINUTE
    assert history.at(end) == {}
    assert history.at(end + 999) == {}
    for delta in (1000, 2000):
        result = history.at(end + delta)
        assert result["m1__close"] == pytest.approx(rows[0]["close"])
        assert result["m1__received_clock_known"] == 1
        assert result["m1__source_time_only"] == 0
        clocks = history.source_clocks(end + delta)["minutes"]
        assert clocks["received_ts_ms"] == end + 1000
        assert clocks["assumed_available_at_ms"] == end + 1000
    before = history.at(BASE + 3 * MINUTE)
    assert before["m1__close"] == pytest.approx(rows[1]["close"])
    assert before["w3m__observed"] == 0
    after = history.at(BASE + 3 * MINUTE + 1000)
    assert after["m1__close"] == pytest.approx(rows[2]["close"])
    assert after["w3m__observed"] == 1
    assert after["w3m__flow_imbalance"] == pytest.approx(.2)
    assert history.at(BASE + HOUR)["h1__observed"] == 0
    assert history.at(BASE + HOUR + 1000)["h1__observed"] == 1


def test_cache_requires_all_source_hashes_and_preserves_raw_keys(tmp_path):
    rows, aux = [minute(i) for i in range(65)], auxiliary(65)
    rows[0]["raw_metadata_test"] = "preserved"
    write_sources(tmp_path, rows, aux)
    first = FullHistoryFeatures(tmp_path)
    second = FullHistoryFeatures(tmp_path)
    assert first.cache_hit is False and second.cache_hit is True
    assert second.minutes[0]["raw_metadata_test"] == "preserved"
    np.testing.assert_allclose(first.features, second.features, equal_nan=True)
    aux["funding"][0]["funding_rate"] = .0002
    write_sources(tmp_path, rows, aux)
    third = FullHistoryFeatures(tmp_path)
    assert third.cache_hit is False
    assert third.source_hashes != second.source_hashes
    assert third.at(BASE + MINUTE)["funding__rate"] == pytest.approx(.0002)
    report = json.loads((tmp_path / "artifacts/full_history_research/FEATURE_COVERAGE.json").read_text())
    assert report["feature_matrix"]["columns"] <= 200
    assert report["time_assumptions"]["historical_receipt_latency"].startswith("unknown")
