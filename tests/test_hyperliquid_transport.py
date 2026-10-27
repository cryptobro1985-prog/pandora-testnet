import copy
import io
import json
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch
from hyperliquid_transport import RestBudget, RestDeferred
import app
from market_stream import run_trade_stream


class BudgetTests(unittest.TestCase):
    def test_all_threads_share_budget_and_priority_reserve(self):
        budget=RestBudget(limit=200,clock=lambda:0)
        def request(_):
            try:budget.acquire({'type':'metaAndAssetCtxs'});return True
            except RestDeferred:return False
        with ThreadPoolExecutor(max_workers=20) as pool:
            self.assertEqual(sum(pool.map(request,range(40))),5)
        budget.acquire({'type':'candleSnapshot','req':{'interval':'1h','startTime':0,'endTime':3600000}})
        self.assertEqual(budget.status()['used_weight_60s'],121)

    def test_retry_after_is_global_and_success_cannot_cancel_cooldown(self):
        now=[0.];budget=RestBudget(clock=lambda:now[0],wall=lambda:1000+now[0])
        budget.limited('90');budget.success()
        for body in ({'type':'allMids'},{'type':'l2Book'},{'type':'candleSnapshot'}):
            with self.assertRaises(RestDeferred):budget.acquire(body)
        now[0]=91;budget.acquire({'type':'allMids'})
        budget.limited();self.assertEqual(budget.status()['cooldown_seconds'],60)

    def test_http_date_retry_after_and_window_expiry(self):
        now=[0.];budget=RestBudget(limit=120,clock=lambda:now[0],wall=lambda:now[0])
        budget.limited('Thu, 01 Jan 1970 00:02:00 GMT')
        self.assertEqual(budget.status()['cooldown_seconds'],120)
        now[0]=121;budget.acquire({'type':'metaAndAssetCtxs'})
        now[0]=182;self.assertEqual(budget.status()['used_weight_60s'],0)

    def test_http_429_blocks_next_network_call_across_endpoints(self):
        budget=RestBudget()
        error=urllib.error.HTTPError(app.API,429,'limited',{'Retry-After':'90'},io.BytesIO())
        with patch.object(app,'HL_REST_BUDGET',budget),patch.object(app.urllib.request,'urlopen',side_effect=error) as net:
            with self.assertRaises(urllib.error.HTTPError):app.get(app.API,{'type':'l2Book'})
            with self.assertRaises(RestDeferred):app.get(app.API,{'type':'allMids'})
        self.assertEqual(net.call_count,1)


class CandleTests(unittest.TestCase):
    def setUp(self):
        self.cache=copy.deepcopy(app._LOCAL_CANDLE_CACHE);self.stream=copy.deepcopy(app._LOCAL_CANDLE_STREAM)
        self.backoff=copy.deepcopy(app._LOCAL_CANDLE_BACKOFF)
        app._LOCAL_CANDLE_CACHE.clear();app._LOCAL_CANDLE_STREAM.clear();app._LOCAL_CANDLE_BACKOFF.clear()
    def tearDown(self):
        for target,saved in ((app._LOCAL_CANDLE_CACHE,self.cache),(app._LOCAL_CANDLE_STREAM,self.stream),(app._LOCAL_CANDLE_BACKOFF,self.backoff)):
            target.clear();target.update(saved)
    def rows(self):
        step=900000;end=int(app.time.time()*1000)//step*step
        return [dict(t=end-i*step,T=end-(i-1)*step-1,s='HYPE',i='15m',o='100',h='102',l='99',c='101',v='10') for i in range(12,0,-1)]
    def test_ws_updates_warm_history_without_rest_and_uses_current_time(self):
        rows=self.rows();key=('HYPE','15m',12)
        app._LOCAL_CANDLE_CACHE[key]=(0,rows,1)
        latest=dict(rows[-1],c='101.5')
        app.accept_local_candles(latest)
        with patch.object(app,'get') as net:
            result,stamp=app._local_m15_candles('HYPE')
        net.assert_not_called();self.assertEqual(result[-1]['c'],'101.5');self.assertGreater(stamp,1)
    def test_cold_ws_candle_does_not_masquerade_as_history(self):
        rows=self.rows();app.accept_local_candles(rows[-1])
        with patch.object(app,'get',return_value=json.dumps(rows).encode()) as net:
            result,_=app._local_m15_candles('HYPE')
        net.assert_called_once();self.assertEqual(len(result),12)
    def test_fresh_exchange_interval_cache_avoids_redundant_rest_recovery(self):
        rows=self.rows();key=('HYPE','15m',12)
        app._LOCAL_CANDLE_CACHE[key]=(0,rows,1)
        with patch.object(app,'get') as net:
            result,_=app._local_m15_candles('HYPE')
        self.assertEqual(len(result),12)
        net.assert_not_called()
    def test_invalid_ws_data_does_not_refresh_cache(self):
        row=self.rows()[-1];row['c']='nan';app.accept_local_candles(row)
        self.assertFalse(app._LOCAL_CANDLE_CACHE)
    def test_socket_subscribes_four_candles_and_routes_updates(self):
        stop=MagicMock();stop.is_set.side_effect=[False,False,True,True]
        ws=MagicMock();row=self.rows()[-1];ws.recv.return_value=json.dumps({'channel':'candle','data':row})
        callback=MagicMock()
        with patch('market_stream.websocket.create_connection',return_value=ws):
            run_trade_stream(MagicMock(),stop,lambda:set(),lambda _:None,'wss://test',on_candles=callback,candle_symbols=('HYPE','NEAR'))
        callback.assert_called_once_with(row)
        subs=[json.loads(c.args[0])['subscription'] for c in ws.send.call_args_list if 'subscription' in json.loads(c.args[0])]
        self.assertEqual(len(subs),4)

