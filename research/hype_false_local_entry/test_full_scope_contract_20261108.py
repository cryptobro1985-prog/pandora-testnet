"""Full-scope regression contracts; synthetic data, no historical performance claims."""
from dataclasses import dataclass

from research.hype_false_local_entry.audit_dense_coverage import evaluate
from research.hype_false_local_entry.dense_causal_reachability import dense_completed_m1_candidates
from research.hype_false_local_entry.first_flip_path_audit import score_first_flips


@dataclass(frozen=True)
class Flip:
    ts_ms: int
    side: str
    stage: str
    close: float
    core_flip: bool = True


def _bar(i, low, high, close):
    return {"ts_ms": i * 60000, "bar_end_ms": (i + 1) * 60000,
            "low": low, "high": high, "close": close}


def _label(i, side, price):
    return {"label_id": str(i), "side": side,
            "extreme_interval_start_ms": i * 60000,
            "extreme_interval_end_ms": (i + 1) * 60000,
            "extreme_price": price, "reference_finalized": True}


def test_dense_candidate_reachability_not_signal_recall():
    bars = [_bar(0, 100, 110, 105), _bar(1, 101, 109, 106),
            _bar(2, 102, 112, 110)]
    labels = [_label(0, "LOW", 100), _label(2, "HIGH", 112)]
    candidates = list(dense_completed_m1_candidates(bars))
    reach = evaluate(candidates, labels, tolerance_ms=0)
    assert reach["finalized"] == 2
    assert reach["covered"] == 2
    assert all(e["entry_signal"] is False for e in candidates)
    signals = score_first_flips(bars, labels, [])
    assert signals["detected_locals"] == 0
    assert signals["missed_locals"] == 2
    assert signals["complete_swings"] == 1


def test_wrong_first_cannot_be_repaired_and_duplicate_is_false():
    bars = [_bar(0, 100, 110, 105), _bar(1, 101, 111, 107),
            _bar(2, 103, 113, 110), _bar(3, 104, 114, 111)]
    labels = [_label(0, "LOW", 100), _label(3, "HIGH", 114)]
    flips = [Flip(60000, "HIGH", "HARD_CONFIRMED", 105),
             Flip(120000, "LOW", "HARD_CONFIRMED", 107)]
    result = score_first_flips(bars, labels, flips)
    assert result["detected_locals"] == 0
    assert result["false_first"] == 2
    assert result["first_signal_precision"] == 0
    assert result["missed_locals"] == 2


def test_full_internal_denominator_even_when_candidate_space_incomplete():
    labels = [_label(i, "LOW" if i % 2 == 0 else "HIGH",
                     100 + i) for i in range(122)]
    result = score_first_flips([], labels, [])
    assert result["finalized_locals"] == 122
    assert result["complete_swings"] == 121
    assert result["missed_locals"] == 122
    assert result["missed_local_rate"] == 1.0
    assert result["first_signal_precision"] is None
