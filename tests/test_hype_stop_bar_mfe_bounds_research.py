"""Run: python -m unittest tests.test_hype_stop_bar_mfe_bounds_research"""
import unittest
from research.hype_terminal_local_strategy.stop_bar_mfe_bounds_research import StopBar, mfe_bounds_at_stop

class TestBounds(unittest.TestCase):
    def check(self, b, hit, lower, upper, ambiguous):
        result=mfe_bounds_at_stop(b)
        self.assertEqual(result[0],hit)
        self.assertAlmostEqual(result[1],lower)
        self.assertAlmostEqual(result[2],upper)
        self.assertEqual(result[3],ambiguous)
    def test_long_stop_bar(self):
        self.check(StopBar('LONG',100,99,100,105,98,101,102),True,.02,.05,True)
    def test_short_stop_bar(self):
        self.check(StopBar('SHORT',100,101,100,102,95,99,98),True,.02,.05,True)
    def test_prior_best(self):
        self.check(StopBar('LONG',100,99,100,101,98,99,104),True,.04,.04,False)
    def test_no_stop(self):
        self.check(StopBar('LONG',100,99,100,103,99.1,102,100),False,0,.03,False)
    def test_short_gap_open(self):
        self.check(StopBar('SHORT',100,101,99,102,95,101,100),True,.01,.05,True)
    def test_invalid_stop(self):
        with self.assertRaises(ValueError):
            mfe_bounds_at_stop(StopBar('LONG',100,101,100,102,99,100,100))
if __name__=='__main__':
    unittest.main()
