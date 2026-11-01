"""Deterministic software contracts; synthetic inputs, no PnL optimization."""
import copy
import json
import os
import time
import unittest

from accounting import paper_pnl
from pandora_flow import summarize
from pandora_locals import live_locals, execution_anchor
from pandora_scanner import LiveScanner
from pandora_win_core import allocation, apply_add, pyramid_decision, mark_metrics
from tests.archive_v1 import pandora_end_to_end_v1 as fixture
from tests.test_pandora_restoration import bars, BASE, H
import app


@unittest.skipUnless(os.getenv('PANDORA_TEST_DATABASE_URL_FILE'),'isolated PostgreSQL required')
class PersistentPyramidTests(unittest.TestCase):
    setUp=fixture.SelectedMarketExecutionTests.setUp
    tearDown=fixture.SelectedMarketExecutionTests.tearDown
    send=fixture.SelectedMarketExecutionTests.send
    wait_for=fixture.SelectedMarketExecutionTests.wait_for

    def test_real_wire_add_is_atomic_idempotent_and_survives_runtime_restart(self):
        from pandora_runtime import PandoraRuntime
        symbol='BTC';self.send(symbol,1,1);self.send(symbol,1,1,100.1)
        app.pandora_flow_fast_entries({symbol:100.1})
        self.assertIn(symbol,app.S['pandora_win_positions'])
        self.send(symbol,1,20,101)
        flow=self.obs.flow_context(symbol)
        anchor=app.S['_pandora_analysis'][symbol]
        before=app.S['pandora_equity']
        self.assertTrue(app.WIN.pyramid(symbol,anchor,flow,101))
        self.assertFalse(app.WIN.pyramid(symbol,anchor,flow,101))
        app.restore_state()
        restored=PandoraRuntime(app)
        p=app.S['pandora_win_positions'][symbol]
        self.assertEqual(p['features']['pyramid_level'],1)
        self.assertEqual(len(p['features']['pyramid_adds']),1)
        self.assertEqual(app.S['pandora_equity'],before)
        with self.connect() as db:
            self.assertEqual(db.execute('select count(*) n from pandora_win_pyramid_adds').fetchone()['n'],1)
            self.assertEqual(db.execute("select count(*) n from pandora_win_audit_journal where kind='pandora_ADD_LONG'").fetchone()['n'],1)
        self.assertFalse(restored.pyramid(symbol,anchor,flow,101))
        self.assertIsNotNone(app.pandora_close(symbol,101,'operator_paper_close'))
        self.assertIsNone(app.pandora_close(symbol,101,'operator_paper_close'))

    def test_runtime_holds_bounce_then_closes_and_reverses_only_with_new_structure(self):
        symbol='BTC'
        self.send(symbol,1,1,100)
        self.send(symbol,1,1,100.1)
        app.WIN.cycle({symbol:100.1})
        self.assertEqual(app.S['pandora_win_positions'][symbol]['side'],1)
        self.send(symbol,-1,.01,100.05)
        app.WIN.cycle({symbol:100.05})
        self.assertIn(symbol,app.S['pandora_win_positions'])
        self.send(symbol,1,3,100.2)
        app.WIN.cycle({symbol:100.2})
        self.send(symbol,-1,90,99)
        app.WIN.cycle({symbol:99})
        self.assertIn(symbol,app.S['pandora_win_positions'])
        time.sleep(3.05)
        self.send(symbol,-1,1,99)
        app.WIN.cycle({symbol:99})
        self.assertNotIn(symbol,app.S['pandora_win_positions'])
        self.assertIn(symbol,app.S['pandora_watch'])
        old=copy.deepcopy(app.S['_pandora_analysis'][symbol])
        # Feed a new confirmed structure through the executor boundary. Local
        # causality itself is exercised separately against actual H1/M15 bars.
        opposite={**old,'entry_side':-1,'pivot_type':'LOCAL_HIGH','pivot_price':101,
                  'signal_candle_time':old['signal_candle_time']+1,
                  'pivot_candle_time':old['pivot_candle_time']+1}
        app.S['_pandora_analysis'][symbol]=opposite
        app.S['pandora_win_h1_direction'][symbol]=opposite
        app.S['_pandora_h1_runtime_verified'][symbol].update(
            entry_side=-1,signal_candle_time=opposite['signal_candle_time'],
            pivot_candle_time=opposite['pivot_candle_time'])
        with self.connect() as db:
            db.execute('update pandora_win_h1_direction set analysis=%s::jsonb where symbol=%s',
                       (json.dumps(opposite),symbol))
        app.WIN.cycle({symbol:99})
        self.assertEqual(app.S['pandora_win_positions'][symbol]['side'],-1)
        with self.connect() as db:
            self.assertEqual(db.execute("select count(*) n from pandora_win_audit_journal where kind='pandora_REVERSE_LONG_TO_SHORT'").fetchone()['n'],1)
            self.assertEqual(db.execute('select count(*) n from pandora_win_trade_history').fetchone()['n'],1)
        app.WIN.cycle({symbol:99})
        with self.connect() as db:
            self.assertEqual(db.execute("select count(*) n from pandora_win_audit_journal where kind='pandora_REVERSE_LONG_TO_SHORT'").fetchone()['n'],1)

