import datetime as dt
import re,sqlite3,unittest
from strategy_stats import performance,cards_html

END=dt.datetime(2026,10,27,3,tzinfo=dt.timezone.utc)

class Result:
    def __init__(self,c):self.c=c
    def fetchall(self):return [dict(r) for r in self.c.fetchall()]

class Database:
    def __init__(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        for name in ('trade_history','pump_trade_history','whale_liq_trade_history','hype_swing_trade_history'):
            self.db.execute('create table '+name+' (symbol text,side integer,opened text,closed text,pnl real,reason text,strategy text)')
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql,args=()):
        # Execute the same grouping/dedup query with only driver/cast adaptation.
        sql=sql.replace('::timestamptz','').replace('%%','%').replace('%s','?')
        args=tuple(v.isoformat() if isinstance(v,dt.datetime) else v for v in args)
        return Result(self.db.execute(sql,args))
    def add(self,table,symbol='HYPE',strategy='local_h1_m15_swing_v5',pnl=2.,closed=None,opened=None):
        self.db.execute('insert into '+table+' values(?,?,?,?,?,?,?)',
            (symbol,1,opened or (END-dt.timedelta(hours=10)).isoformat(),closed or (END-dt.timedelta(hours=1)).isoformat(),pnl,'test',strategy))

class StrategyStatsTests(unittest.TestCase):
    def setUp(self):self.db=Database()
    def stats(self,baseline=None):return performance(lambda:self.db,baseline,END)

    def test_mirrored_journals_count_once_even_when_closed_timestamps_differ(self):
        self.db.add('trade_history')
        self.db.add('hype_swing_trade_history',closed=(END-dt.timedelta(hours=1)+dt.timedelta(microseconds=10)).isoformat())
        r=self.stats()['periods']['last_8h']['local']
        self.assertEqual((r['trades'],r['wins'],r['win_rate_pct'],r['realized_pnl']),(1,1,100.,2.))

    def test_dedicated_row_missing_from_shared_journal_is_retained(self):
        self.db.add('pump_trade_history',symbol='SOL',strategy='pump_dump',pnl=-3.)
        r=self.stats()['periods']['all_time']['pump_dump']
        self.assertEqual((r['trades'],r['losses'],r['realized_pnl']),(1,1,-3.))

    def test_window_uses_close_time_with_start_inclusive_end_exclusive(self):
        for i,hours in enumerate((8,8.01,0)):
            self.db.add('trade_history',symbol=str(i),strategy='news',closed=(END-dt.timedelta(hours=hours)).isoformat())
        r=self.stats()['periods']
        self.assertEqual(r['last_8h']['news']['trades'],1)
        self.assertEqual(r['all_time']['news']['trades'],2)

    def test_wins_losses_zero_and_empty_denominator(self):
        for i,pnl in enumerate((3.,-1.,0.)):self.db.add('trade_history',symbol=str(i),strategy='news',pnl=pnl)
        r=self.stats()['periods']['all_time']['news']
        self.assertEqual((r['wins'],r['losses'],r['breakeven'],r['win_rate_pct'],r['realized_pnl']),(1,1,1,33.33,2.))
        self.assertIsNone(self.stats()['periods']['all_time']['local']['win_rate_pct'])

    def test_restored_pnl_does_not_invent_unknown_trade_outcomes(self):
        self.db.add('trade_history',symbol='SOL',strategy='pump_dump',pnl=2.)
        s=self.stats(dict(restored_closed_trades=26,restored_realized_pnl=38.77,exact_rows_available=False))
        r=s['periods']['all_time']['pump_dump']
        self.assertEqual((r['trades'],r['known_trades'],r['unknown_outcomes'],r['realized_pnl']),(27,1,26,40.77))
        self.assertIsNone(r['win_rate_pct']);self.assertEqual(r['known_win_rate_pct'],100.)
        self.assertEqual(s['periods']['last_8h']['pump_dump']['realized_pnl'],2.)
        page=cards_html(s,'pump_dump',-1.,'Pump/Dump')
        self.assertIn('общий WR неизвестен',page);self.assertIn('-1.0000 USDT',page)

    def test_all_local_versions_group_together_and_breakdown_is_available(self):
        self.db.add('trade_history',strategy='local_m15_swing_v4',pnl=1.)
        self.db.add('trade_history',symbol='NEAR',strategy='local_h1_m15_swing_v5',pnl=2.)
        s=self.stats();self.assertEqual(s['periods']['last_8h']['local']['trades'],2)
        self.assertEqual(len(s['local_last_8h']),2)
        self.assertIn('Самара',cards_html(s,'local',3.,'Local'))

    def test_today_is_not_double_counted(self):
        self.db.add('trade_history');self.db.add('hype_swing_trade_history')
        s=self.stats();self.assertEqual(s['periods']['today_utc']['local']['realized_pnl'],2.)
