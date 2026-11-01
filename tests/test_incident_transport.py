"""Observed incident: subscription churn, stale backlog and expensive reads."""
import json
import threading
import unittest
from unittest.mock import Mock,patch

from bybit_market_stream import run_bybit_stream
from market_data import RollingMarketData
from pandora_flow import summarize


def trade(epoch,price=100,ident='a'):
    return dict(coin='BTC',px=price,sz=1,time=epoch*1000,side='B',tid=ident)


class FlowReadIncidentTests(unittest.TestCase):
    def observations(self):
        obs=RollingMarketData(freshness_seconds=15)
        obs.mark_connected(1000,['BTC'],owner='test')
        for epoch,price,ident in ((1000,99,'start'),(1010,99,'warm'),(1016,100,'second'),(1020,101,'third')):
            obs.ingest_trades([trade(epoch,price,ident)],epoch,owner='test')
        return obs

    def test_cache_reuses_same_revision_but_never_hides_new_executions_or_window_expiry(self):
        obs=self.observations()
        with patch('market_data.summarize',wraps=summarize) as calculated:
            first=obs.flow_context('BTC',1020)
            first['windows']['5']['buy_volume']=-1
            again=obs.flow_context('BTC',1020.1)
            self.assertGreater(again['windows']['5']['buy_volume'],0)
            self.assertAlmostEqual(again['latest_trade_age_seconds'],.1)
            self.assertEqual(calculated.call_count,1)
            obs.ingest_trades([trade(1020.11,102,'fourth')],1020.11,owner='test')
            self.assertEqual(obs.flow_context('BTC',1020.12)['last_price'],102)
            self.assertEqual(calculated.call_count,2)
            obs.flow_context('BTC',1020.26)
            self.assertEqual(calculated.call_count,3)
            self.assertLess(obs.flow_context('BTC',1021.1)['windows']['5']['buy_volume'],again['windows']['5']['buy_volume']+102)
            self.assertFalse(obs.flow_context('BTC',1036)['trade_data_fresh'])

    def test_expensive_summary_does_not_hold_socket_ingestion_lock(self):
        obs=self.observations();done=threading.Event()
        def calculate(rows,epoch,coverage):
            writer=threading.Thread(target=lambda:(obs.ingest_trades([trade(1020.1,102,'fourth')],1020.1,owner='test'),done.set()))
            writer.start()
            self.assertTrue(done.wait(1),'reader blocked trade ingestion while computing flow')
            writer.join(1)
            return summarize(rows,epoch,coverage)
        with patch('market_data.summarize',side_effect=calculate):obs.flow_context('BTC',1020)
        self.assertEqual(obs.flow_context('BTC',1020.2)['last_price'],102)

    def test_receive_delay_cannot_manufacture_exchange_control_duration(self):
        obs=RollingMarketData();obs.mark_connected(1000,['BTC'],owner='test')
        obs.ingest_trades([trade(1001,100,'first')],1001,owner='test')
        first=obs.flow_context('BTC',1001)['decision_event_epoch']
        obs.ingest_trades([trade(1001,101,'same-ms-distinct')],1004,owner='test')
        second=obs.flow_context('BTC',1004)['decision_event_epoch']
        self.assertGreater(second,first)
        self.assertLess(second-first,.001)

    def test_reconnect_cannot_reuse_cached_fresh_tape(self):
        obs=self.observations();self.assertTrue(obs.flow_context('BTC',1020)['trade_data_fresh'])
        obs.mark_disconnected(owner='test');obs.mark_connected(1020.05,['BTC'],owner='test')
        self.assertFalse(obs.flow_context('BTC',1020.1)['trade_data_fresh'])


class StreamIncidentTests(unittest.TestCase):
    def run_stream(self,backlog=False):
        clock=[1000.];stop=threading.Event();reports=[];ws=Mock();messages=[]
        def send(raw):
            message=json.loads(raw)
            if backlog and message.get('op')=='subscribe':messages.append({'op':'subscribe','success':True,'req_id':message['req_id']})
        def receive():
            clock[0]+=1
            if clock[0]>1025:stop.set()
            if messages:return json.dumps(messages.pop(0))
            if backlog:
                return json.dumps({'topic':'publicTrade.BTCUSDT','data':[{'s':'BTCUSDT','p':'100','v':'1',
                    'T':int((clock[0]-10)*1000),'S':'Buy','i':str(clock[0])}]})
            return json.dumps({'op':'pong'})
        def report(value):
            reports.append(value)
            if value.get('error'):stop.set()
        ws.send.side_effect=send;ws.recv.side_effect=receive
        provider=lambda:{'BTC'} if backlog else {'BTC','N'+str(int(clock[0]))}
        with patch('bybit_market_stream.websocket.create_connection',return_value=ws),patch('bybit_market_stream.time.time',side_effect=lambda:clock[0]):
            run_bybit_stream(RollingMarketData(freshness_seconds=15),stop,provider,report,worker_name='incident')
        return reports

    def test_subscription_changes_cannot_keep_resetting_an_old_missing_ack_deadline(self):
        reports=self.run_stream()
        self.assertTrue(any('subscription_ack_timeout' in (row.get('error') or '') for row in reports))

    def test_continuously_delayed_packets_trigger_backlog_recovery_even_under_fifteen_seconds(self):
        reports=self.run_stream(backlog=True)
        self.assertTrue(any('lagging_fast_window' in (row.get('error') or '') for row in reports))
