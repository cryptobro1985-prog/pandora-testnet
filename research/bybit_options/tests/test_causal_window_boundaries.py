import unittest

from research.bybit_options.feature_plane_116 import _window


class CausalWindowBoundaries(unittest.TestCase):
    def test_future_events_never_enter_feature_plane(self):
        now = 1_800_000
        rows = [
            {"T": now - 30_001, "price": "1"},
            {"T": now - 30_000, "price": "2"},
            {"T": now, "price": "3"},
            {"T": now + 1, "price": "4"},
            {"T": now + 10_000, "price": "5"},
        ]
        selected = _window(rows, now, 30_000)
        self.assertEqual([x["price"] for x in selected], ["2", "3"])

    def test_empty_and_older_windows(self):
        self.assertEqual(_window([], 100_000, 30_000), [])
        self.assertEqual(_window([{"T": 1}], 100_000, 30_000), [])


if __name__ == "__main__":
    unittest.main()
