import copy
import json
import unittest

from pandora_scanner import LiveScanner
from pandora_universe import HourlyUniverse


def discovery(symbols, stamp, **extra):
    rows = [dict(symbol=symbol, rank=rank, last=100 + rank,
                 change_24h_pct=20 - rank, turnover_24h=1000000 * rank,
                 volume_24h=10000 * rank, eligible=True,
                 price_received=stamp, exchange_ms=stamp * 1000)
            for rank, symbol in enumerate(symbols, 1)]
    return dict(at=stamp, ranked_rows=rows, top_movers=copy.deepcopy(rows),
                selected_symbols=list(reversed(symbols[:5])),
                candidate_symbols=list(symbols), observations_ready=True,
                selection_frozen=False, **extra)


class HourlyUniverseTests(unittest.TestCase):
    def test_acceptance_10_entry_set_changes_only_at_hour_and_keeps_positions(self):
        universe = HourlyUniverse()
        first = universe.update(discovery(list('ABCDE'), 36000), epoch=36000)
        self.assertEqual(first['selected_symbols'], list('ABCDE'))
        self.assertEqual(first['last_refresh_at'], 36000)
        self.assertEqual(first['next_refresh_at'], 39600)
        intrahour = universe.update(discovery(list('BCFGH'), 36900),
                                    held=['A', 'D'], epoch=36900)
        self.assertEqual(intrahour['selected_symbols'], list('ABCDE'))
        self.assertFalse(intrahour['universe_refreshed'])
        self.assertEqual(intrahour['candidate_symbols'], list('ABCDE'))
        self.assertEqual(intrahour['selected'], first['selected'])
        refreshed = universe.update(discovery(list('BCFGH'), 39600),
                                    held=['A', 'D'], epoch=39600)
        self.assertEqual(refreshed['selected_symbols'], list('BCFGH'))
        self.assertEqual(refreshed['managed_symbols'], ['A', 'D'])
        self.assertEqual(refreshed['tracking_symbols'], list('BCFGHAD'))
        self.assertEqual(refreshed['states']['A'], 'MANAGED_POSITION')
        self.assertEqual(refreshed['states']['D'], 'MANAGED_POSITION')
        self.assertTrue(all('CLOSE' not in event['action'] for event in refreshed['events']))

    def test_acceptance_11_restart_preserves_metadata_and_hourly_cycle(self):
        universe = HourlyUniverse()
        first = universe.update(discovery(list('ABCDE'), 36000), epoch=36000)
        universe.update(discovery(list('BCFGH'), 39600), held=['A', 'D'], epoch=39600)
        encoded = json.dumps(universe.to_dict())
        restored = HourlyUniverse(state=json.loads(encoded))
        before = restored.to_dict()
        result = restored.update(discovery(list('HIJKL'), 40000), held=['A', 'D'], epoch=40000)
        self.assertEqual(result['selected_symbols'], list('BCFGH'))
        self.assertEqual(result['selected'], before['selected'])
        self.assertEqual(result['last_refresh_at'], 39600)
        self.assertEqual(result['next_refresh_at'], 43200)
        self.assertEqual(result['managed_symbols'], ['A', 'D'])
        self.assertFalse(result['universe_refreshed'])
        row = first['selected'][0]
        for field in ('rank', 'change_24h_pct', 'current_price', 'turnover_24h',
                      'volume_24h', 'selected_at', 'reason', 'refresh_timestamp'):
            self.assertIn(field, row)

    def test_bootstrap_is_immediate_then_uses_next_aligned_utc_hour(self):
        universe = HourlyUniverse()
        result = universe.update(discovery(list('ABCDE'), 36900), epoch=36900)
        self.assertTrue(result['universe_refreshed'])
        self.assertEqual(result['next_refresh_at'], 39600)
        self.assertFalse(universe.due(39599.999))
        self.assertTrue(universe.due(39600))

    def test_restart_after_missed_hours_refreshes_once_without_replaying(self):
        universe = HourlyUniverse()
        universe.update(discovery(list('ABCDE'), 36000), epoch=36000)
        restored = HourlyUniverse(state=universe.to_dict())
        result = restored.update(discovery(list('FGHIJ'), 47000), epoch=47000)
        self.assertEqual(result['last_refresh_at'], 47000)
        self.assertEqual(result['next_refresh_at'], 50400)
        self.assertEqual(sum(event['action'] == 'UNIVERSE_REFRESHED' for event in result['events']), 1)

    def test_discovery_outage_does_not_consume_refresh_or_remove_managed_positions(self):
        universe = HourlyUniverse()
        universe.update(discovery(list('ABCDE'), 36000), epoch=36000)
        old = universe.to_dict()
        frozen = universe.update(dict(observations_ready=False, ranked_rows=[],
                                      selection_frozen=True), held=['OLD'], epoch=39600)
        self.assertEqual(frozen['selected'], old['selected'])
        self.assertEqual(frozen['next_refresh_at'], 39600)
        self.assertEqual(frozen['managed_symbols'], ['OLD'])
        self.assertTrue(frozen['hourly_refresh_due'])
        self.assertTrue(frozen['selection_frozen'])
        recovered = universe.update(discovery(list('FGHIJ'), 39610), held=['OLD'], epoch=39610)
        self.assertEqual(recovered['next_refresh_at'], 43200)
        self.assertEqual(recovered['selected_symbols'], list('FGHIJ'))

    def test_closed_legacy_position_leaves_management_without_reentry_permission(self):
        universe = HourlyUniverse()
        universe.update(discovery(list('ABCDE'), 36000), held=['OLD'], epoch=36000)
        result = universe.update(discovery(list('FGHIJ'), 36100), held=(), epoch=36100)
        self.assertNotIn('OLD', result['tracking_symbols'])
        self.assertNotIn('OLD', result['current_entry_set'])
        self.assertEqual(result['states']['OLD'], 'ROTATE_OUT')

    def test_discovery_and_returned_snapshots_cannot_mutate_persisted_universe(self):
        universe = HourlyUniverse()
        source = discovery(list('ABCDE'), 36000)
        result = universe.update(source, epoch=36000)
        source['ranked_rows'][0]['last'] = -1
        result['selected'][0]['last'] = -2
        self.assertEqual(universe.to_dict()['selected'][0]['last'], 101)

    def test_scanner_exposes_full_ranked_cross_section_and_volume(self):
        scanner = LiveScanner(top=1, candidate_limit=1)
        stamp = 36000
        for symbol, turnover in [('A', 1000000), ('B', 2000000), ('C', 3000000)]:
            scanner.ingest(dict(symbol=symbol + 'USDT', lastPrice=100,
                                turnover24h=turnover, volume24h=turnover / 100,
                                price24hPcnt=.1), stamp * 1000, stamp)
        snapshot = scanner.rank(dict.fromkeys('ABC', {}), lambda *args: {}, epoch=stamp)
        self.assertEqual(len(snapshot['top_movers']), 1)
        self.assertEqual(len(snapshot['ranked_rows']), 3)
        result = HourlyUniverse().update(snapshot, epoch=stamp)
        self.assertEqual(len(result['selected_symbols']), 3)
        self.assertEqual(result['selected'][0]['volume_24h'], 30000)


if __name__ == '__main__':
    unittest.main()
