import unittest
from types import SimpleNamespace

from research.hype_false_local_entry.time_to_confirmation_live import (
    _same_side_liquidation_exhaustion,
    _book_quality_ok,
)


class TimeToConfirmationLiveTest(unittest.TestCase):
    def test_liquidation_decay_is_positive_when_recent_pressure_dies(self):
        state = SimpleNamespace(liqs=[
            {"ts_ms": 1_000, "side": 1, "notional": 100.0},
            {"ts_ms": 50_000, "side": 1, "notional": 100.0},
        ])
        score = _same_side_liquidation_exhaustion("LOW", 300_000, state, 300)
        self.assertGreater(score, 0.0)

    def test_crossed_book_fails_quality(self):
        state = SimpleNamespace(book_bids={101.0: 1.0}, book_asks={100.0: 1.0})
        self.assertFalse(_book_quality_ok(state))

    def test_normal_book_passes_quality(self):
        state = SimpleNamespace(book_bids={99.0: 1.0}, book_asks={100.0: 1.0})
        self.assertTrue(_book_quality_ok(state))


if __name__ == "__main__":
    unittest.main()
