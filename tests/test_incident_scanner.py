"""Incident regressions: ranking noise must not repeatedly erase warm tape."""
import unittest

from pandora_scanner import LiveScanner


def tape(velocity=100):
    window=dict(buy_volume=velocity,sell_volume=0,volume_velocity=velocity,
                trade_count=10,trade_velocity=2,volume_change=0)
    return dict(trade_data_fresh=True,latest_trade_epoch=1000,
                windows={str(n):dict(window) for n in (5,15,60)},fast_control_side=0)


def ticker(scanner,symbol,epoch,price,turnover=1000):
    scanner.ingest(dict(symbol=symbol+'USDT',lastPrice=price,turnover24h=turnover,
                        price24hPcnt=.1),epoch*1000,epoch)


class IncidentScannerTests(unittest.TestCase):
    def test_small_activity_decline_without_strict_control_is_not_immediate_fading(self):
        scanner=LiveScanner(top=1)
        for epoch,price in ((1000,100),(1010,110),(1016,111)):
            ticker(scanner,'BTC',epoch,price)
            scanner.rank({'BTC':{}},lambda *args:tape(),epoch=epoch)
        ticker(scanner,'BTC',1017,111)
        result=scanner.rank({'BTC':{}},lambda *args:tape(99),epoch=1017)
        self.assertEqual(result['selected_symbols'],['BTC'])
        self.assertFalse(result['selected'][0]['fading'])
        self.assertFalse(result['events'])

    def test_material_sustained_activity_loss_still_rotates(self):
        scanner=LiveScanner(top=1)
        for epoch,price in ((1000,100),(1010,110),(1016,111)):
            ticker(scanner,'BTC',epoch,price)
            scanner.rank({'BTC':{}},lambda *args:tape(),epoch=epoch)
        for epoch in (1017,1020,1025):
            ticker(scanner,'BTC',epoch,111)
            self.assertEqual(scanner.rank({'BTC':{}},lambda *args:tape(20),epoch=epoch)['selected_symbols'],['BTC'])
        ticker(scanner,'BTC',1033,111)
        result=scanner.rank({'BTC':{}},lambda *args:tape(20),epoch=1033)
        self.assertEqual(result['selected_symbols'],[])
        self.assertEqual(result['events'][0]['action'],'TOKEN_ROTATED')

    def test_candidate_and_selection_warmup_survive_rank_noise_then_hot_candidate_replaces(self):
        scanner=LiveScanner(top=1,candidate_limit=2)
        instruments={s:{} for s in ('A','B','C')}
        for symbol,turnover in (('A',1000),('B',2000),('C',3000)):
            ticker(scanner,symbol,1000,100,turnover)
        first=scanner.rank(instruments,lambda *args:{},epoch=1000)
        selected=first['selected_symbols'];candidates=set(first['candidate_symbols'])
        for epoch in range(1001,1010):
            for symbol in instruments:
                ticker(scanner,symbol,epoch,101 if symbol!='A' else 105,100000 if symbol=='A' else 3000)
            result=scanner.rank(instruments,lambda *args:{},epoch=epoch)
            self.assertEqual(result['selected_symbols'],selected)
            self.assertEqual(set(result['candidate_symbols']),candidates)
        for symbol in instruments:
            ticker(scanner,symbol,1020,150 if symbol=='A' else 102,100000 if symbol=='A' else 3000)
        result=scanner.rank(instruments,lambda *args:{},epoch=1020)
        self.assertEqual(result['selected_symbols'],['A'])
        self.assertIn('A',result['candidate_symbols'])

    def test_dead_selected_ticker_is_not_kept_by_warmup(self):
        scanner=LiveScanner(top=1)
        ticker(scanner,'OLD',1000,100)
        scanner.rank({'OLD':{},'NEW':{}},lambda *args:tape(),epoch=1000)
        ticker(scanner,'NEW',1020,101)
        result=scanner.rank({'OLD':{},'NEW':{}},lambda *args:tape(),held=['OLD'],epoch=1020)
        self.assertEqual(result['selected_symbols'],['NEW'])
        self.assertEqual(result['retained_open_positions'],['OLD'])
