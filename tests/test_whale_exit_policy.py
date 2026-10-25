import unittest

import operator_cleanup  # noqa: F401 - import is a CI syntax/smoke check
from risk import evaluate_exit


class WhaleExitPolicyTests(unittest.TestCase):
    def _short_local_pullback(self, features):
        # A short that has already made a clear favorable move and is now bouncing
        # enough to satisfy the generic local-extreme exit.
        return {
            "entry": 100.0,
            "side": -1,
            "leverage": 25.0,
            "peak": 98.0,
            "history": [100.0, 99.5, 99.0, 98.5, 98.0, 98.2, 98.4],
            "features": features,
        }

    def test_whale_exit_is_blocked_until_liquidation_target_is_touched(self):
        features={
            "engine": "whale_liquidation_cluster_v4",
            "victim_side": "long",
            "liquidation_price": 95.0,
            "dynamic_entry_distance_pct": 0.75,
        }
        evaluated,reason=evaluate_exit(
            self._short_local_pullback(features),
            98.6,
            "2026-10-25T09:00:00+00:00",
        )
        self.assertIsNone(reason)
        self.assertTrue(evaluated["last_exit_check"]["pre_liquidation_hold"])
        self.assertGreater(evaluated["last_exit_check"]["remaining_to_liquidation_pct"],0.75)
        self.assertFalse(evaluated["last_exit_check"]["local_extreme_exit"])

    def test_whale_local_exit_restarts_fresh_after_liquidation_latch(self):
        features={
            "engine": "whale_liquidation_cluster_v4",
            "victim_side": "long",
            "liquidation_price": 95.0,
            "liquidation_level_reached_at": "2026-10-25T09:00:00+00:00",
        }
        evaluated,reason=evaluate_exit(
            self._short_local_pullback(features),
            98.6,
            "2026-10-25T09:01:00+00:00",
        )
        self.assertIsNone(reason)
        self.assertTrue(evaluated["post_liq_risk_reset_done"])
        self.assertEqual(evaluated["history"],[98.6])
        self.assertGreaterEqual(evaluated["local_search_min_samples"],15)
        self.assertFalse(evaluated["last_exit_check"]["local_extreme_exit"])

        # Build a fresh post-liquidation path: first a new local low, then a
        # confirmed bounce. Only this new path is eligible for exit.
        prices=[98.4,98.2,98.0,97.8,97.6,97.5,97.4,97.3,97.2,97.1,97.0,97.1,97.2,97.4,97.6]
        reason=None
        for i,price in enumerate(prices,1):
            evaluated,reason=evaluate_exit(
                evaluated,price,f"2026-10-25T09:01:{i:02d}+00:00"
            )
        self.assertEqual(reason,"local_extreme_weakening")
        self.assertFalse(evaluated["last_exit_check"]["pre_liquidation_hold"])
        self.assertTrue(evaluated["last_exit_check"]["local_extreme_exit"])


if __name__ == "__main__":
    unittest.main()
