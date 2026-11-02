"""Four-hour cohorts, continuous observed fading and admission requirements."""
import unittest
from pandora_scanner import LiveScanner


def tape(velocity=100, rate=2, fresh=True):
    window=dict(buy_volume=velocity,sell_volume=0,volume_velocity=velocity,
                trade_count=10 if velocity else 0,trade_velocity=rate,volume_change=0)
    return dict(trade_data_fresh=fresh,latest_trade_epoch=1000,
                windows={str(n):dict(window) for n in (5,15,60)},fast_control_side=0)


def ticker(scanner,symbol,epoch,price,turnover=20_000_000,spread=.001,size=100):
    scanner.ingest(dict(symbol=symbol+'USDT',lastPrice=price,turnover24h=turnover,
                        price24hPcnt=.1,bid1Price=price*(1-spread/2),ask1Price=price*(1+spread/2),
                        bid1Size=size,ask1Size=size),epoch*1000,epoch)


def warm(scanner,symbols=('OLD',),start=1000):
    instruments={s:{} for s in symbols}
    for epoch,price in ((start,100),(start+10,110),(start+16,111)):
        for symbol in symbols:ticker(scanner,symbol,epoch,price)
        result=scanner.rank(instruments,lambda *args:tape(),epoch=epoch)
    return result


class IncidentScannerTests(unittest.TestCase):
    def test_small_activity_decline_is_not_fading(self):
        scanner=LiveScanner(top=1);warm(scanner)
        ticker(scanner,'OLD',1017,111)
        result=scanner.rank({'OLD':{}},lambda *args:tape(99),epoch=1017)
        self.assertEqual(result['selected_symbols'],['OLD'])
        self.assertFalse(result['selected'][0]['fading'])
        self.assertFalse(result['events'])

    def test_material_sustained_activity_loss_replaces_only_one_and_retains_position(self):
        scanner=LiveScanner(top=2);warm(scanner,('A','B'))
        instruments={s:{} for s in ('A','B','NEW')}
        for epoch in range(1017,1201):
            for s in instruments:ticker(scanner,s,epoch,111 if s in ('A','B') else 100+(epoch-1017)*.01)
            result=scanner.rank(instruments,lambda s,*args:tape(0,0) if s=='A' else tape(),held=['A'],epoch=epoch)
            if epoch<1197:self.assertEqual(set(result['selected_symbols']),{'A','B'})
        self.assertEqual(set(result['selected_symbols']),{'B','NEW'})
        self.assertEqual(result['retained_open_positions'],['A'])
        self.assertEqual(result['selected_at'],1016)
        self.assertEqual(result['next_refresh_at'],1016+14400)
        self.assertEqual(result['last_rotation_events'][0]['reason'],'confirmed_180s_activity_fade')
        restored=LiveScanner(top=2);restored.restore(result)
        self.assertEqual(restored.last_snapshot['next_refresh_at'],15416)

    def test_rank_noise_cannot_replace_before_four_hours_but_candidates_keep_warming(self):
        scanner=LiveScanner(top=1,candidate_limit=2);warm(scanner,('A',))
        for epoch in (1017,1020,1035):
            ticker(scanner,'A',epoch,111);ticker(scanner,'HOT',epoch,100+(epoch-1017)*5)
            result=scanner.rank({'A':{},'HOT':{}},lambda *args:tape(),epoch=epoch)
            self.assertEqual(result['selected_symbols'],['A'])
        self.assertIn('HOT',result['candidate_symbols'])

    def test_stale_ticker_and_stale_flow_do_not_prove_fading(self):
        scanner=LiveScanner(top=1);warm(scanner)
        for epoch in (1020,1100,1300):
            ticker(scanner,'NEW',epoch,100+(epoch-1020)*.1)
            result=scanner.rank({'OLD':{},'NEW':{}},lambda *args:tape(fresh=False),held=['OLD'],epoch=epoch)
            self.assertEqual(result['selected_symbols'],['OLD'])
            self.assertEqual(result['events'],[])

    def test_turnover_boundary_spread_and_top_book_are_independent_gates(self):
        cases=[(9_999_999,.001,100,False),(10_000_000,.001,100,True),
               (50_000_000,.01,100,False),(50_000_000,.001,.01,False)]
        for turnover,spread,size,expected in cases:
            with self.subTest(turnover=turnover,spread=spread,size=size):
                scanner=LiveScanner(top=1)
                for epoch,price in ((1000,100),(1010,101),(1016,102)):
                    ticker(scanner,'X',epoch,price,turnover,spread,size)
                    result=scanner.rank({'X':{}},lambda *args:tape(),epoch=epoch)
                self.assertEqual(bool(result['selected_symbols']),expected)

    def test_startup_warms_candidates_before_selection_and_accepts_falling_market(self):
        scanner=LiveScanner(top=1)
        ticker(scanner,'X',1000,100)
        cold=scanner.rank({'X':{}},lambda *args:{},epoch=1000)
        self.assertEqual(cold['selected_symbols'],[]);self.assertEqual(cold['candidate_symbols'],['X'])
        ticker(scanner,'X',1010,99.5)
        ticker(scanner,'X',1016,99)
        ready=scanner.rank({'X':{}},lambda *args:tape(),epoch=1016)
        self.assertEqual(ready['selected_symbols'],['X'])
        self.assertEqual(ready['selected'][0]['move'],'CORRECTION')

    def test_scheduled_four_hour_refresh_survives_restore(self):
        scanner=LiveScanner(top=1);original=warm(scanner)
        restored=LiveScanner(top=1);restored.restore(original)
        due=original['next_refresh_at']
        for epoch in (due-20,due-10,due-1,due):
            ticker(restored,'OLD',epoch,111);ticker(restored,'HOT',epoch,100+(epoch-due+20)*2)
            result=restored.rank({'OLD':{},'HOT':{}},lambda *args:tape(),epoch=epoch)
            self.assertEqual(result['selected_symbols'],['HOT'] if epoch==due else ['OLD'])
        self.assertEqual(result['selected_at'],due)
