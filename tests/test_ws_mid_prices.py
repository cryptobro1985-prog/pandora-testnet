import copy,json
import unittest
from unittest.mock import MagicMock,patch
import app
from market_stream import run_trade_stream


class MidPriceTests(unittest.TestCase):
    def setUp(self):self.saved=copy.deepcopy(app.S)
    def tearDown(self):app.S.clear();app.S.update(self.saved)

    def test_ws_snapshot_updates_fresh_prices_and_avoids_rest(self):
        app.accept_market_prices({'HYPE':'79.2','NEAR':'4.5','BAD':'nan','@1':'2','ZERO':'0'})
        with patch.object(app,'get') as network:
            self.assertEqual(app.refresh_market_prices(max_age=8),{'HYPE':79.2,'NEAR':4.5})
        network.assert_not_called()
        self.assertEqual(app.S['_timeline']['HYPE'][-1][1],79.2)

    def test_stale_ws_snapshot_uses_existing_rest_fallback(self):
        app.S.update(_prices={'HYPE':79.},_last_poll_epoch=app.time.time()-60)
        with patch.object(app,'get',return_value=b'{"HYPE":"79.1"}') as network:
            self.assertEqual(app.refresh_market_prices(),{'HYPE':79.1})
        network.assert_called_once()

    def test_existing_socket_subscribes_and_routes_mids(self):
        stop=MagicMock();stop.is_set.side_effect=[False,False,True,True]
        ws=MagicMock();ws.recv.return_value=json.dumps({'channel':'allMids','data':{'mids':{'HYPE':'79.2'}}})
        callback=MagicMock();obs=MagicMock()
        with patch('market_stream.websocket.create_connection',return_value=ws):
            run_trade_stream(obs,stop,lambda:{'HYPE'},lambda state:None,'wss://example.test',on_mids=callback)
        callback.assert_called_once_with({'HYPE':'79.2'})
        sent=[json.loads(c.args[0]) for c in ws.send.call_args_list]
        self.assertIn({'method':'subscribe','subscription':{'type':'allMids'}},sent)
