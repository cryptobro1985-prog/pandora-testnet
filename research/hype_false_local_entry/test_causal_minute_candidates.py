from research.hype_false_local_entry.causal_minute_candidates import (
    coverage,
    generate_minute_candidates,
)


def test_causal_generation_does_not_look_ahead():
    bars = [
        {"ts_ms": i * 60000, "low": 100 - i, "high": 110 + i}
        for i in range(8)
    ]
    initial = list(generate_minute_candidates(bars[:6], (3,)))
    extended = list(generate_minute_candidates(bars, (3,)))
    assert initial == [e for e in extended if e["extreme_ts_ms"] < 6 * 60000]
    assert all(e["signal_ts_ms"] > e["extreme_ts_ms"] for e in extended)


def test_compact_bar_end_is_signal_time_without_extra_minute():
    bars = []
    for i in range(4):
        start = i * 60000
        end = start + 60000
        bars.append(
            {
                "start_ms": start,
                "bar_end_ms": end,
                "ts_ms": end,
                "interval_ms": 60000,
                "low": 100 - i,
                "high": 110 + i,
                "low_ts_ms": start + 10000,
                "high_ts_ms": start + 50000,
            }
        )

    events = list(generate_minute_candidates(bars, (3,)))
    low = next(e for e in events if e["side"] == "LOW")
    high = next(e for e in events if e["side"] == "HIGH")

    assert low["signal_ts_ms"] == bars[-1]["bar_end_ms"]
    assert high["signal_ts_ms"] == bars[-1]["bar_end_ms"]
    assert low["extreme_ts_ms"] == bars[-1]["low_ts_ms"]
    assert high["extreme_ts_ms"] == bars[-1]["high_ts_ms"]


def test_multiple_lookback_hits_are_deduplicated_per_side_and_bar():
    bars = [
        {"ts_ms": i * 60000, "low": 100 - i, "high": 110 + i}
        for i in range(8)
    ]
    events = list(generate_minute_candidates(bars, (2, 3, 5)))
    tail = [e for e in events if e["extreme_ts_ms"] == 7 * 60000]

    assert len([e for e in tail if e["side"] == "LOW"]) == 1
    assert len([e for e in tail if e["side"] == "HIGH"]) == 1
    assert next(e for e in tail if e["side"] == "LOW")["lookbacks_m"] == [2, 3, 5]
    assert next(e for e in tail if e["side"] == "HIGH")["lookbacks_m"] == [2, 3, 5]


def test_coverage_is_postfactum_and_reports_missing():
    bars = [
        {"ts_ms": i * 60000, "low": 100 - i, "high": 110 + i}
        for i in range(8)
    ]
    events = list(generate_minute_candidates(bars, (3,)))
    labels = [
        {"label_id": 1, "side": "LOW", "extreme_interval_start_ms": 5 * 60000},
        {"label_id": 2, "side": "LOW", "extreme_interval_start_ms": 999 * 60000},
    ]
    result = coverage(events, labels, tolerance_ms=0)
    assert result["covered"] == 1
    assert result["missing_ids"] == [2]
