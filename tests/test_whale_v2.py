import unittest

from whale_v2 import (
    EligibilityTracker,
    WL2_POLICY,
    evaluate_position,
    initial_position_state,
)


class WhaleLiquidationV2Tests(unittest.TestCase):
    def candidate(self, distance):
        return {
            "symbol": "TEST",
            "side": -1,
            "cluster_id": "cluster-1",
            "distance_pct": distance,
            "dynamic_entry_distance_pct": 1.2,
            "score": 93.0,
            "whale_rank_score": 91.0,
            "r15": -0.0010,
            "r60": -0.0020,
            "r300": -0.0040,
            "r900": -0.0070,
            "flow_imbalance": -0.40,
            "cvd_1m": -1000.0,
            "orderbook_imbalance": -0.25,
            "spread_bps": 5.0,
            "micro_confirmations": 5,
            "volume_burst_ratio": 4.0,
            "volume_rate_z": 3.0,
            "liquidation_flow_to_depth": 2.0,
            "liquidation_price": 99.0,
            "victim_side": "long",
        }

    def test_entry_requires_contracting_liquidation_distance(self):
        tracker = EligibilityTracker()
        q1, _ = tracker.observe([self.candidate(0.80)], 1)
        q2, _ = tracker.observe([self.candidate(0.74)], 2)
        q3, rejected = tracker.observe([self.candidate(0.68)], 3)
        self.assertEqual(q1, [])
        self.assertEqual(q2, [])
        self.assertEqual(len(q3), 1)
        self.assertEqual(q3[0]["wl2_policy"], WL2_POLICY)
        self.assertGreaterEqual(q3[0]["wl2_distance_contraction_pct"], 0.10)
        self.assertNotIn("distance_not_contracting", rejected)

    def test_pre_liquidation_distance_invalidation(self):
        candidate = self.candidate(0.30)
        features = initial_position_state(candidate, 100.0, "2026-10-25T10:00:00+00:00")
        position = {
            "entry": 100.0,
            "side": -1,
            "leverage": 25.0,
            "features": features,
        }
        reason = None
        # Liquidation is at 99.0. The market runs away from the target and the
        # remaining distance widens past the dynamic invalidation level for
        # three consecutive evaluations.
        for i, price in enumerate((100.4, 100.7, 101.0, 101.3), 1):
            position, reason = evaluate_position(
                position,
                price,
                f"2026-10-25T10:00:{i:02d}+00:00",
                flow=0.2,
                r15=0.001,
                r60=0.002,
            )
        self.assertEqual(reason, "wl2_pre_liq_distance_invalidation")

    def test_post_liquidation_exit_keeps_old_best_extreme(self):
        candidate = self.candidate(0.30)
        features = initial_position_state(candidate, 100.0, "2026-10-25T10:00:00+00:00")
        position = {
            "entry": 100.0,
            "side": -1,
            "leverage": 25.0,
            "features": features,
        }

        # Hit the long victim's liquidation level.
        position, reason = evaluate_position(
            position,
            98.95,
            "2026-10-25T10:01:00+00:00",
            flow=-0.5,
            r15=-0.002,
            r60=-0.003,
        )
        self.assertIsNone(reason)
        self.assertIsNotNone(position["features"]["wl2_liquidation_level_reached_at"])

        # Extend lower, spend enough samples that the best low is no longer
        # "recent", then bounce with confirmed weakening.
        path = [
            98.8, 98.6, 98.4, 98.2, 98.0,
            98.05, 98.04, 98.03, 98.02, 98.01,
            98.00, 98.05, 98.12, 98.20,
        ]
        reason = None
        for i, price in enumerate(path, 1):
            position, reason = evaluate_position(
                position,
                price,
                f"2026-10-25T10:01:{i:02d}+00:00",
                flow=0.1,
                r15=0.0005,
                r60=-0.001,
            )
        self.assertEqual(reason, "wl2_post_liq_local_extreme_weakening")
        self.assertAlmostEqual(position["features"]["wl2_post_liq_best_price"], 98.0)


if __name__ == "__main__":
    unittest.main()
