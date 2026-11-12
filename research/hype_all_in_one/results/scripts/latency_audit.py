"""Real receive-time audit: project live WS raw frames (HYPE-LOCAL-RAW-*), CryptoHFTData 48h raw (HYPE-RECENT-48H-RAW), public liquidation archive."""
import gzip,json,glob,io,numpy as np,pandas as pd,zstandard,collections,sys
A='/workspace/proj_art'
def pct(x):
    x=np.asarray(x,float); 
    if len(x)==0: return None
    return {'n':int(len(x)),'p50':float(np.percentile(x,50)),'p90':float(np.percentile(x,90)),'p99':float(np.percentile(x,99)),'p999':float(np.percentile(x,99.9)),'max':float(x.max()),'frac_gt_1000ms':float((x>1000).mean()),'frac_gt_500ms':float((x>500).mean())}
res={}
# 1) project live raw frames
lat=collections.defaultdict(list); spans=[]
for f in sorted(glob.glob(A+'/HYPE-LOCAL-RAW-*/chunks/*/HYPE_live_raw_frames.jsonl.gz')):
    first=last=None
    for line in gzip.open(f,'rt'):
        try: r=json.loads(line); m=json.loads(r['raw_text'])
        except Exception: continue
        top=m.get('topic','').split('.')[0]; rt=r['received_ts_ms']
        first=first or rt; last=rt
        if top=='publicTrade':
            for t in m.get('data',[]): lat['ws_publicTrade_recv_minus_T'].append(rt-int(t['T']))
        elif top=='orderbook': 
            if 'cts' in m: lat['ws_orderbook_recv_minus_cts'].append(rt-int(m['cts']))
        elif top=='allLiquidation':
            for t in m.get('data',[]): lat['ws_liquidation_recv_minus_T'].append(rt-int(t['T']))
        elif top in ('tickers',):
            lat['ws_ticker_recv_minus_ts'].append(rt-int(m['ts']))
    if first: spans.append((first,last))
res['project_live_ws']={k:pct(v) for k,v in lat.items()}
res['project_live_ws_capture_hours']=sum((b-a) for a,b in spans)/3.6e6
res['project_live_ws_windows_utc']=[(pd.to_datetime(a,unit='ms').isoformat(),pd.to_datetime(b,unit='ms').isoformat()) for a,b in spans]
print(json.dumps(res['project_live_ws'],indent=0)[:1500],res['project_live_ws_capture_hours'],flush=True)
# 2) CryptoHFTData raw 48h cache
def rp(p):
    b=open(p,'rb').read()
    try: return pd.read_parquet(io.BytesIO(b))
    except Exception: return pd.read_parquet(io.BytesIO(zstandard.ZstdDecompressor().stream_reader(io.BytesIO(b)).read()))
lat2=collections.defaultdict(list)
for kind in ('trades','orderbook','liquidations','ticker'):
    for p in sorted(glob.glob(A+f'/HYPE-RECENT-48H-RAW-*/cache/*_{kind}.parquet'))[:48]:
        try: df=rp(p)
        except Exception as e: continue
        if 'received_time' not in df: continue
        rt=df['received_time'].astype('int64')//1_000_000
        et=None
        for c in ('trade_time','transaction_time','event_time','timestamp'):
            if c in df: df=df[df[c].notna()&df['received_time'].notna()]; rt=df['received_time'].astype('int64')//1_000_000; et=df[c].astype('int64'); break
        if et is None: continue
        if et.iloc[0]>1e15: et=et//1000
        d=(rt-et).values
        if kind=='trades': lat2['chd_trades_frac_recv_after_1s_bar_end'].append(float(((rt//1000)>(et//1000)).mean()))
        lat2[f'chd_{kind}_recv_minus_{c}']+=list(d[::max(1,len(d)//20000)])
res['cryptohftdata_48h']={k:(pct(v) if 'frac' not in k else float(np.mean(v))) for k,v in lat2.items()}
print(json.dumps(res['cryptohftdata_48h'],indent=0),flush=True)
# 3) public liquidation archive
lat3=[];lat3b=[]
for p in sorted(glob.glob('/workspace/data/liq_raw/*_liquidations.parquet.zst')):
    df=rp(p); rt=df['received_time'].astype('int64')//1_000_000
    lat3+=list(rt-df['trade_time'].astype('int64')); lat3b+=list(rt-df['event_time'].astype('int64'))
res['liquidation_archive_recv_minus_trade_time']=pct(lat3); res['liquidation_archive_recv_minus_event_time']=pct(lat3b)
print(res['liquidation_archive_recv_minus_trade_time'],flush=True)
json.dump(res,open('/workspace/data/latency_audit.json','w'),indent=1)
