"""Release gates for the two active PAPER strategies.
These checks must pass before the staging changes can be merged to main.
"""
import unittest
from unittest.mock import patch
import app


class TradingModuleGates(unittest.TestCase):
    def test_archived_modules_must_not_open_new_positions(self):
        self.assertFalse(app.NEWS_NEW_ENTRIES_ENABLED)
        self.assertFalse(app.WHALE_NEW_ENTRIES_ENABLED)
        with patch.object(app, "STORE") as store:
            self.assertFalse(app.open_signal("BTC", 1, "fixture", {"BTC": 1.0}))
            self.assertFalse(app.whale_liq_open("BTC", 1, 1.0, 100.0, {}))
            store.save.assert_not_called()

    def test_local_experiment_is_isolated_paper_500(self):
        self.assertEqual(app.LOCAL_EXPERIMENT_STARTING_EQUITY, 500.0)
        self.assertEqual(len(app.LOCAL_EXPERIMENT_SYMBOLS), 4)
        self.assertIn("HYPE", app.LOCAL_EXPERIMENT_SYMBOLS)
        self.assertIn("NEAR", app.LOCAL_EXPERIMENT_SYMBOLS)
        self.assertEqual(len(set(app.LOCAL_EXPERIMENT_SYMBOLS)),4)
        self.assertEqual(app.LOCAL_EXPERIMENT_MARGIN_FRACTION, 0.20)

    def test_legacy_local_book_is_exit_only(self):
        analysis={"ready":True,"h1_direction_anchor":"fixture","entry_side":1}
        self.assertFalse(app.local_swing_open("HYPE",1,analysis))
        self.assertFalse(app.local_swing_open("NEAR",1,analysis))

    def test_local_entry_direction_is_checked_before_market_access(self):
        analysis={"ready":True,"h1_direction_anchor":"fixture","entry_side":-1}
        with patch.object(app,"current_entry_price") as price:
            self.assertFalse(app.local_experiment_open("TAO",1,analysis))
            price.assert_not_called()


if __name__ == "__main__":
    unittest.main()
