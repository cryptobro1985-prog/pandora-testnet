import unittest

from market_data import RollingMarketData


def trade(ident, stamp=1001, price=100, side='B', symbol='BTC', size=1):
    return dict(coin=symbol, tid=ident, time=stamp * 1000,
                px=price, sz=size, side=side)


class ExecutionEventTests(unittest.TestCase):
    def collector(self, **options):
        result = RollingMarketData(**options)
        result.mark_connected(1000, ['BTC'], owner='test')
        return result

    def test_ordered_event_metadata_and_accepted_rows_remain_exact(self):
        collector = self.collector()
        rows = [trade('first', price=100, size=2), trade('second', price=101, side='A')]
        accepted = []
        self.assertEqual(collector.ingest_trades(rows, 1001.05, owner='test', accepted_rows=accepted), 2)
        self.assertEqual(accepted, rows)
        events = collector.events_after('BTC', 0)
        self.assertEqual([event['sequence'] for event in events], [1, 2])
        self.assertEqual([event['id'] for event in events], ['first', 'second'])
        self.assertEqual(events[0], dict(id='first', sequence=1, exchange_epoch=1001,
                                        received_epoch=1001.05, price=100, size=2,
                                        notional=200, aggressor_side='B', side='B'))
        self.assertEqual(collector.events_after('BTC', 1), events[1:])

    def test_acceptance_8_polling_never_creates_new_execution_evidence(self):
        collector = self.collector()
        row = trade('unique')
        collector.ingest_trades([row], 1001, owner='test')
        for _ in range(100):
            collector.flow_context('BTC', 1001)
            collector.events_after('BTC', 1)
            collector.event_status('BTC', 1)
        self.assertEqual(collector.execution_sequences(), {'BTC': 1})
        self.assertEqual(collector.ingest_trades([row], 1001.1, owner='test'), 0)
        self.assertEqual(collector.event_status('BTC')['latest_sequence'], 1)

    def test_reconnect_preserves_sequence_and_deduplicates_overlap(self):
        collector = self.collector()
        row = trade('original')
        collector.ingest_trades([row], 1001, owner='test')
        collector.mark_disconnected(owner='test')
        collector.mark_connected(1001, ['BTC'], owner='test')
        self.assertFalse(collector.flow_context('BTC', 1001)['trade_data_fresh'])
        self.assertEqual(collector.ingest_trades([row], 1001.1, owner='test'), 0)
        collector.ingest_trades([trade('new', stamp=1001.2)], 1001.2, owner='test')
        self.assertEqual([event['sequence'] for event in collector.events_after('BTC', 0)], [1, 2])
        self.assertEqual(collector.flow_context('BTC', 1001.2)['execution_sequence'], 2)

    def test_bounded_replay_buffer_exposes_gap_for_lagging_consumer(self):
        collector = self.collector(max_events_per_symbol=2)
        collector.ingest_trades([trade(str(n), price=100 + n) for n in range(4)], 1001, owner='test')
        self.assertEqual([event['sequence'] for event in collector.events_after('BTC')], [3, 4])
        self.assertTrue(collector.event_status('BTC', 1)['gap'])
        self.assertFalse(collector.event_status('BTC', 2)['gap'])
        self.assertEqual(collector.event_status('BTC')['buffered_events'], 2)

    def test_restart_seeds_sequences_from_persisted_cursor(self):
        collector = self.collector()
        collector.restore_execution_sequences({'BTC': 125})
        self.assertTrue(collector.event_status('BTC', 124)['gap'])
        self.assertFalse(collector.event_status('BTC', 125)['gap'])
        collector.ingest_trades([trade('post_restart')], 1001, owner='test')
        self.assertEqual(collector.events_after('BTC', 125)[0]['sequence'], 126)

    def test_symbols_have_independent_sequences_and_lru_eviction_reports_gap(self):
        collector = self.collector(max_symbols=1)
        collector.ingest_trades([trade('btc')], 1001, owner='test')
        collector.set_subscriptions(['SOL'], 1001, owner='test')
        collector.ingest_trades([trade('sol', symbol='SOL', stamp=1002)], 1002, owner='test')
        self.assertEqual(collector.execution_sequences(), {'BTC': 1, 'SOL': 1})
        self.assertEqual(collector.events_after('BTC'), [])
        self.assertTrue(collector.event_status('BTC', 0)['gap'])
        collector.set_subscriptions(['BTC'], 1002, owner='test')
        collector.ingest_trades([trade('btc_again', stamp=1003)], 1003, owner='test')
        self.assertEqual(collector.events_after('BTC')[0]['sequence'], 2)

    def test_rejected_rows_never_receive_execution_sequence(self):
        collector = self.collector()
        rows = [trade('old', stamp=999), trade('future', stamp=1003),
                trade('bad', side='UNKNOWN'), trade('other', symbol='SOL')]
        self.assertEqual(collector.ingest_trades(rows, 1001, owner='test'), 0)
        self.assertEqual(collector.events_after('BTC'), [])
        self.assertEqual(collector.event_status('BTC')['latest_sequence'], 0)

    def test_flow_metadata_counts_notional_ratio_and_receive_time(self):
        collector = self.collector()
        collector.ingest_trades([trade('buy', price=100, size=2),
                                 trade('sell', price=100, side='A')],
                                1001.02, owner='test')
        flow = collector.flow_context('BTC', 1001.03)
        self.assertEqual(flow['execution_sequence'], 2)
        self.assertEqual(flow['latest_receive_epoch'], 1001.02)
        self.assertEqual(flow['buy_trade_count'], 1)
        self.assertEqual(flow['sell_trade_count'], 1)
        self.assertEqual(flow['buy_sell_ratio'], 2)

    def test_returned_event_cannot_mutate_replay_history(self):
        collector = self.collector()
        collector.ingest_trades([trade('first')], 1001, owner='test')
        collector.events_after('BTC')[0]['price'] = -1
        self.assertEqual(collector.events_after('BTC')[0]['price'], 100)


if __name__ == '__main__':
    unittest.main()
