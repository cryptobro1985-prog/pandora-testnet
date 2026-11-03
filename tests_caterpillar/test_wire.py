"""Real loopback websocket -> reused Bybit transport -> PAPER engine."""
import asyncio
import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest

from aiohttp import web
from caterpillar_paper.config import Config
from caterpillar_paper.engine import Engine
from caterpillar_paper.market import StreamBridge
from caterpillar_paper.storage import Store


class WireTests(unittest.TestCase):
    def test_real_wire_ack_trade_ingress_and_reconnect(self):
        loop=asyncio.new_event_loop(); ready=threading.Event(); connected=threading.Event(); state={}
        async def handler(request):
            ws=web.WebSocketResponse(); await ws.prepare(request); state['ws']=ws
            async for msg in ws:
                data=json.loads(msg.data)
                if data.get('op')=='subscribe':
                    await ws.send_json({'op':'subscribe','success':True,'req_id':data['req_id']})
                    connected.set()
                elif data.get('op')=='ping':await ws.send_json({'op':'pong','success':True})
            return ws
        async def setup():
            app=web.Application(); app.router.add_get('/public',handler)
            runner=web.AppRunner(app,shutdown_timeout=.2); await runner.setup(); state['runner']=runner
            site=web.TCPSite(runner,'127.0.0.1',0); await site.start()
            state['port']=site._server.sockets[0].getsockname()[1]; ready.set()
        def serve():
            asyncio.set_event_loop(loop); loop.run_until_complete(setup()); loop.run_forever()
        server=threading.Thread(target=serve,daemon=True); server.start()
        stop=threading.Event(); transport=None; store=None
        try:
            self.assertTrue(ready.wait(5),'Loopback websocket failed to start')
            with tempfile.TemporaryDirectory() as temp:
                store=Store(temp); cfg=Config(block_trades=4,warmup_blocks=2,baseline_blocks=32)
                engine=Engine(cfg,store); symbols=['BTC','ETH','SOL','NEAR','HYPE']
                engine.set_active(symbols,{}, {s:{'status':'Trading','max_leverage':25} for s in symbols},time.time())
                hour=int(time.time()//3600)*3600
                bars=[dict(open_ts=hour-(6-i)*3600,available_ts=hour-(5-i)*3600,
                    open=102,high=110,low=98 if i==4 else 99 if i==5 else 100,close=101,volume=100) for i in range(6)]
                engine.seed_h1('BTC',bars,time.time())
                messages=queue.Queue(); bridge=StreamBridge(messages)
                transport=threading.Thread(target=bridge.run,args=(stop,lambda:set(symbols),f"ws://127.0.0.1:{state['port']}/public"),daemon=True)
                transport.start(); self.assertTrue(connected.wait(5))
                # Distinct real arrival times, no clock/mocked fill or strategy functions.
                for i in range(28):
                    ts=int(time.time()*1000)
                    packet={'topic':'publicTrade.BTCUSDT','data':[
                        {'s':'BTCUSDT','S':'Buy','p':str(101+i*.04),'v':str(1+i//4),'T':ts,'i':str(i)},
                        {'s':'BTCUSDT','S':'Buy','p':'nan','v':'1','T':ts,'i':'malformed'}]}
                    asyncio.run_coroutine_threadsafe(state['ws'].send_json(packet),loop).result(2)
                    time.sleep(.004)
                deadline=time.time()+5
                while time.time()<deadline and 'BTC' not in engine.s['positions']:
                    try:kind,data=messages.get(timeout=.1)
                    except queue.Empty:continue
                    if kind=='connection':engine.reset_flow(*data)
                    elif kind=='trade':
                        row,received,generation=data
                        engine.on_trade(row['coin'],float(row['time'])/1000,float(row['px']),float(row['sz']),
                                        1 if row['side']=='B' else -1,str(row['tid']),received)
                self.assertIn('BTC',engine.s['positions'])
                self.assertGreater(engine.s['positions']['BTC']['opened'],engine.s['positions']['BTC']['signal_ts'])
                engine.checkpoint()
                self.assertTrue((Path(temp)/'checkpoint.json').is_file())
                asyncio.run_coroutine_threadsafe(state['ws'].close(),loop).result(2)
                deadline=time.time()+4
                disconnected=False
                while time.time()<deadline:
                    kind,data=messages.get(timeout=2)
                    if kind=='connection' and data[1] is False:
                        engine.reset_flow(*data); disconnected=True; break
                self.assertTrue(disconnected)
                self.assertIn('BTC',engine.s['positions'])
                self.assertIsNone(engine.snapshot()['positions'][0]['mark'])
                store.db.close(); store=None
        finally:
            stop.set()
            if 'ws' in state:
                try:asyncio.run_coroutine_threadsafe(state['ws'].close(),loop).result(2)
                except Exception:pass
            if transport:transport.join(4)
            if 'runner' in state:asyncio.run_coroutine_threadsafe(state['runner'].cleanup(),loop).result(3)
            loop.call_soon_threadsafe(loop.stop); server.join(3); loop.close()
            if store:store.db.close()


if __name__=='__main__':unittest.main()
