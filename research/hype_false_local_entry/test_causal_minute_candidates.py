from research.hype_false_local_entry.causal_minute_candidates import generate_minute_candidates, coverage


def test_causal_generation_does_not_look_ahead():
    bars = [{"ts_ms": i * 60000, "low": 100 - i, "high": 110 + i}
            for i in range(8)]
    initial = list(generate_minute_candidates(bars[:6], (3,)))
    extended = list(generate_minute_candidates(bars, (3,)))
    assert initial == [e for e in extended if e["extreme_ts_ms"] < 6 * 60000]
    assert all(e["signal_ts_ms"] > e["extreme_ts_ms"] for e in extended)


def test_coverage_is_postfactum_and_reports_missing():
    bars = [{"ts_ms": i * 60000, "low": 100 - i, "high": 110 + i}
            for i in range(8)]
    events = list(generate_minute_candidates(bars, (3,)))
    labels = [
        {"label_id": 1, "side": "LOW", "extreme_interval_start_ms": 5 * 60000},
        {"label_id": 2, "side": "LOW", "extreme_interval_start_ms": 999 * 60000},
    ]
    result = coverage(events, labels, tolerance_ms=0)
    assert result["covered"] == 1
    assert result["missing_ids"] == [2]
