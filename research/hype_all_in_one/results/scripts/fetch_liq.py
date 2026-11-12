"""Download public CryptoHFTData Bybit HYPEUSDT liquidation hourly parquet (no API key; 1 req/s)."""
import requests,time,datetime as dt,os,sys,json
OUT='/workspace/data/liq_raw'; API='https://api.cryptohftdata.com/v1/download'
kind=sys.argv[1] if len(sys.argv)>1 else 'liquidations'
start=dt.datetime(2026,4,24);end=dt.datetime(2026,11,12)
hours=[]; t=start
while t<end: hours.append(t); t+=dt.timedelta(hours=1)
status={}
sp=f'{OUT}/_status_{kind}.json'
if os.path.exists(sp): status=json.load(open(sp))
import threading
from concurrent.futures import ThreadPoolExecutor
lock=threading.Lock(); LAST=[0.0]
def pace():
    with lock:
        w=1.05-(time.time()-LAST[0])
        if w>0: time.sleep(w)
        LAST[0]=time.time()
def job(i,h):
    key=h.strftime('%Y%m%d_%H')
    fn=f'{OUT}/{key}_{kind}.parquet.zst'
    if key in status and status[key] in ('ok','404'): return
    if os.path.exists(fn) and os.path.getsize(fn)>0: status[key]='ok'; return
    for attempt in range(5):
        pace()
        try:
            r=requests.get(API,params={'file':f'bybit/{h:%Y-%m-%d}/{h:%H}/HYPEUSDT_{kind}.parquet'},timeout=(10,40))
            if r.status_code in (400,404): status[key]='404'; break
            if r.status_code==429: time.sleep(float(r.headers.get('Retry-After','3'))); continue
            r.raise_for_status(); open(fn,'wb').write(r.content); status[key]='ok'; break
        except Exception as e:
            status[key]='err:'+str(e)[:80]; time.sleep(3)
    if i%100==0:
        with lock: snap=dict(status)
        json.dump(snap,open(sp,'w')); print(i,len(hours),key,status.get(key),flush=True)
with ThreadPoolExecutor(3) as ex: list(ex.map(lambda a:job(*a),enumerate(hours)))
json.dump(status,open(sp,'w')); print('DONE',sum(v=='ok' for v in status.values()),sum(v=='404' for v in status.values()),flush=True)
