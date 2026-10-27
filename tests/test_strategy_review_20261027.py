import copy,json,unittest
from unittest.mock import MagicMock,patch
import app
from hype_h1_swing import analyze_m15,m15_reentry_ready,update_path,profit_lock_exit
from market_stream import run_trade_stream

M=900000
def candles():
    return [dict(t=i*M,T=(i+1)*M-1,o=100+i*.1,h=101+i*.1,l=99+i*.1,c=100.5+i*.1,v=100) for i in range(8)]

class EntryQualityTests(unittest.TestCase):
    def test_strong_opposing_executed_flow_vetoes_both_directions_even_with_max_score(self):
        for side in (-1,1):
            m15=dict(ready=True,recovery_confirmed=True,recovery_score=5)
            self.assertFalse(m15_reentry_ready(side,m15,-.4*side))
            self.assertTrue(m15_reentry_ready(side,m15,.4*side))

    def test_partial_candle_compares_elapsed_volume_rate(self):
        rows=candles();rows.append(dict(t=8*M,T=9*M-1,o=101.2,h=102,l=101,c=101.9,v=20))
        result=analyze_m15(rows,8*M+180000,1)
        self.assertTrue(result['partial'])
        self.assertAlmostEqual(result['raw_volume_ratio'],.2)
        self.assertAlmostEqual(result['volume_ratio'],1.)

    def test_stale_and_gapped_m15_cannot_authorize_recovery(self):
        rows=candles()
        self.assertEqual(analyze_m15(rows,rows[-1]['T']+M+121000,1)['reason'],'stale_m15_history')
        rows.pop(-3)
        self.assertEqual(analyze_m15(rows,8*M+1001,1)['reason'],'gapped_m15_history')

    def test_existing_earned_stop_never_loosens_after_partial_state_restore(self):
        for side,stop in ((1,102.),(-1,98.)):
            p=dict(entry=100.,side=side,leverage=25.,features=dict(profit_lock_armed=True,profit_lock_stop=stop))
            result,_=update_path(p,100.+side*.1)
            self.assertEqual(result['features']['profit_lock_stop'],stop)
            self.assertIsNotNone(profit_lock_exit(result,100.+side*.1))

    def test_new_cost_budget_is_respected_and_legacy_floor_remains_supported(self):
        for side in (-1,1):
            p=dict(entry=100.,side=side,leverage=25.,features=dict(profit_lock_buffer_move=.0016))
            result,_=update_path(p,100.+side*.26)
            self.assertAlmostEqual(result['features']['profit_lock_stop'],100.+side*.16)
            self.assertAlmostEqual(result['features']['profit_lock_buffer_move_pct'],.16)

class BreadthStreamTests(unittest.TestCase):
    def setUp(self):self.saved=copy.deepcopy(app.S)
    def tearDown(self):app.S.clear();app.S.update(self.saved)

    def test_six_completed_seed_markets_supply_h1_h4_without_rest(self):
        epoch=20000.;prices={s:100. for s in app.REGIME_SEED_SYMBOLS};volumes={s:1e7 for s in prices};rows=[]
        for s in prices:
            for age,p in ((14400,103.),(3600,101.)):
                T=(epoch-age)*1000
                rows.append(dict(s=s,i='1m',t=T-59999,T=T,c=p))
        with patch.object(app.time,'time',return_value=epoch):self.assertEqual(app.accept_regime_candles(rows),12)
        with patch.object(app,'get') as network:r=app.market_regime(prices,{},volumes,epoch)
        network.assert_not_called();self.assertEqual(r['side'],-1);self.assertNotEqual(r['mode'],'WARMUP')

    def test_open_candle_is_not_future_trend_context_and_commits_only_after_close(self):
        app.S['_regime_candles']={};row=dict(s='BTC',i='1m',t=60000,T=119999,c=100.)
        with patch.object(app.time,'time',return_value=90):self.assertEqual(app.accept_regime_candles(row),0)
        self.assertEqual(app.S['_regime_candles']['BTC'],[])
        next_row=dict(s='BTC',i='1m',t=120000,T=179999,c=101.)
        with patch.object(app.time,'time',return_value=121):self.assertEqual(app.accept_regime_candles(next_row),1)
        self.assertEqual(app.S['_regime_candles']['BTC'],[(119.999,100.)])

    def test_socket_bootstraps_and_routes_seed_history_separately(self):
        stop=MagicMock();stop.is_set.side_effect=[False,False,True,True]
        ws=MagicMock();rows=[dict(s='BTC',i='1m',t=0,T=59999,c=100)]
        ws.recv.return_value=json.dumps(dict(channel='post',data=dict(id=1000000,response=dict(type='info',payload=dict(type='candleSnapshot',data=rows)))))
        callback=MagicMock()
        with patch('market_stream.websocket.create_connection',return_value=ws):
            run_trade_stream(MagicMock(),stop,lambda:set(),lambda _:None,'wss://example.test',regime_symbols=app.REGIME_SEED_SYMBOLS,on_regime_candles=callback)
        callback.assert_called_once_with(rows)
        sent=[json.loads(x.args[0]) for x in ws.send.call_args_list]
        posts=[x for x in sent if x.get('method')=='post']
        self.assertEqual(len(posts),6)
        self.assertEqual({x['request']['payload']['req']['coin'] for x in posts},set(app.REGIME_SEED_SYMBOLS))

if __name__=='__main__':unittest.main()
