import json,pathlib,datetime as dt,statistics,collections
ROOT=pathlib.Path.cwd();FEE=.00045
def epoch(s):return dt.datetime.fromisoformat(s).timestamp()
def unit(entry,exit,side):r=exit/entry;return side*(r-1)-FEE*(1+r)
def summary(rows):
 p=[r['pnl'] for r in rows];w=[x for x in p if x>0];l=[x for x in p if x<0]
 return dict(n=len(p),wins=len(w),win_rate=100*len(w)/len(p),pnl=sum(p),profit_factor=sum(w)/-sum(l) if l else None,
  avg_win=statistics.mean(w) if w else 0,avg_loss=statistics.mean(l) if l else 0)
trades=sorted([r['row'] for r in json.load(open(ROOT/'analysis_data/trade_tables.json')) if r['source']=='pump'],key=lambda r:r['opened'])
out={'method':'same_recorded_entries_fixed_inferred_notional_minute_close_exit_counterfactual_not_portfolio_backtest','variants':{}}
for name,hard,failed,slip_bps in [('recorded',None,False,0),('recorded_2bps',None,False,2),('stop35',.0035,False,2),('stop50',.005,False,2),('stop80',.008,False,2),('failed60',.008,True,2)]:
 rows=[];slip=slip_bps/10000
 for t in trades:
  side=t['side'];e=t['entry'];actual=t['exit'];n=t['pnl']/unit(e,actual,side);opened=epoch(t['opened']);closed=epoch(t['closed'])
  bars=json.load(open(ROOT/f"analysis_data/candles/{t['symbol']}_pump_1m.json"))
  path=[(b['T']/1000,float(b['c'])) for b in bars if opened<=b['T']/1000<closed]
  path.append((closed,actual));fill=actual;why=t['reason'];closed_at=closed
  for i,(stamp,price) in enumerate(path):
   move=side*(price/e-1)
   if hard and move<=-hard:fill=price;why='hard_loss_proxy';closed_at=stamp;break
   prior=[p for ts,p in path[:i] if 55<=stamp-ts<=65]
   if failed and stamp-opened>=60 and move<=-.0025 and prior and side*(price/prior[-1]-1)<=-.0015:
    fill=price;why='failed_impulse_price_only_proxy';closed_at=stamp;break
  ef=e*(1+side*slip);xf=fill*(1-side*slip)
  rows.append(dict(symbol=t['symbol'],opened=t['opened'],pnl=n*unit(ef,xf,side),original_pnl=t['pnl'],why=why,holding_seconds=closed_at-opened,notional=n))
 train=rows[:14];test=rows[14:]
 out['variants'][name]={'all':summary(rows),'first14':summary(train),'last9':summary(test),'rows':rows}
 print(name,out['variants'][name]['all'],'last9',out['variants'][name]['last9'])
(ROOT/'analysis_data/pump_replay_summary.json').write_text(json.dumps(out,indent=2))
