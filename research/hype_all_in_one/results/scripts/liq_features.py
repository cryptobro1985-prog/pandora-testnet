"""V2 liquidation layer: public CryptoHFTData Bybit HYPEUSDT liquidation archive (WS allLiquidation with received_time).
Causal rule: an event is usable from its RECEIVE second; at decision second t only events with recv_s < t are used.
Missing hourly file (404/err) => window features NaN + mask; never zero-filled."""
import glob,io,json,numpy as np,pandas as pd,zstandard,pickle,sys
from core import T0,DATA,Tape
def rp(p):
    b=open(p,'rb').read()
    try: return pd.read_parquet(io.BytesIO(b))
    except Exception: return pd.read_parquet(io.BytesIO(zstandard.ZstdDecompressor().stream_reader(io.BytesIO(b)).read()))
def load_liq(n_sec):
    st=json.load(open(DATA/'liq_raw/_status_liquidations.json'))
    long_=np.zeros(n_sec+1);short_=np.zeros(n_sec+1);lc=np.zeros(n_sec+1);sc=np.zeros(n_sec+1)
    avail=np.zeros(n_sec+1,bool); ev=[]
    for k,v in st.items():
        if v!='ok': continue
        h=int(pd.Timestamp(k[:8]+' '+k[9:]+':00',tz='UTC').timestamp())-T0
        if 0<=h<n_sec: avail[h:min(n_sec,h+3600)]=True
    for p in sorted(glob.glob(str(DATA/'liq_raw/*_liquidations.parquet.zst'))):
        df=rp(p)
        if len(df)==0: continue
        rs=(df['received_time'].astype('int64')//1_000_000_000-T0).values
        q=df['quantity'].astype(float).values*df['average_price'].astype(float).values
        side=df['side'].astype(str).str.upper().values  # liquidation ORDER side: SELL => long position liquidated
        ev.append(pd.DataFrame({'rs':rs,'notl':q,'side':side,'tt':df['trade_time'].values}))
        for r,n,s_ in zip(rs,q,side):
            if 0<=r<n_sec:
                if s_=='SELL': long_[r]+=n; lc[r]+=1
                else: short_[r]+=n; sc[r]+=1
    cs=lambda a:np.concatenate([[0.0],np.cumsum(a)])
    return dict(cl=cs(long_),cs_=cs(short_),cnl=cs(lc),cns=cs(sc),cav=cs((~avail).astype(float)),events=pd.concat(ev) if ev else None,avail=avail)
class LiqFeat:
    def __init__(self,L,tp):
        self.L=L; self.tp=tp
        self.n=len(L['cl'])-1
    def win(self,arr,a,b):
        a=max(0,a);b=min(self.n,b)
        if b<=a: return np.nan
        if self.L['cav'][b]-self.L['cav'][a]>0: return np.nan  # some hour missing in window
        return arr[b]-arr[a]
    def features(self,side,g,t):
        L=self.L; old=L['cl'] if side=='LOW' else L['cs_']; new=L['cs_'] if side=='LOW' else L['cl']
        oldc=L['cnl'] if side=='LOW' else L['cns']
        f={}
        f['liq_avail']=float(self.L['cav'][min(self.n,t)]-self.L['cav'][max(0,t-3600)]==0)
        for w in (10,60,300,900,3600):
            f[f'liq_old_{w}s']=np.log1p(self.win(old,t-w,t)) if np.isfinite(self.win(old,t-w,t)) else np.nan
        for w in (60,300,900):
            v=self.win(new,t-w,t); f[f'liq_new_{w}s']=np.log1p(v) if np.isfinite(v) else np.nan
        pre60=self.win(old,g-59,g+1); pre300=self.win(old,g-299,g+1); post=self.win(old,g+1,t)
        h1=self.win(old,g-3600,g+1)
        f['liq_old_pre_ext_60s']=np.log1p(pre60) if np.isfinite(pre60) else np.nan
        f['liq_old_pre_ext_300s']=np.log1p(pre300) if np.isfinite(pre300) else np.nan
        f['liq_old_since_ext']=np.log1p(post) if np.isfinite(post) else np.nan
        el=max(1,t-g-1)
        f['liq_old_rate_since_ext_vs_pre300']=(post/el)/(pre300/300+1.0) if np.isfinite(post) and np.isfinite(pre300) else np.nan
        f['liq_burst_pre60_vs_1h']=(pre60/60)/(h1/3600+1.0) if np.isfinite(pre60) and np.isfinite(h1) else np.nan
        c3=self.win(oldc,t-300,t); f['liq_old_count_300s']=c3
        # share of traded notional
        try:
            b,s,_=self.tp.flow(max(0,t-300),t); tot=b+s
            v=self.win(old,t-300,t); f['liq_old_share_300s']=v/tot if np.isfinite(v) and tot>0 else np.nan
        except Exception: pass
        o=self.win(old,g-299,t); n_=self.win(new,g-299,t)
        f['liq_old_minus_new_since_pre300']=(o-n_)/(o+n_+1.0) if np.isfinite(o) and np.isfinite(n_) else np.nan
        return f
if __name__=='__main__':
    tp=Tape(); n=tp.n if hasattr(tp,'n') else len(tp.cbuy)-1
    L=load_liq(n); lf=LiqFeat(L,tp)
    d=pd.read_pickle(DATA/'dataset.pkl'); rows=d['rows']
    add=[lf.features(r['side'],r['member_g'],r['t']) for r in rows]
    pickle.dump(add,open(DATA/'liq_feat_rows.pkl','wb'))
    av=np.mean([a['liq_avail'] for a in add]); print('rows',len(add),'liq_avail_frac',av)
    print('hours ok',int(L['avail'].sum()/3600))
