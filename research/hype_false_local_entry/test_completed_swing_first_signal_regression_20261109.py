"""Regression: completed-swing first-signal accounting, no live orders."""
from types import SimpleNamespace
from research.hype_false_local_entry.first_flip_path_audit import score_first_flips


def _local(t, side, price):
    return {"extreme_interval_start_ms": t, "side": side, "extreme_price": price,
            "label_id": str(t)}


def _flip(t, side, price=100):
    return SimpleNamespace(ts_ms=t, side=side, close=price,
                           stage="HARD_CONFIRMED", core_flip=True)


def test_wrong_first_cannot_be_rescued_by_later_correct_flip():
    labels = [_local(0, "LOW", 100), _local(600000, "HIGH", 110),
              _local(1200000, "LOW", 95)]
    result = score_first_flips([], labels,
                               [_flip(60000, "HIGH"), _flip(120000, "LOW"),
                                _flip(660000, "HIGH")])
    assert result["complete_swings"] == 2
    assert result["completed_swing_true_first"] == 1
    assert result["completed_swing_wrong_first"] == 1
    assert result["completed_swing_missed"] == 1
    assert result["completed_swing_first_signal_precision"] == 1 / 3
    assert result["completed_swing_false_first"] == 2


def test_terminal_hit_does_not_raise_completed_swing_precision():
    labels = [_local(0, "LOW", 100), _local(600000, "HIGH", 110),
              _local(1200000, "LOW", 95)]
    result = score_first_flips([], labels,
                               [_flip(60000, "LOW"), _flip(660000, "HIGH"),
                                _flip(1260000, "LOW")])
    assert result["detected_locals"] == 3
    assert result["completed_swing_true_first"] == 2
    assert result["terminal_local_hit_excluded_from_completed_swing_precision"]
    assert result["completed_swing_first_signal_precision"] == 2 / 3
    assert result["completed_swing_recall"] == 1.0


def test_missing_internal_local_counts_as_miss_not_reduced_denominator():
    labels = [_local(i * 600000, "LOW" if i % 2 == 0 else "HIGH",
                     100 if i % 2 == 0 else 110) for i in range(5)]
    result = score_first_flips([], labels, [_flip(60000, "LOW")])
    assert result["finalized_locals"] == 5
    assert result["complete_swings"] == 4
    assert result["completed_swing_true_first"] == 1
    assert result["completed_swing_missed"] == 3
    assert result["completed_swing_missed_rate"] == 0.75
