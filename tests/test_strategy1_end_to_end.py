"""Synthetic Bybit-wire integration over a real local WebSocket and PostgreSQL.

This proves software execution, not real-exchange latency, signal quality or PnL.
No trade-flow, candidate, allocator, close or accounting functions are mocked.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from aiohttp import web
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import app
from bybit_market_stream import run_bybit_stream
from market_data import RollingMarketData


class BybitFixtureServer:
    def __init__(self):
        self.ready=threading.Event();self.connected=threading.Event();self.socket=None
        self.topics=set();self.loop=asyncio.new_event_loop();self.trade_id=0
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
        if not self.ready.wait(5):raise RuntimeError('fixture server did not start')

    async def handler(self,request):
        ws=web.WebSocketResponse();await ws.prepare(request);self.socket=ws;self.connected.set()
        async for message in ws:
            if message.type!=web.WSMsgType.TEXT:continue
            payload=json.loads(message.data)
            if payload.get('op')=='subscribe':
                self.topics.update(payload.get('args') or [])
                await ws.send_json({'op':'subscribe','success':True,'req_id':payload.get('req_id')})
            elif payload.get('op')=='ping':await ws.send_json({'op':'pong','success':True})
        return ws

    def run(self):
        asyncio.set_event_loop(self.loop)
        async def start():
            application=web.Application();application.router.add_get('/public',self.handler)
            self.runner=web.AppRunner(application);await self.runner.setup()
            site=web.TCPSite(self.runner,'127.0.0.1',0);await site.start()
            self.port=site._server.sockets[0].getsockname()[1];self.ready.set()
        self.loop.run_until_complete(start());self.loop.run_forever()

    def trade(self,symbol,side,size,price=100):
        self.trade_id+=1
        frame={'topic':'publicTrade.'+symbol+'USDT','data':[{'s':symbol+'USDT','S':'Buy' if side>0 else 'Sell',
               'p':str(price),'v':str(size),'T':int(time.time()*1000),'i':'fixture-'+str(self.trade_id)}]}
        asyncio.run_coroutine_threadsafe(self.socket.send_json(frame),self.loop).result(5)

    def close(self):
        asyncio.run_coroutine_threadsafe(self.runner.cleanup(),self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop);self.thread.join(5);self.loop.close()


@unittest.skipUnless(os.getenv('PANDORA_TEST_DATABASE_URL_FILE'),'isolated PostgreSQL required')
class TenMarketExecutionTests(unittest.TestCase):
    def setUp(self):
        self.url=Path(os.environ['PANDORA_TEST_DATABASE_URL_FILE']).read_text().strip()
        self.schema='wire_'+uuid.uuid4().hex
        with psycopg.connect(self.url,autocommit=True) as db:
            db.execute(sql.SQL('create schema {}').format(sql.Identifier(self.schema)))
        self.saved=copy.deepcopy(app.S)
        self.connect=lambda:psycopg.connect(self.url,autocommit=True,row_factory=dict_row,options='-c search_path='+self.schema)
        self.patches=[patch.object(app,'pg',self.connect)]
        self.patches[0].start();app.pinit()
        self.store=app.EngineStore(self.connect);self.store.migrate();self.assertTrue(self.store.claim())
        self.obs=RollingMarketData(freshness_seconds=60,max_seen_per_symbol=65536)
        self.patches.extend([patch.object(app,'STORE',self.store),patch.object(app,'MARKET_OBS',self.obs)])
        for item in self.patches[1:]:item.start()
        app.S.update(engine_active=True,mode='PAPER_ONLY',orders_enabled=False,local_v12_positions={},
                     local_experiment_watch={},local_h1_direction={},_local4_analysis={},_prices={},_price_received_epoch={},
                     local_experiment_equity=500.,local_experiment_realized_pnl=0.,last_checkpoint=app.now())
        stamp=time.time();hour=3600000;last=(int(stamp*1000)//hour)*hour
        self.sides={symbol:1 if i%2==0 else -1 for i,symbol in enumerate(app.LOCAL_EXPERIMENT_SYMBOLS)}
        values=[(100,102,95,99),(99,101,94,98),(98,100,93,97),(97,99,92,96),(96,98,85,89),(89,96,87,95)]
        for symbol,side in self.sides.items():
            prices=values if side>0 else [(200-o,200-l,200-h,200-c) for o,h,l,c in values]
            rows=[dict(t=last-(6-i)*hour,T=last-(5-i)*hour-1,o=o,h=h,l=l,c=c,v=100) for i,(o,h,l,c) in enumerate(prices)]
            analysis=app.local_h1_direction(rows,int(stamp*1000),symbol)
            self.assertEqual(analysis['entry_side'],side)
            app.S['_local4_analysis'][symbol]=analysis
        app.S['_bybit_instruments']={symbol:dict(max_leverage=10 if symbol=='HYPE' else 25,observed_at=stamp) for symbol in self.sides}
        self.server=BybitFixtureServer();self.stop=threading.Event();self.reports=[]
        self.transport=threading.Thread(target=run_bybit_stream,args=(self.obs,self.stop,lambda:set(self.sides),self.reports.append),
               kwargs={'url':f'ws://127.0.0.1:{self.server.port}/public','worker_name':'fixture',
                       'on_trade_mids':app.accept_market_prices},daemon=True)
        self.transport.start()
        self.wait_for(lambda: self.server.topics=={'publicTrade.'+s+'USDT' for s in self.sides})
        self.assertTrue(self.server.connected.is_set())

    def wait_for(self,predicate,seconds=5):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if predicate():return
            time.sleep(.005)
        self.fail('timeout waiting for WebSocket fixture: '+str(self.reports[-1:] or self.obs.stats()))

    def send(self,symbol,side,size,price=100):
        count=self.obs.stats()['accepted'];self.server.trade(symbol,side,size,price)
        self.wait_for(lambda:self.obs.stats()['accepted']>count)
        self.wait_for(lambda:app.S.get('_prices',{}).get(symbol)==price)
        self.assertTrue(self.obs.flow_context(symbol)['trade_data_fresh'])
        app.S['last_checkpoint']=app.now()  # bounded fixture heartbeat after committed schema/lease setup

    def evidence(self,name,payload):
        directory=os.getenv('PANDORA_VALIDATION_OUTPUT_DIR')
        if directory:
            path=Path(directory);path.mkdir(parents=True,exist_ok=True)
            (path/name).write_text(json.dumps({'synthetic_fixture':True,'live_exchange':False,**payload},indent=2)+'\n')

    def tearDown(self):
        if hasattr(self,'stop'):self.stop.set()
        if hasattr(self,'server'):self.server.close()
        if hasattr(self,'transport'):self.transport.join(5);self.assertFalse(self.transport.is_alive())
        self.store.release()
        for item in reversed(self.patches):item.stop()
        app.S.clear();app.S.update(self.saved)
        with psycopg.connect(self.url,autocommit=True) as db:
            db.execute(sql.SQL('drop schema {} cascade').format(sql.Identifier(self.schema)))

    def test_every_market_opens_exits_and_reenters_from_actual_wire_observations(self):
        for symbol,side in self.sides.items():
            self.send(symbol,side,1)
            entry=100+side*.1
            self.send(symbol,side,1,entry)
            app.local4_fast_entries({symbol:entry})
            self.assertIn(symbol,app.S['local_v12_positions'])
            self.assertEqual(app.S['local_v12_positions'][symbol]['side'],side)
            if symbol=='HYPE':self.assertEqual(app.S['local_v12_positions'][symbol]['leverage'],10)
            tiny=entry-side*.05
            self.send(symbol,-side,.01,tiny)
            app.local_experiment_mark_positions({symbol:tiny})
            self.assertIn(symbol,app.S['local_v12_positions'])
            best=entry+side*.1
            self.send(symbol,side,3,best)
            app.local_experiment_mark_positions({symbol:best})
            self.assertIn(symbol,app.S['local_v12_positions'])
            exit_price=best-side*.4
            self.send(symbol,-side,9,exit_price)
            app.local_experiment_mark_positions({symbol:exit_price})
            self.assertNotIn(symbol,app.S['local_v12_positions'])
            extreme=exit_price-side*.3
            for control,size,price in [(-side,27,extreme),(side,81,extreme+side*.2),(-side,243,extreme+side*.1)]:
                self.send(symbol,control,size,price)
                app.local4_fast_entries({symbol:price})
                self.assertNotIn(symbol,app.S['local_v12_positions'])
            resumed=extreme+side*.5
            self.send(symbol,side,729,resumed)
            app.local4_fast_entries({symbol:resumed})
            self.assertEqual(app.S['local_v12_positions'][symbol]['features']['entry_kind'],'REENTRY')
            final=extreme-side*.1
            self.send(symbol,-side,2187,final)
            app.local_experiment_mark_positions({symbol:final})
            self.assertNotIn(symbol,app.S['local_v12_positions'])
        with self.connect() as db:
            trades=db.execute('select symbol,count(*) n,sum(pnl) pnl from local_v12_trade_history group by symbol').fetchall()
            self.assertEqual({r['symbol']:r['n'] for r in trades},{s:2 for s in self.sides})
            self.assertEqual(db.execute('select count(*) n from local_v12_positions').fetchone()['n'],0)
            account=db.execute('select equity,realized_pnl from local_v12_account_state where id=1').fetchone()
            pnl=sum(r['pnl'] for r in trades)
            self.assertAlmostEqual(account['equity'],500+pnl)
            self.assertAlmostEqual(account['realized_pnl'],pnl)
            for kind in ('local_experiment_trade_opened','local_experiment_trade_closed'):
                self.assertEqual(db.execute('select count(*) n from audit_journal where kind=%s',(kind,)).fetchone()['n'],20)
        self.assertEqual(self.obs.stats()['accepted'],100)
        self.evidence('ten-market-wire.json',{'tokens':{r['symbol']:{'opens':2,'closes':r['n'],'reentries':1,
            'pnl_net_fees':r['pnl']} for r in trades},'accepted_frames':100,'closed_trades':20,
            'starting_equity':500,'ending_equity':account['equity'],'realized_pnl':pnl,
            'transport':'real loopback WebSocket carrying synthetic Bybit publicTrade frames'})

    def test_simultaneous_entries_respect_real_margin_including_modeled_fees(self):
        prices={}
        for symbol,side in self.sides.items():
            self.send(symbol,side,1)
            prices[symbol]=100+side*.1
            self.send(symbol,side,1,prices[symbol])
        app.local4_fast_entries(prices)
        equity,used,free=app._local_experiment_margin_state()
        self.assertGreater(len(app.S['local_v12_positions']),0)
        self.assertLessEqual(used,equity+1e-7)
        self.assertGreaterEqual(free,0)
        self.assertLess(len(app.S['local_v12_positions']),10)  # 20% total-equity sizing exhausts $500
        rejected=set(self.sides)-set(app.S['local_v12_positions'])
        for symbol in rejected:self.assertEqual(app.S['strategy1_executor_rejections'][symbol]['reason'],'INSUFFICIENT_FREE_MARGIN')
        self.evidence('margin-capacity.json',{'simultaneous_positions':len(app.S['local_v12_positions']),
            'equity_after_modeled_fees':equity,'reserved_margin':used,'free_margin':free,
            'rejected':{symbol:app.S['strategy1_executor_rejections'][symbol]['reason'] for symbol in sorted(rejected)},
            'sizing':'20% current equity, capped by free margin with fee reserve'})