class SidecarTests(unittest.TestCase):
    def test_only_public_exchange_info_is_routed_through_budget(self):
        from hyperdata_runner import routed_url
        self.assertEqual(routed_url('https://api.hyperliquid.xyz/info'),'http://127.0.0.1:8421/info')
        for url in ('https://api.hyperliquid.xyz/exchange','https://example.test/info','wss://api.hyperliquid.xyz/ws'):
            self.assertEqual(routed_url(url),url)

    def test_simultaneous_429s_do_not_multiply_cooldown(self):
        b=RestBudget(clock=lambda:0)
        for _ in range(10):b.limited()
        self.assertEqual(b.status()['cooldown_seconds'],30)

    def test_sidecar_and_app_share_single_outbound_budget(self):
        import threading
        import urllib.request
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.HyperliquidBudgetProxy)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        budget=RestBudget(limit=120)
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{}'
        original=urllib.request.urlopen
        url='http://127.0.0.1:%s/info'%server.server_port
        def network(req,**kw):
            if req.full_url==app.API:return response
            return original(req,**kw)
        try:
            with patch.object(app,'HL_REST_BUDGET',budget),patch.object(app.urllib.request,'urlopen',side_effect=network):
                req=urllib.request.Request(url,data=b'{"type":"metaAndAssetCtxs"}',headers={'Content-Type':'application/json'})
                with original(req,timeout=2) as reply:self.assertEqual(reply.status,200)
                with self.assertRaises(RestDeferred):app.get(app.API,{'type':'metaAndAssetCtxs'})
                app.get(app.API,{'type':'allMids'})
            self.assertEqual(budget.status()['sent'],2)
        finally:server.shutdown();server.server_close()

class AdaptiveBudgetTests(unittest.TestCase):
    def test_rate_limit_reduces_future_load_once_per_cooldown(self):
        now=[0.];b=RestBudget(clock=lambda:now[0])
        b.limited();self.assertEqual(b.limit,300)
        b.limited();self.assertEqual(b.limit,300)
        now[0]=31;b.limited();self.assertEqual(b.limit,150)
        now[0]=92;b.limited();self.assertEqual(b.limit,120)

class HistoryBootstrapTests(CandleTests):
    def test_history_bootstrap_restores_old_rows_without_overwriting_live_candle(self):
        rows=self.rows();app.accept_local_candles(dict(rows[-1],c='101.7'))
        app.accept_local_candles(rows,history=True)
        with patch.object(app,'get') as network:result,_=app._local_m15_candles('HYPE')
        network.assert_not_called();self.assertEqual(len(result),12);self.assertEqual(result[-1]['c'],'101.7')

    def test_socket_bootstraps_history_via_documented_info_post(self):
        stop=MagicMock();stop.is_set.side_effect=[False]*24+[True]*8
        ws=MagicMock();rows=self.rows()
        ws.recv.return_value=json.dumps({'channel':'post','data':{'id':1000000,'response':{'type':'info','payload':{'type':'candleSnapshot','data':rows}}}})
        callback=MagicMock();clock=iter(range(1,200))
        with patch('market_stream.websocket.create_connection',return_value=ws),patch('market_stream.time.time',side_effect=lambda: next(clock)):
            run_trade_stream(MagicMock(),stop,lambda:set(),lambda _:None,'wss://test',candle_symbols=('HYPE','NEAR'),on_candle_history=callback)
        self.assertGreaterEqual(callback.call_count,1)
        posts=[json.loads(c.args[0]) for c in ws.send.call_args_list if json.loads(c.args[0]).get('method')=='post']
        self.assertGreaterEqual(len(posts),1)
        self.assertTrue(all(p['request']['payload']['type']=='candleSnapshot' for p in posts))
        self.assertTrue(all(p['request']['payload']['req']['interval']=='3m' for p in posts))
