"""Regression: terminal local must not inflate completed-swing precision."""
from types import SimpleNamespace

from research.hype_false_local_entry.first_flip_path_audit import score_first_flips


def _local(ts, side, price):
    return {"extreme_interval_start_ms": ts, "side": side, "extreme_price": price}


def _flip(ts, side, price):
    return SimpleNamespace(ts_ms=ts, side=side, close=price, stage="HARD_CONFIRMED")


def test_terminal_hit_is_not_completed_swing_true_first():
    labels = [_local(0, "LOW", 100), _local(120000, "HIGH", 110)]
    flips = [_flip(60000, "LOW", 101), _flip(180000, "HIGH", 109)]
    result = score_first_flips([], labels, flips)
    assert result["finalized_locals"] == 2
    assert result["complete_swings"] == 1
    assert result["detected_locals"] == 2
    assert result["completed_swing_true_first"] == 1
    assert result["completed_swing_first_signal_precision"] == 0.5
    assert result["completed_swing_false_first"] == 1
    assert result["terminal_local_hit_excluded_from_completed_swing_precision"] is True


def test_wrong_first_then_correct_cannot_repair_first_signal():
    labels = [_local(0, "LOW", 100), _local(180000, "HIGH", 110)]
    flips = [_flip(60000, "HIGH", 101), _flip(120000, "LOW", 102)]
    result = score_first_flips([], labels, flips)
    assert result["completed_swing_true_first"] == 0
    assert result["completed_swing_wrong_first"] == 1
    assert result["completed_swing_false_first"] == 2
    assert result["completed_swing_first_signal_precision"] == 0.0
