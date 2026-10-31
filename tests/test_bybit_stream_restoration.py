import json
import unittest
from unittest.mock import Mock,patch
from bybit_market_stream import run_bybit_stream
from market_data import RollingMarketData


class BybitStreamContracts(unittest.TestCase):
    def stream(self, messages):
        stop=Mock();stop.is_set.return_value=False
        reports=[];marks=[];sent=[]
        clock=[1000.0]
        def now():
            clock[0]+=.1
            return clock[0]
        def receive():
            if messages:
                return json.dumps(messages.pop(0))
            stop.is_set.return_value=True
            return json.dumps({'op':'pong'})
        ws=Mock();ws.recv.side_effect=receive
        ws.send.side_effect=lambda payload:sent.append(json.loads(payload))
        obs=RollingMarketData(freshness_seconds=60)
        with patch('bybit_market_stream.websocket.create_connection',return_value=ws),patch('bybit_market_stream.time.time',side_effect=now):
            run_bybit_stream(obs,stop,lambda:{'BTC'},reports.append,on_mids=marks.append,
                             on_trade_mids=marks.append,worker_name='test')
        return reports,marks,sent,obs

    def trade(self,epoch_ms=1000500,price='100',ident='a'):
        return {'topic':'publicTrade.BTCUSDT','data':[{'s':'BTCUSDT','p':price,'v':'1','T':epoch_ms,'S':'Buy','i':ident}]}

    def test_ticker_ack_does_not_confirm_public_trade_subscription(self):
        reports,_,sent,_=self.stream([{'op':'subscribe','success':True,'req_id':'test:2'}])
        self.assertFalse(next(r for r in reports if r.get('ok'))['subscription_confirmed'])
        self.assertEqual(sent[0]['args'],['publicTrade.BTCUSDT'])

    def test_matching_public_trade_ack_confirms_subscription(self):
        reports,_,_,_=self.stream([{'op':'subscribe','success':True,'req_id':'test:1'}])
        self.assertTrue(next(r for r in reports if r.get('ok'))['subscription_confirmed'])

    def test_old_delayed_packet_does_not_roll_back_mark(self):
        _,marks,_,_=self.stream([self.trade(1000500,'101','a'),self.trade(1000400,'99','b')])
        self.assertEqual(marks,[{'BTC':101.0}])

    def test_malformed_and_stale_trade_cannot_update_mark(self):
        invalid=self.trade();invalid['data']=[{'bad':'row'}]
        _,marks,_,_=self.stream([invalid,self.trade(900000)])
        self.assertEqual(marks,[])

    def test_delta_ticker_never_refreshes_unchanged_symbols(self):
        _,marks,_,_=self.stream([{'topic':'tickers.BTCUSDT','data':{'symbol':'BTCUSDT','lastPrice':'100'}},
                               {'topic':'tickers.BTCUSDT','data':{'symbol':'BTCUSDT','fundingRate':'0.001'}}])
        self.assertEqual(marks,[{'BTC':'100'}])

    def test_same_millisecond_distinct_trade_updates_mark(self):
        _,marks,_,_=self.stream([self.trade(1000500,'100','a'),self.trade(1000500,'101','b')])
        self.assertEqual(marks,[{'BTC':100.0},{'BTC':101.0}])

    def test_rejected_row_in_mixed_batch_cannot_poison_mark(self):
        packet=self.trade(1000500,'101','a')
        packet['data']+=self.trade(1000400,'99','b')['data']
        _,marks,_,_=self.stream([packet])
        self.assertEqual(marks,[{'BTC':101.0}])
