"""Fail-closed historical execution manifest audit. Research only."""
import csv,json,sys
from collections import Counter
REQUIRED=('trade_id','side','anchor_ts_ms','confirmation_ts_ms','entry_ts_ms','entry_vwap','stop_price','exit_ts_ms','exit_reason','quote_event_count','mark_event_count','l50_event_count','fee_entry','fee_exit','funding','max_quote_gap_ms','max_mark_gap_ms','max_l50_gap_ms','liquidation_price','mark_min','mark_max','source_hash')
def audit(rows):
 seen=set(); reasons=Counter(); accepted=[]
 for r in rows:
  if any(k not in r or str(r[k]).strip()=='' for k in REQUIRED):
   reasons['MISSING_FIELDS']+=1;continue
  errors=[]
  try:
   if r['trade_id'] in seen: errors.append('DUPLICATE_ID')
   seen.add(r['trade_id'])
   side=r['side'];assert side in ('LONG','SHORT')
   a,c,e,x=[int(r[k]) for k in ('anchor_ts_ms','confirmation_ts_ms','entry_ts_ms','exit_ts_ms')]
   if not a<c<=e<x:errors.append('NONCAUSAL_TIMELINE')
   p,s,l=[float(r[k]) for k in ('entry_vwap','stop_price','liquidation_price')]
   if min(p,s,l)<=0:errors.append('INVALID_PRICE')
   if (side=='LONG' and not l<s<p) or (side=='SHORT' and not p<s<l):errors.append('STOP_NOT_BEFORE_LIQ')
   if any(int(r[k])<2 for k in ('quote_event_count','mark_event_count','l50_event_count')):errors.append('MISSING_EVENT_STREAM')
   if any(int(r[k])>60000 for k in ('max_quote_gap_ms','max_mark_gap_ms','max_l50_gap_ms')):errors.append('UNRESOLVED_GAP')
   if (side=='LONG' and float(r['mark_min'])<=l) or (side=='SHORT' and float(r['mark_max'])>=l):errors.append('POSSIBLE_LIQUIDATION')
   if min(float(r['fee_entry']),float(r['fee_exit']))<0:errors.append('INVALID_FEE')
   float(r['funding'])
   if len(r['source_hash'])<16:errors.append('UNVERIFIABLE_SOURCE')
  except (ValueError,TypeError,AssertionError,OverflowError):errors.append('INVALID_VALUES')
  if errors:reasons.update(set(errors))
  else:accepted.append(r['trade_id'])
 return {'rows':len(rows),'replay_eligible':len(accepted),'rejected':len(rows)-len(accepted),'reasons':dict(reasons),'eligible_ids':accepted}
if __name__=='__main__':
 if len(sys.argv)==2:
  with open(sys.argv[1],newline='') as f:rows=list(csv.DictReader(f))
  result=audit(rows);print(json.dumps(result,indent=2));sys.exit(0 if result['rejected']==0 and result['rows']>0 else 2)
 base=dict(trade_id='a',side='LONG',anchor_ts_ms=100,confirmation_ts_ms=200,entry_ts_ms=201,entry_vwap=100,stop_price=99,exit_ts_ms=300,exit_reason='STOP',quote_event_count=10,mark_event_count=10,l50_event_count=10,fee_entry=.01,fee_exit=.01,funding=0,max_quote_gap_ms=1000,max_mark_gap_ms=1000,max_l50_gap_ms=1000,liquidation_price=96,mark_min=98,mark_max=101,source_hash='0123456789abcdef')
 assert audit([base])['replay_eligible']==1
 for changes,reason in [({'confirmation_ts_ms':202},'NONCAUSAL_TIMELINE'),({'stop_price':95},'STOP_NOT_BEFORE_LIQ'),({'max_quote_gap_ms':180000},'UNRESOLVED_GAP'),({'mark_min':95},'POSSIBLE_LIQUIDATION'),({'l50_event_count':0},'MISSING_EVENT_STREAM'),({'source_hash':'x'},'UNVERIFIABLE_SOURCE')]:
  assert reason in audit([{**base,**changes}])['reasons']
 assert audit([base,base])['replay_eligible']==1
 assert audit([{'trade_id':'b'}])['rejected']==1
 print('9 deterministic manifest-gate checks passed; no historical fills claimed')
