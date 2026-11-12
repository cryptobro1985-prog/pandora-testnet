"""Replay Bybit public ob200 daily deltas -> causal 1s L50 book features. State at t uses only updates with ts<=t."""
import sys,zipfile,io,os,math,subprocess,orjson,gzip
from pathlib import Path
import numpy as np
OUT=Path("/workspace/data/ob_feat");OUT.mkdir(parents=True,exist_ok=True)
TMP=Path("/workspace/data/ob")
def process(day):
    out=OUT/f"{day}.npz"
    if out.exists():return "skip"
    z=TMP/f"{day}_HYPEUSDT_ob200.data.zip"
    url=f"https://quote-saver.bycsi.com/orderbook/linear/HYPEUSDT/{day}_HYPEUSDT_ob200.data.zip"
    if not z.exists():
        r=subprocess.run(["curl","-s","-f","--retry","5","-o",str(z)+".part",url])
        if r.returncode!=0:return f"missing {day}"
        os.rename(str(z)+".part",z)
    bids={};asks={}
    from datetime import datetime,timezone
    d0=int(datetime.strptime(day,"%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()*1000)
    grid_t=d0+1000;cols=[];snaps=0;nupd=0;last_ts=None
    def sample(t):
        if not bids or not asks:
            cols.append([t]+[np.nan]*13+[nupd,snaps]);return
        bk=sorted(bids,reverse=True)[:50];ak=sorted(asks)[:50]
        bb=bk[0];ba=ak[0];mid=(bb+ba)/2
        bq=np.array([bids[k] for k in bk]);aq=np.array([asks[k] for k in ak])
        bp=np.array(bk);ap=np.array(ak)
        bn=bq*bp;an=aq*ap
        def within(p,n,bps,side):
            m=(p>=mid*(1-bps/1e4)) if side=="b" else (p<=mid*(1+bps/1e4))
            return float(n[m].sum())
        b5=float(bn[:5].sum());a5=float(an[:5].sum());b50=float(bn.sum());a50=float(an.sum())
        cols.append([t,bb,ba,b5,a5,b50,a50,within(bp,bn,10,"b"),within(ap,an,10,"a"),within(bp,bn,25,"b"),within(ap,an,25,"a"),
                     float(bp[-1]),float(ap[-1]),(ba-bb)/mid*1e4,nupd,snaps])
    with zipfile.ZipFile(z) as zf:
        name=zf.namelist()[0]
        with zf.open(name) as f:
            for line in f:
                m=orjson.loads(line);ts=m["ts"];d=m["data"]
                while grid_t<ts and grid_t<=d0+86400000:
                    sample(grid_t);grid_t+=1000
                if m["type"]=="snapshot":
                    bids.clear();asks.clear();snaps+=1
                for p,q in d.get("b",()):
                    p=float(p);q=float(q)
                    if q==0:bids.pop(p,None)
                    else:bids[p]=q
                for p,q in d.get("a",()):
                    p=float(p);q=float(q)
                    if q==0:asks.pop(p,None)
                    else:asks[p]=q
                nupd+=1
    while grid_t<=d0+86400000:
        sample(grid_t);grid_t+=1000
    arr=np.array(cols,dtype=np.float64)
    np.savez_compressed(out,a=arr,cols=np.array(["t","bb","ba","b5","a5","b50","a50","b10bps","a10bps","b25bps","a25bps","b50_last_px","a50_last_px","spread_bps","nupd","snaps"]))
    z.unlink()
    return f"ok {day} {len(arr)} snaps={snaps}"
if __name__=="__main__":
    for day in sys.argv[1:]:
        try:print(process(day),flush=True)
        except Exception as e:print("ERR",day,repr(e),flush=True)
