import copy,unittest
from strategy_stats import contribution_pct,with_capital_basis,cards_html,empty,KEYS

def sample():
    s=dict(window_start='2026-10-26T19:00:00+00:00',window_end='2026-10-27T03:00:00+00:00',error=None,
        periods={p:{k:empty() for k in KEYS} for p in ('all_time','last_8h')})
    s['periods']['all_time']['local']['realized_pnl']=25.
    s['periods']['last_8h']['local']['realized_pnl']=-5.
    return s

class StrategyRoiTests(unittest.TestCase):
    def test_percentage_has_explicit_common_capital_and_negative_values(self):
        self.assertEqual(contribution_pct(25.,200.),12.5)
        self.assertEqual(contribution_pct(-5.,200.),-2.5)
        self.assertEqual(contribution_pct(0.,200.),0.)

    def test_invalid_capital_never_defaults_to_100(self):
        for capital in (None,0,-1,'bad',float('nan'),float('inf')):
            self.assertIsNone(contribution_pct(25.,capital))
            self.assertIn('база неизвестна',cards_html(sample(),'local',3.,'Local',capital))

    def test_json_keeps_periods_closed_and_current_open_separate(self):
        s=sample();before=copy.deepcopy(s)
        out=with_capital_basis(s,200.,dict(local=-3.))
        self.assertEqual(out['periods']['all_time']['local']['realized_pnl_pct'],12.5)
        self.assertEqual(out['periods']['last_8h']['local']['realized_pnl_pct'],-2.5)
        self.assertEqual(out['strategy_pnl_pct']['local'],dict(realized_pct=12.5,unrealized_pct=-1.5,total_pct=11.))
        self.assertEqual(s,before)

    def test_cards_display_all_time_window_open_and_total_percentages(self):
        page=cards_html(sample(),'local',-3.,'Local',200.)
        for value in ('+12.50%','-2.50%','-1.50%','+11.00%','Вклад в доходность общего капитала'):
            self.assertIn(value,page)

    def test_percentages_do_not_invent_archived_win_rate(self):
        s=sample();r=s['periods']['all_time']['pump_dump'];r.update(realized_pnl=38.,unknown_outcomes=26,win_rate_pct=None)
        out=with_capital_basis(s,200.)
        self.assertIsNone(out['periods']['all_time']['pump_dump']['win_rate_pct'])
        self.assertEqual(out['periods']['all_time']['pump_dump']['realized_pnl_pct'],19.)
        self.assertIn('общий WR неизвестен',cards_html(out,'pump_dump',0.,'Pump',200.))

if __name__=='__main__':unittest.main()
