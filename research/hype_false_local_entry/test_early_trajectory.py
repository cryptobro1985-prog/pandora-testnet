import math
import unittest

import numpy as np

from research.hype_false_local_entry import early_trajectory_features as f
from research.hype_false_local_entry import replay_early_trajectory as replay


def bars(count=398):
    rows = []
    for i in range(count):
        start = i * f.MINUTE
        rows.append(dict(start_ms=start, bar_end_ms=start + f.MINUTE, ts_ms=start + f.MINUTE,
                         open=100, high=100.4, low=99.8, close=100,
                         high_ts_ms=start + 20_000, low_ts_ms=start + 25_000,
                         buy_notional=1000, sell_notional=2000, max_trade_notional=500))
    rows[360].update(low=99, close=99.5)
    return rows


def low_at(i):
    return f"LOW-{i * f.MINUTE + 25_000}"


def label(label_id, side, index, price):
    return dict(label_id=label_id, side=side, extreme_price=price,
                extreme_interval_start_ms=index * f.MINUTE,
                extreme_interval_end_ms=(index + 1) * f.MINUTE, reference_finalized=True)


class EarlyTrajectoryTest(unittest.TestCase):
    def test_full_minute_timestamp_and_prefix_invariance(self):
        rows = bars()
        rows[368]["strict_label_id"] = 80
        rows[369]["feature_110"] = 9000
        rows[380].update(low=90, close=95)
        full = list(f.trajectories(f.tape_from_rows(rows)))
        cutoff = rows[375]["bar_end_ms"]
        prefix = list(f.trajectories(f.tape_from_rows(
            {k: v for k, v in row.items() if k not in {"strict_label_id", "feature_110"}}
            for row in rows[:376]
        )))
        np.testing.assert_equal(prefix, [r for r in full if r["signal_ts_ms"] <= cutoff])
        low = next(x for x in full if x["candidate_id"] == low_at(360))
        self.assertEqual(low["age_s"], 60)
        self.assertEqual(low["signal_ts_ms"], rows[361]["bar_end_ms"])

    def test_same_side_extension_wins_at_decision_bar(self):
        rows = bars()
        rows[361].update(low=98, close=98.5)
        rows[365].update(low=98)  # Equal lows do not reset the running candidate.
        signals = list(f.trajectories(f.tape_from_rows(rows)))
        self.assertNotIn(low_at(360), {r["candidate_id"] for r in signals})
        self.assertNotIn(low_at(365), {r["candidate_id"] for r in signals})
        self.assertTrue(any(r["candidate_id"] == low_at(361) and r["age_s"] == 600
                            for r in signals))

    def test_higher_high_replaces_only_high(self):
        rows = bars()
        rows[360]["high"] = 101
        rows[361]["high"] = 102
        signals = list(f.trajectories(f.tape_from_rows(rows)))
        ids = {r["candidate_id"] for r in signals}
        self.assertNotIn(f"HIGH-{360 * f.MINUTE + 20_000}", ids)
        self.assertIn(f"HIGH-{361 * f.MINUTE + 20_000}", ids)
        self.assertIn(low_at(360), ids)

    def test_unobserved_flow_is_missing_even_if_values_exist(self):
        rows = bars()
        rows[361]["flow_observed"] = False
        rows[361]["close"] = 99.9
        signals = list(f.trajectories(f.tape_from_rows(rows)))
        at_3m = next(r for r in signals if r["candidate_id"] == low_at(360) and r["age_s"] == 180)
        self.assertTrue(math.isnan(at_3m["efficiency_slope"]))
        self.assertFalse(at_3m["old_side_failed_extension"])

    def test_gap_resets_candidate_and_reference_warmup(self):
        rows = bars()
        rows[364]["low"] = 95
        del rows[361]
        self.assertEqual(list(f.trajectories(f.tape_from_rows(rows))), [])

    def test_false_first_beats_later_true_and_uses_terminal_price(self):
        rows = bars()
        rows[375].update(low=98)
        tape = f.tape_from_rows(rows)
        labels = [label(1, "HIGH", 360, 100.4), label(2, "LOW", 375, 98),
                  label(3, "HIGH", 390, 100.4)]
        earlier_false = dict(side="LOW", candidate_id=low_at(362), age_s=180, price=99.5,
                             candidate_ts_ms=362 * f.MINUTE + 25_000,
                             signal_ts_ms=366 * f.MINUTE, signal_price=100.0, retrace_bps=50.0)
        later_true = dict(side="LOW", candidate_id=low_at(375), age_s=180, price=98,
                          candidate_ts_ms=375 * f.MINUTE + 25_000,
                          signal_ts_ms=379 * f.MINUTE, signal_price=98.5, retrace_bps=51.0)
        scope = replay.scoring_scope(tape, labels)
        result = replay.evaluate_side(tape, labels, "LOW", [later_true, earlier_false], scope)
        self.assertEqual((result["episodes"], result["true_first"], result["false_first"]), (1, 0, 1))
        self.assertAlmostEqual(result["false_candidate_continuation_bps"]["median"],
                               (1 - 98 / 99.5) * 10_000)
        late = dict(later_true, signal_ts_ms=390 * f.MINUTE)
        result = replay.evaluate_side(tape, labels, "LOW", [late], scope)
        self.assertEqual(result["accepted_first"], 0)

    def test_rejects_start_stamped_completed_bar(self):
        rows = bars()
        rows[0]["ts_ms"] = rows[0]["start_ms"]
        with self.assertRaisesRegex(ValueError, "completed M1"):
            f.tape_from_rows(rows)


if __name__ == "__main__":
    unittest.main()
