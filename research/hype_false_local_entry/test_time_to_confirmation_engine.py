import unittest

from research.hype_false_local_entry.time_to_confirmation_engine import (
    ConfirmState,
    ConfirmationEvidence,
    TimeToConfirmationEngine,
    confirmation_metrics,
)


def ev(**kw):
    base = dict(
        ts_ms=60_000,
        side="LOW",
        extreme_ts_ms=0,
        extreme_price=100.0,
        price=100.40,
        reversal_return_bps=40.0,
        flow_efficiency=0.012,
        opposing_impact_efficiency=-0.004,
        same_side_liq_decay=0.9,
        book_recovery=0.9,
        oi_price_agreement=0.5,
        no_new_extreme=True,
        data_quality_ok=True,
    )
    base.update(kw)
    return ConfirmationEvidence(**base)


class TimeToConfirmationEngineTest(unittest.TestCase):
    def test_60s_strong_low_confirms_long(self):
        d = TimeToConfirmationEngine().evaluate(ev())
        self.assertEqual(d.state, ConfirmState.CONFIRMED)
        self.assertTrue(d.enter)
        self.assertEqual(d.target_side, "LONG")
        self.assertEqual(d.checkpoint_s, 60)

    def test_60s_strong_high_confirms_short(self):
        d = TimeToConfirmationEngine().evaluate(ev(
            side="HIGH", extreme_price=100.0, price=99.6,
        ))
        self.assertEqual(d.state, ConfirmState.CONFIRMED)
        self.assertEqual(d.target_side, "SHORT")

    def test_before_30s_never_enters(self):
        d = TimeToConfirmationEngine().evaluate(ev(ts_ms=20_000))
        self.assertEqual(d.state, ConfirmState.CANDIDATE)
        self.assertFalse(d.enter)

    def test_new_low_invalidates_old_low(self):
        e = TimeToConfirmationEngine()
        e.start_or_extend("LOW", 0, 100.0)
        d = e.evaluate(ev(ts_ms=60_000, price=99.9, no_new_extreme=False))
        self.assertEqual(d.state, ConfirmState.INVALIDATED)
        self.assertFalse(d.enter)

    def test_bad_quality_blocks_entry(self):
        d = TimeToConfirmationEngine().evaluate(ev(data_quality_ok=False))
        self.assertEqual(d.state, ConfirmState.WATCH)
        self.assertFalse(d.enter)

    def test_weak_evidence_stays_candidate(self):
        d = TimeToConfirmationEngine().evaluate(ev(
            reversal_return_bps=2.0,
            flow_efficiency=-0.005,
            opposing_impact_efficiency=0.02,
            same_side_liq_decay=-0.5,
            book_recovery=-0.5,
            oi_price_agreement=-0.5,
        ))
        self.assertFalse(d.enter)
        self.assertIn(d.state, (ConfirmState.CANDIDATE, ConfirmState.PROBABLE))

    def test_confirmation_metrics_low(self):
        m = confirmation_metrics(100.0, 100.5, "LOW", 73)
        self.assertAlmostEqual(m["missed_move_bps"], 50.0, places=6)
        self.assertEqual(m["confirmation_delay_s"], 73.0)

    def test_confirmation_metrics_high(self):
        m = confirmation_metrics(100.0, 99.5, "HIGH", 91)
        self.assertGreater(m["missed_move_bps"], 50.0)
        self.assertEqual(m["confirmation_delay_s"], 91.0)


if __name__ == "__main__":
    unittest.main()
