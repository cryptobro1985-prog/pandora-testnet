import copy
import unittest
from momentum_scanner import candidates


class MomentumAuditTests(unittest.TestCase):
    def fixture(self, side=1):
        epoch=1000
        rows=[]
        for age in range(190,0,-2):
            if age>=60:
                price=99.5+(190-age)*(-.1/130)
            elif age>=15:
                price=99.4+(60-age)*(.3/45)
            else:
                price=99.7+(15-age)*(.3/15)
            rows.append((epoch-age,price if side>0 else 200-price))
        ctx={"epoch":epoch,"trade_data_fresh":True,"oi_delta_60s":.005,
             "volume_burst_ratio":5,"volume_rate_z":6,"volume_baseline_samples":20}
        return {"BTC":100},{"BTC":rows},{"BTC":1e9},epoch,{"BTC":ctx}

    def scan(self, fixture):
        prices,history,volumes,epoch,contexts=fixture
        return candidates(prices,history,volumes,epoch,contexts=contexts)

    def test_observed_consistent_pump_and_dump_can_be_candidates(self):
        for side in (-1,1):
            with self.subTest(side=side):
                found=self.scan(self.fixture(side))
                self.assertEqual(len(found),1)
                self.assertEqual(found[0]["side"],side)

    def test_burst_without_fresh_observed_trades_is_not_a_signal(self):
        f=self.fixture();f[-1]["BTC"]["trade_data_fresh"]=False
        self.assertEqual(self.scan(f),[])

    def test_stale_metadata_cannot_authorize_an_entry(self):
        f=self.fixture();f[-1]["BTC"]["epoch"]-=30
        self.assertEqual(self.scan(f),[])

    def test_ordinary_participation_does_not_qualify(self):
        f=self.fixture();f[-1]["BTC"].update(volume_burst_ratio=1,volume_rate_z=0)
        self.assertEqual(self.scan(f),[])

    def test_short_history_cannot_substitute_current_price_for_a_horizon(self):
        f=self.fixture();f[1]["BTC"]=f[1]["BTC"][-20:]
        self.assertEqual(self.scan(f),[])

    def test_bounce_inside_longer_selloff_is_rejected(self):
        f=self.fixture();f[1]["BTC"]=[(t,101 if 55<=f[3]-t<=65 else p) for t,p in f[1]["BTC"]]
        self.assertEqual(self.scan(f),[])

    def test_terminal_vertical_spike_is_not_chased(self):
        f=self.fixture();f[0]["BTC"]=105
        self.assertEqual(self.scan(f),[])

    def test_detector_does_not_modify_source_history(self):
        f=self.fixture();before=copy.deepcopy(f)
        self.scan(f)
        self.assertEqual(f,before)
