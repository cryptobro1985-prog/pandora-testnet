"""Alignment of the public liquidation archive vs (a) project live WS capture (HYPE-LOCAL-RAW-*), (b) project 7-layer overlay (HYPE-7LAYER-*)."""
import glob,gzip,json,numpy as np,pandas as pd
from liq_features import rp
A='/workspace/proj_art'
ev=[]
for p in sorted(glob.glob('/workspace/data/liq_raw/*_liquidations.parquet.zst')):
    df=rp(p)
    if len(df): ev.append(pd.DataFrame({'T':df['trade_time'].astype('int64'),'p':df['price'].astype(float),'v':df['quantity'].astype(float),'S':df['side'].str.upper(),'rt':df['received_time'].astype('int64')//1_000_000,'notl':df['quantity'].astype(float)*df['average_price'].astype(float)}))
E=pd.concat(ev).sort_values('T'); res={'archive_events':int(len(E)),'archive_first_utc':str(pd.to_datetime(E['T'].min(),unit='ms')),'archive_last_utc':str(pd.to_datetime(E['T'].max(),unit='ms'))}
# (a) live WS
live=[];wins=[]
for f in sorted(glob.glob(A+'/HYPE-LOCAL-RAW-*/chunks/*/HYPE_live_liquidations.jsonl.gz')):
    for line in gzip.open(f,'rt'):
        m=json.loads(line)
        for d in m.get('data',[]): live.append((int(d['T']),float(d['p']),float(d['v']),d['S'].upper()))
for f in sorted(glob.glob(A+'/HYPE-LOCAL-RAW-*/chunks/*/HYPE_live_raw_frames.jsonl.gz')):
    ts=[json.loads(l)['received_ts_ms'] for l in gzip.open(f,'rt')]
    if ts: wins.append((min(ts),max(ts)))
L=pd.DataFrame(live,columns=['T','p','v','S']).drop_duplicates()
inwin=lambda t:any(a<=t<=b for a,b in wins)
Ew=E[[inwin(t) for t in E['T']]] if len(wins) else E.iloc[:0]
ks=lambda df:set(zip(df['T'],df['p'].round(4),df['v'].round(4)))
kl,ka=ks(L),ks(Ew)
res['live_ws']={'capture_windows':len(wins),'capture_hours':sum(b-a for a,b in wins)/3.6e6,'live_events':len(kl),'archive_events_in_windows':len(ka),'matched':len(kl&ka),
               'live_only':len(kl-ka),'archive_only':len(ka-kl),'side_convention_note':'WS allLiquidation S = position side? compared by T/price/qty only'}
# side convention check on matched
if len(kl&ka):
    Lm=L.set_index(['T']); Em=Ew.set_index(['T'])
    same=0;n=0
    for t,p,v in list(kl&ka)[:500]:
        try: a=Lm.loc[t]['S'];b=Em.loc[t]['S']; a=a if isinstance(a,str) else a.iloc[0]; b=b if isinstance(b,str) else b.iloc[0]; same+=a==b;n+=1
        except Exception: pass
    res['live_ws']['side_label_equal_frac']=same/max(1,n)
# (b) 7LAYER per-minute liquidation sums
rows=[]
for f in glob.glob(A+'/HYPE-7LAYER-*/**/missing_rich_layers_1m.jsonl.gz',recursive=True):
    for line in gzip.open(f,'rt'):
        r=json.loads(line);ft=r['features']
        if 'fullmicro_long_liq_notional_60s' in ft: rows.append((r['ts_ms'],ft.get('fullmicro_long_liq_notional_60s'),ft.get('fullmicro_short_liq_notional_60s')))
R=pd.DataFrame(rows,columns=['ts','long60','short60']).drop_duplicates('ts').sort_values('ts')
T=E['T'].values; cl=np.concatenate([[0],np.cumsum(np.where(E['S']=='SELL',E['notl'],0))]); cs=np.concatenate([[0],np.cumsum(np.where(E['S']!='SELL',E['notl'],0))])
def wsum(c,t0,t1): return c[np.searchsorted(T,t1,'left')]-c[np.searchsorted(T,t0,'left')]
R=R[(R.ts>E['T'].min())&(R.ts<E['T'].max())]
if len(R):
    a_long=np.array([wsum(cl,t-60000,t) for t in R.ts]); a_short=np.array([wsum(cs,t-60000,t) for t in R.ts])
    def cmp(x,y):
        m=np.isfinite(x)&np.isfinite(y); x,y=x[m],y[m]
        return {'n':int(m.sum()),'corr':float(np.corrcoef(x,y)[0,1]) if x.std()>0 and y.std()>0 else None,'exact_rel1pct':float(np.mean(np.abs(x-y)<=0.01*np.maximum(1,np.abs(y)))),'nonzero_minutes_project':int((y>0).sum())}
    res['7layer_1m']={'minutes':int(len(R)),'long_vs_archive_SELL':cmp(a_long,R.long60.values.astype(float)),'short_vs_archive_BUY':cmp(a_short,R.short60.values.astype(float)),
                      'long_vs_archive_BUY(swapped)':cmp(a_short,R.long60.values.astype(float))}
print(json.dumps(res,indent=1)); json.dump(res,open('/workspace/data/liq_alignment.json','w'),indent=1)
