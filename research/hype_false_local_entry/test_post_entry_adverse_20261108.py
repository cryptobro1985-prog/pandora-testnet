"""Regression: adverse extension begins AFTER signal-bar close."""
from types import SimpleNamespace
from research.hype_false_local_entry.first_flip_path_audit import score_first_flips


def test_signal_candle_extreme_is_not_post_entry_adverse():
    labels = [
        dict(label_id="l", side="LOW", extreme_interval_start_ms=0, extreme_price=100),
        dict(label_id="h", side="HIGH", extreme_interval_start_ms=180000, extreme_price=110),
    ]
    bars = [
        dict(ts_ms=0, bar_end_ms=60000, low=90, high=105),
        dict(ts_ms=60000, bar_end_ms=120000, low=80, high=106),
        dict(ts_ms=120000, bar_end_ms=180000, low=100, high=110),
    ]
    flip = SimpleNamespace(ts_ms=120000, side="LOW", stage="HARD_CONFIRMED", close=105)
    scored = score_first_flips(bars, labels, [flip])
    hit = scored["matched"][0]
    assert hit["detected"]
    assert hit["adverse_extension_bps"] == 0.0
    assert hit["entry_distance_bps"] == 500.0
