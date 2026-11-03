import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from caterpillar_paper.config import Config
from caterpillar_paper.engine import Engine
from caterpillar_paper.market import Scanner
from caterpillar_paper.storage import Store, atomic_json, encode

SYMBOLS=('BTC','ETH','SOL','NEAR','HYPE')
NOW=36000+100


def candles():
    bars=[]
    for i in range(6):
        low=98 if i==4 else 99 if i==5 else 100
        bars.append(dict(open_ts=(4+i)*3600,available_ts=(5+i)*3600,
                         open=102,high=110,low=low,close=101,volume=100))
    return bars


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.cfg=Config(block_trades=4,warmup_blocks=2,baseline_blocks=32)
        self.store=Store(self.root); self.e=Engine(self.cfg,self.store)
        instruments={s:{'status':'Trading','max_leverage':25} for s in SYMBOLS}
        self.e.set_active(SYMBOLS,{},instruments,NOW)
        for s in SYMBOLS:self.e.seed_h1(s,candles(),NOW)
        self.e.reset_flow(SYMBOLS,True,NOW)
        self.t=NOW; self.ident=0

    def tearDown(self):
        self.store.db.close(); self.temp.cleanup()

    def trade(self,price,side=1,qty=1,symbol='BTC',ts=None,now=None):
        self.ident+=1; self.t=self.t+.01 if ts is None else ts
        return self.e.on_trade(symbol,self.t,price,qty,side,str(self.ident),self.t,now=self.t if now is None else now)

    def open_position(self,symbol='BTC',side=1):
        if side==-1:
            row=self.e.s['symbols'][symbol]
            row['local']={**row['local'],'kind':'HIGH','price':110}
        for i in range(25):self.trade(101+side*i*.04,side=side,qty=1+i//4,symbol=symbol)
        self.assertIn(symbol,self.e.s['positions'])
        return self.e.s['positions'][symbol]

    def test_local_causal_confirmation_and_pivot_separate(self):
        local=self.e.s['symbols']['BTC']['local']
        self.assertEqual(local['kind'],'LOW'); self.assertEqual(local['price'],98)
        self.assertLess(local['pivot_time'],local['confirmed_time'])
        self.assertEqual(local['confirmed_time'],36000)
        self.assertIsNone(local['exact_pivot_timestamp'])

    def test_future_unclosed_candle_rejected(self):
        b=dict(candles()[-1],open_ts=36000)
        with self.assertRaises(ValueError):self.e.seed_h1('BTC',[b],NOW)

    def test_unconfirmed_has_no_entry(self):
        self.e.s['symbols']['BTC']['local']=None
        for i in range(28):self.trade(101+i*.04,qty=1+i//4)
        self.assertFalse(self.e.s['positions']); self.assertEqual(self.e.s['symbols']['BTC']['state'],'WAIT_LOCAL')

    def test_long_entry_next_tick_and_exact_accounting(self):
        p=self.open_position()
        self.assertGreater(p['opened'],p['signal_ts'])
        self.assertEqual(p['side'],1); self.assertEqual(p['margin'],100)
        self.assertEqual(p['notional'],2500); self.assertEqual(p['leverage'],25)
        self.assertAlmostEqual(self.e.s['cash'],500-2500*4.5/10000)
        self.assertGreater(p['entry'],p['entry_mark'])

    def test_short_mirror_and_local_high(self):
        p=self.open_position(side=-1)
        self.assertEqual(p['side'],-1); self.assertLess(p['entry'],p['entry_mark'])

    def test_local_low_blocks_sells(self):
        for i in range(28):self.trade(103-i*.04,side=-1,qty=1+i//4)
        self.assertFalse(self.e.s['positions'])

    def test_local_high_blocks_buys(self):
        self.e.s['symbols']['BTC']['local']['kind']='HIGH'
        self.e.s['symbols']['BTC']['local']['price']=110
        for i in range(28):self.trade(101+i*.04,qty=1+i//4)
        self.assertFalse(self.e.s['positions'])

    def test_volume_without_directional_response_no_entry(self):
        for i in range(28):self.trade(103-i*.03,side=1,qty=1+i//4)
        self.assertFalse(self.e.s['positions'])

    def test_neutral_valid_flow_is_distinct_from_missing(self):
        for i in range(8):self.trade(101,side=1 if i%2 else -1)
        snap=self.e.snapshot(self.t)
        token=snap['tokens'][0]
        self.assertTrue(token['fresh']); self.assertEqual(token['flow']['imbalance'],0)
        self.assertFalse(snap['tokens'][1]['fresh']); self.assertIsNone(snap['tokens'][1]['flow'])

    def test_stale_future_nan_malformed_trade_rejected(self):
        self.assertFalse(self.trade(101,ts=NOW,now=NOW+16))
        self.assertFalse(self.trade(101,ts=NOW+2,now=NOW))
        self.assertFalse(self.trade(float('nan')))
        self.assertFalse(self.e.on_trade('BTC',NOW,101,1,0,'a',NOW,now=NOW))

    def test_duplicate_trade_and_out_of_order_rejected(self):
        args=('BTC',NOW,101,1,1,'same',NOW)
        self.assertTrue(self.e.on_trade(*args,now=NOW))
        self.assertFalse(self.e.on_trade(*args,now=NOW))
        self.assertFalse(self.e.on_trade('BTC',NOW-.1,101,1,1,'other',NOW,now=NOW))

    def test_reconnect_drops_old_flow_and_pending(self):
        self.open_position(); self.e.reset_flow(['BTC'],False,self.t)
        self.assertIsNone(self.e.memory['BTC']['flow'])
        self.assertFalse(self.trade(103))
        self.e.reset_flow(['BTC'],True,self.t)
        self.trade(103); self.assertIsNone(self.e.memory['BTC']['flow'])
        self.assertIn('BTC',self.e.s['positions'])

    def test_single_counter_spike_holds(self):
        self.open_position(); self.trade(101.8,side=-1,qty=50)
        self.assertIn('BTC',self.e.s['positions']); self.assertFalse(self.e.s['closed'])

    def test_real_transfer_exits_and_fees_slippage_reconcile(self):
        p=copy.deepcopy(self.open_position())
        for i in range(17):self.trade(101.9-i*.035,side=-1,qty=10+i//4)
        self.assertNotIn('BTC',self.e.s['positions'])
        closed=self.e.s['closed'][-1]
        self.assertEqual(closed['reason'],'EFFECTIVE_CONTROL_TRANSFER')
        expected=p['quantity']*(closed['exit']-p['entry'])-p['entry_fee']-closed['exit_fee']
        self.assertAlmostEqual(expected,closed['pnl']); self.assertAlmostEqual(500+expected,self.e.s['cash'])
        self.assertEqual(self.e.s['symbols']['BTC']['watch']['side'],1)

    def test_opposite_confirmed_h1_emergency_even_without_flow_warmup(self):
        p=self.open_position(); self.e.reset_flow(['BTC'],True,self.t)
        local=self.e.s['symbols']['BTC']['local']
        self.e.s['symbols']['BTC']['local']={**local,'kind':'HIGH','price':110,'confirmed_time':self.t,'ident':local['ident']+1}
        self.trade(102)
        self.assertEqual(self.e.s['closed'][-1]['reason'],'OPPOSITE_CONFIRMED_H1')

    def test_anchor_invalidation_emergency(self):
        self.open_position(); self.trade(97.99)
        self.assertNotIn('BTC',self.e.s['positions'])
        self.assertIn(self.e.s['closed'][-1]['reason'],('ORIGINAL_LOCAL_INVALIDATED','MODELED_MAINTENANCE_BREACH'))

    def test_liquidation_loss_not_erased_or_capped(self):
        self.open_position(); self.trade(80,side=-1)
        self.assertEqual(self.e.s['closed'][-1]['reason'],'MODELED_MAINTENANCE_BREACH')
        self.assertLess(self.e.s['closed'][-1]['pnl'],-100)

    def test_mfe_mae_marked_and_preserved(self):
        self.open_position(); self.trade(104); self.trade(101)
        p=self.e.s['positions']['BTC']; self.assertGreater(p['mfe'],0); self.assertLess(p['mae'],0)
        self.e.checkpoint(); resumed=Engine(self.cfg,self.store)
        self.assertEqual(p['mfe'],resumed.s['positions']['BTC']['mfe'])
        self.assertIsNone(resumed.snapshot(self.t)['portfolio']['equity'])

    def test_portfolio_margin_limit_with_five_simultaneous_positions(self):
        for s in SYMBOLS[:4]:
            p=self.open_position(s)
            self.trade(p['entry'],symbol=s)
        for i in range(25):self.trade(101+i*.04,qty=1+i//4,symbol=SYMBOLS[4])
        # The fifth nominal 20% allocation cannot fit once entry fees are reserved.
        self.assertEqual(len(self.e.s['positions']),4)
        portfolio=self.e.portfolio(self.t)
        self.assertLessEqual(portfolio['used_margin'],portfolio['equity'])

    def test_compounding_after_realized_pnl(self):
        self.open_position()
        for i in range(17):self.trade(101.9-i*.035,side=-1,qty=10+i//4)
        cash=self.e.s['cash']
        self.open_position('ETH')
        self.assertAlmostEqual(self.e.s['positions']['ETH']['margin'],cash*.2)

    def test_reentry_needs_correction_acceleration_and_same_local(self):
        first=copy.deepcopy(self.open_position())
        for i in range(17):self.trade(101.9-i*.035,side=-1,qty=10+i//4)
        self.assertNotIn('BTC',self.e.s['positions'])
        for i in range(16):self.trade(101.3-i*.02,side=-1,qty=1)
        for i in range(24):self.trade(101.0+i*.04,side=1,qty=10+i//4)
        self.assertIn('BTC',self.e.s['positions'])
        p=self.e.s['positions']['BTC']
        self.assertEqual(p['kind'],'REENTRY'); self.assertEqual(p['cycle_id'],first['cycle_id'])
        self.assertNotEqual(p['position_id'],first['position_id'])

    def test_reentry_blocks_absent_correction_and_wrong_local(self):
        row=self.e.s['symbols']['BTC']; local=row['local']
        row['watch']={'side':1,'local':copy.deepcopy(local),'exit_price':102,'exit_at':NOW,
                      'extreme':102,'depth_bps':0,'cycle_id':'original'}
        for i in range(28):self.trade(102+i*.04,qty=1+i//4)
        self.assertNotIn('BTC',self.e.s['positions'])
        self.assertIn('NO_CORRECTION_DEPTH',row['reason'])
        row['local']={**local,'ident':local['ident']+1}
        for i in range(4):self.trade(103.2+i*.04,qty=20)
        self.assertIsNone(row['watch'])

    def test_checkpoint_roundtrip_same_session_no_duplicate_fill(self):
        self.open_position(); self.e.checkpoint()
        other=Store(self.root/'restore'); other.restore(self.root/'checkpoint.json')
        restored=Engine(self.cfg,other)
        self.assertEqual(restored.s['session_id'],self.e.s['session_id'])
        self.assertEqual(restored.s['positions'],self.e.s['positions'])
        self.assertIsNone(restored.s['symbols']['BTC']['pending'])
        self.assertEqual(other.recent_events(),self.store.recent_events())
        other.db.close()

    def test_corrupt_checkpoint_fails_closed(self):
        self.e.checkpoint(); payload=json.loads((self.root/'checkpoint.json').read_text())
        payload['payload']['state']['cash']=99999
        atomic_json(self.root/'bad.json',payload); other=Store(self.root/'bad')
        with self.assertRaises(ValueError):other.restore(self.root/'bad.json')
        self.assertIsNone(other.load()); other.db.close()

    def test_cash_tampering_and_changed_config_rejected(self):
        self.e.s['cash']=1000
        with self.assertRaises(RuntimeError):self.e.save()
        self.e.s['cash']=500
        with self.assertRaises(ValueError):Engine(replace(self.cfg,leverage=20),self.store)

    def test_universe_frozen_and_held_not_removed_by_new_rank(self):
        self.open_position()
        self.e.set_active(list(reversed(SYMBOLS)),{}, {s:{'status':'Trading','max_leverage':25} for s in SYMBOLS},self.t)
        self.assertEqual(self.e.s['active'],list(SYMBOLS)); self.assertIn('BTC',self.e.s['positions'])

    def test_config_rejects_live_risk_and_unverified_adds(self):
        for kwargs in ({'leverage':50},{'margin_fraction':.3},{'pyramiding':True},{'paper_symbols':('BTC',)},{'block_trades':3.5}):
            with self.assertRaises(ValueError):Config(**kwargs)

    def test_contract_quantity_step_and_maximum_enforced(self):
        self.e.s['symbols']['BTC']['instrument']['lot_size']={'qtyStep':'1','minOrderQty':'1','maxMktOrderQty':'100','minNotionalValue':'5'}
        p=self.open_position()
        self.assertEqual(p['quantity'],int(p['quantity']))
        self.assertLessEqual(p['margin'],100)
        self.e.s['symbols']['ETH']['instrument']['lot_size']={'qtyStep':'1','minOrderQty':'1','maxMktOrderQty':'1','minNotionalValue':'5'}
        for i in range(25):self.trade(101+i*.04,qty=1+i//4,symbol='ETH')
        self.assertNotIn('ETH',self.e.s['positions'])

    def test_missing_subscription_ack_cannot_feed_strategy(self):
        import queue
        from caterpillar_paper.market import StreamBridge
        messages=queue.Queue(); bridge=StreamBridge(messages)
        self.assertEqual(bridge.ingest_trades([{}]),0)
        self.assertTrue(messages.empty())

    def test_restored_reentry_watch_preserves_cycle_and_correction(self):
        self.open_position()
        for i in range(17):self.trade(101.9-i*.035,side=-1,qty=10+i//4)
        self.e.checkpoint()
        watch=copy.deepcopy(self.e.s['symbols']['BTC']['watch'])
        restored=Engine(self.cfg,self.store)
        self.assertEqual(restored.s['symbols']['BTC']['watch'],watch)
        self.assertIsNone(restored.memory['BTC']['flow'])

    def test_snapshot_no_fake_online_or_fake_marks(self):
        self.open_position(); snap=self.e.snapshot(self.t+16)
        self.assertEqual(snap['status'],'STALE'); self.assertIsNone(snap['positions'][0]['mark'])
        self.assertIsNone(snap['portfolio']['equity'])


class ScannerTests(unittest.TestCase):
    def test_dynamic_liquid_top5_and_exclusion_reasons(self):
        scanner=Scanner(Config()); universe={s:{} for s in ('A','B','C','D','E','F','DEAD')}
        def rows(mult,turnover):return [dict(symbol=s+'USDT',lastPrice=str(100+i*mult),turnover24h=str(turnover if s!='DEAD' else 100),bid1Price='100',ask1Price='100.01') for i,s in enumerate(universe,1)]
        self.assertFalse(scanner.rank(rows(0,20_000_000),universe,100)['candidates'])
        rank=scanner.rank(rows(1,20_010_000),universe,130)
        self.assertEqual([r['symbol'] for r in rank['candidates'][:5]],['F','E','D','C','B'])
        self.assertEqual(rank['excluded']['DEAD'],'LOW_TURNOVER')

    def test_missing_stale_and_wide_quotes_excluded(self):
        sc=Scanner(Config()); uni={'A':{}}
        row=dict(symbol='AUSDT',lastPrice='10',turnover24h='20000000',bid1Price='9',ask1Price='11')
        self.assertEqual(sc.rank([row],uni,100)['excluded']['A'],'WIDE_SPREAD')
        row['ask1Price']='NaN'
        self.assertEqual(sc.rank([row],uni,130)['excluded']['A'],'INVALID_OR_MISSING_QUOTE')


if __name__=='__main__':unittest.main()
