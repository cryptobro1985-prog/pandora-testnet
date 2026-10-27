"""Causal one-minute candle proxy; no reconstructed intrabar fills or order flow."""
import collections, datetime as dt, importlib.util, json, math, pathlib, statistics

ROOT=pathlib.Path.cwd()
spec=importlib.util.spec_from_file_location('local_baseline',pathlib.Path(__file__).resolve().parent/'baseline_local_v5.py')
local=importlib.util.module_from_spec(spec);spec.loader.exec_module(local)
FEE=.00045
SYMBOLS=('HYPE','NEAR','BTC','ETH','SOL')
CONFIGS={
 'v5':dict(cost_floor=False,retention=.50,retest=False,hard_loss=None,volume_rate=False),
 'cost_floor':dict(cost_floor=True,retention=.50,retest=False,hard_loss=None,volume_rate=True),
 'retain65':dict(cost_floor=True,retention=.65,retest=False,hard_loss=None,volume_rate=True),
 'retest':dict(cost_floor=True,retention=.50,retest=True,hard_loss=None,volume_rate=True),
 'retest_risk':dict(cost_floor=True,retention=.50,retest=True,hard_loss=.008,volume_rate=True),
 'risk_only':dict(cost_floor=False,retention=.50,retest=False,hard_loss=.008,volume_rate=False),
 'risk_latched':dict(cost_floor=True,retention=.50,retest=False,hard_loss=.008,volume_rate=True,latch=True),
 'aligned_latched':dict(cost_floor=True,retention=.50,retest=False,hard_loss=.008,volume_rate=True,latch=True,align=True),
 'aligned_retest':dict(cost_floor=True,retention=.50,retest=True,hard_loss=.008,volume_rate=True,latch=True,align=True),
}

def load(s,i):return sorted(json.loads((ROOT/f'analysis_data/candles/{s}_{i}.json').read_text()),key=lambda r:r['t'])
def iso(ms):return dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).isoformat()
def metrics(trades):
 vals=[x['net_pct'] for x in trades];wins=[v for v in vals if v>0];losses=[v for v in vals if v<0]
 equity=peak=dd=0.
 for v in vals:
  equity+=v;peak=max(peak,equity);dd=max(dd,peak-equity)
 return dict(trades=len(vals),wins=len(wins),win_rate_pct=round(100*len(wins)/len(vals),2) if vals else None,
  net_pct_sum=round(sum(vals),5),mean_net_pct=round(statistics.mean(vals),5) if vals else None,
  profit_factor=round(sum(wins)/-sum(losses),3) if losses else None,
  avg_win_pct=round(statistics.mean(wins),5) if wins else None,avg_loss_pct=round(statistics.mean(losses),5) if losses else None,
  drawdown_pct_points=round(dd,5))

def prepare(s):
 m=load(s,'1m');h1=load(s,'1h');m15=load(s,'15m');prepared=[];anchors={}
 for i,b in enumerate(m):
  now=b['t']+1001;hour=b['t']//3600000
  if hour not in anchors:anchors[hour]=local.analyze([r for r in h1 if r['T']<now-1000][-125:],now,s)
  a=anchors[hour];context=local.analyze_h1_context([r for r in h1 if r['T']<now-1000][-6:],now,s)
  closed=[r for r in m15 if r['T']<now-1000][-10:];t15=b['t']//900000*900000
  past=[r for r in m[max(0,i-15):i] if t15<=r['t']<b['t']]
  rows=list(closed)
  if past:
   rows.append(dict(t=t15,T=t15+899999,o=past[0]['o'],h=max(float(r['h']) for r in past),
    l=min(float(r['l']) for r in past),c=past[-1]['c'],v=sum(float(r['v']) for r in past)))
  entry_side=int(a.get('entry_side') or 0)
  raw={};rate={}
  for side in (-1,1):
   raw[side]=local.analyze_m15(rows,now,side)
   adjusted=[dict(r) for r in rows]
   if adjusted and adjusted[-1]['t']==t15 and adjusted[-1]['T']>=now:
    elapsed=(now-t15)/900000
    if elapsed>0:adjusted[-1]['v']=float(adjusted[-1]['v'])/min(1.,elapsed)
   rate[side]=local.analyze_m15(adjusted,now,side)
  prepared.append(dict(t=b['t'],mark=float(b['o']),anchor=a,context=context,raw=raw,rate=rate))
 return prepared

