import unittest
from momentum_scanner import breadth_regime, regime_candidate_guard, direction_guard


class RegimeV6Tests(unittest.TestCase):
    def fixture(self,h1=-.01,h4=-.025):
        epoch=20_000.;symbols=['BTC','ETH','SOL','AAA','BBB','CCC']
        prices={s:100. for s in symbols};volumes={s:1e7 for s in symbols}
        quotes={s:[(epoch-age,100/(1+.008*age/900)) for age in (900,300,180,60,15,2)] for s in symbols}
        candles={s:[(epoch-14400,100/(1+h4)),(epoch-3600,100/(1+h1))] for s in symbols}
        return prices,quotes,volumes,epoch,candles

    def regime(self,f):
        return breadth_regime(*f,require_trend_context=True)

    def test_fifteen_minute_bounce_does_not_override_falling_h1_h4(self):
        r=self.regime(self.fixture());self.assertEqual(r['side'],-1)
        self.assertEqual(r['allowed_sides'],[-1])
        self.assertIsNotNone(regime_candidate_guard({'side':1,'r60_pct':2,'score':100},r))

    def test_h1_h4_growth_allows_only_longs(self):
        r=self.regime(self.fixture(.01,.025));self.assertEqual(r['side'],1)
        self.assertIsNotNone(regime_candidate_guard({'side':-1,'r60_pct':-2},r))

    def test_moderate_higher_decline_cannot_be_overridden_by_a_rebound(self):
        r=self.regime(self.fixture(-.003,-.009))
        self.assertEqual(r['allowed_sides'],[-1])
        self.assertIsNotNone(regime_candidate_guard({'side':1,'r60_pct':1},r))

    def test_conflicting_higher_timeframes_block_both_directions(self):
        r=self.regime(self.fixture(.01,-.025));self.assertEqual(r['mode'],'TRANSITION')
        for side in (-1,1):self.assertIsNotNone(regime_candidate_guard({'side':side},r))

    def test_missing_higher_context_is_warmup_not_a_flat_market(self):
        f=list(self.fixture());f[-1]={};r=self.regime(f)
        self.assertEqual(r['mode'],'WARMUP')
        self.assertIsNotNone(direction_guard('BTC',1,f[0],f[1],f[3],r))

    def test_flat_market_requires_an_isolated_relative_anomaly(self):
        f=list(self.fixture(0,0));f[1]={s:[(f[3]-age,100.) for age in (900,300,180,60,15)] for s in f[0]}
        r=self.regime(f);self.assertEqual(r['mode'],'FLAT')
        self.assertIsNotNone(regime_candidate_guard({'side':1,'r60_pct':.1},r))
        self.assertIsNone(regime_candidate_guard({'side':1,'r60_pct':.6},r))
        self.assertIsNone(regime_candidate_guard({'side':-1,'r60_pct':-.6},r))