def replay(s,prepared,name,start,end,slip_bps=2):
 cfg=CONFIGS[name];slip=slip_bps/10000;floor=max(.0012,2*FEE+2*slip+.0003) if cfg['cost_floor'] else .0012
 pos=None;watch=None;trades=[];blocked=None
 def close(row,reason):
  nonlocal pos,watch,blocked
  side=pos['side'];exit_fill=row['mark']*(1-side*slip);ratio=exit_fill/pos['entry']
  net=side*(ratio-1)-FEE*(1+ratio)
  trades.append(dict(symbol=s,variant=name,opened=iso(pos['t']),closed=iso(row['t']),side=side,
    entry=pos['entry'],exit=exit_fill,net_pct=100*net,mfe_pct=100*pos['peak'],reason=reason))
  watch=dict(side=side,exit=row['mark'],t=row['t'],origin=pos['anchor'],extreme=row['mark']) if reason in ('profit_lock','m15_pressure') else None
  if reason=='hard_loss' and cfg.get('latch'):blocked=pos['anchor']
  pos=None
 for row in prepared:
  if not start<=row['t']<end:continue
  a=row['anchor'];side=int(a.get('entry_side') or 0) if a.get('ready') else 0
  features=row['rate'] if cfg['volume_rate'] else row['raw']
  if pos:
   move=pos['side']*(row['mark']/pos['entry']-1);pos['peak']=max(pos['peak'],move)
   if side==-pos['side']:close(row,'opposite_h1');continue
   if cfg['hard_loss'] and move<=-cfg['hard_loss']:close(row,'hard_loss');continue
   if pos['peak']>=.0025 and move<=max(floor,cfg['retention']*pos['peak']):close(row,'profit_lock');continue
   f=features[pos['side']]
   if move>=max(.0012,floor if cfg['cost_floor'] else .0012) and f.get('strong_adverse_pressure') and f.get('adverse_score',0)>=4:
    close(row,'m15_pressure');continue
  else:
   if side not in (-1,1):continue
   if cfg.get('latch') and a.get('signal_candle_time')==blocked:continue
   if cfg.get('align') and (side*row['context'].get('return_4h',0)<=0 or side*row['context'].get('return_1h',0)<=0):continue
   f=features[side]
   if watch and watch['side']!=side:watch=None
   ready=local.m15_reentry_ready(side,f)
   if watch:
    watch['extreme']=min(watch['extreme'],row['mark']) if side>0 else max(watch['extreme'],row['mark'])
    if cfg['retest']:
     pullback=-side*(watch['extreme']/watch['exit']-1)
     recovery=side*(row['mark']/watch['extreme']-1)
     extension=side*(row['mark']/watch['exit']-1)
     retest_ready=pullback>=.0012 and recovery>=.0010 and extension<=.0010
     breakout_ready=extension>=floor and int(f.get('candle_time') or 0)>watch['t']//900000*900000
     ready=ready and (retest_ready or breakout_ready)
    else:ready=ready and side*(row['mark']/watch['exit']-1)>0
   if ready:
    pos=dict(side=side,entry=row['mark']*(1+side*slip),t=row['t'],peak=0.,anchor=a.get('signal_candle_time'))
    watch=None
 open_net=0.
 if pos:
  last=next((r for r in reversed(prepared) if start<=r['t']<end),None)
  ratio=last['mark']*(1-pos['side']*slip)/pos['entry'];open_net=100*(pos['side']*(ratio-1)-FEE*(1+ratio))
 return dict(**metrics(trades),open_net_pct=round(open_net,5),marked_total_pct=round(sum(x['net_pct'] for x in trades)+open_net,5)),trades

def main():
 manifest=json.loads((ROOT/'analysis_data/candles_manifest.json').read_text());end=manifest['end_ms']+1
 # Chronological split fixed before parameter comparison; no randomized trade split.
 windows={'train48h':(end-72*3600000,end-24*3600000),'holdout24h':(end-24*3600000,end),'last12h':(end-12*3600000,end)}
 result={'method':'one_minute_open_fills_causal_closed_H1_partial_M15_no_book_or_flow','fee_per_leg':FEE,'slippage_bps_per_leg':2,'windows':{n:[iso(a),iso(b)] for n,(a,b) in windows.items()},'runs':[]};alltrades=[]
 for s in SYMBOLS:
  pre=prepare(s)
  for name in CONFIGS:
   for window,(start,stop) in windows.items():
    summary,trades=replay(s,pre,name,start,stop)
    result['runs'].append(dict(symbol=s,variant=name,window=window,**summary))
    for t in trades:t['window']=window
    alltrades+=trades
  print(s,'done',flush=True)
 (ROOT/'analysis_data/local_replay_summary.json').write_text(json.dumps(result,indent=2))
 (ROOT/'analysis_data/local_replay_trades.json').write_text(json.dumps(alltrades))
 for w in windows:
  print('\n',w)
  for r in result['runs']:
   if r['window']==w:print(r['symbol'],r['variant'],r['trades'],r['win_rate_pct'],r['net_pct_sum'],r['marked_total_pct'],r['profit_factor'])
if __name__=='__main__':main()
