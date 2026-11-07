"""Independent tiny numeric JEPA. Future targets exist only during SSL fitting."""
from __future__ import annotations
import argparse,copy,gzip,hashlib,json,math,time
from dataclasses import asdict,dataclass
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import torch
from torch import nn
from .reliability import CheckpointStore,WriterLock,atomic_json
MINUTE=60000
HOUR=60*MINUTE
FEATURES=('body_bps','range_bps','upper_wick','lower_wick','close_position','direction',
          'higher_high','higher_low','flow_imbalance','log_turnover','log_trade_count',
          'return_5m','return_15m','path_efficiency_15m','volatility_15m','flow_price_divergence')
def stamp(day):return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
@dataclass(frozen=True)
class Config:
    context:int=60
    hidden:int=32
    latent:int=16
    horizons:tuple=(1,3,5)
    batch:int=128
    epochs:int=8
    stride:int=5
    learning_rate:float=.0005
    ema:float=.99
    seed:int=20261107
    train_cutoff_ms:int=stamp('2026-10-20')-6*HOUR
    validation_start_ms:int=stamp('2026-10-20')+6*HOUR
    validation_end_ms:int=stamp('2026-10-21')-6*HOUR
class MarketSequence:
    def __init__(self,rows):
        rows=sorted(rows,key=lambda r:int(r['start_ms']));self.rows=rows
        self.ends=np.asarray([int(r['start_ms'])+MINUTE for r in rows],dtype=np.int64)
        if len(set(self.ends))!=len(rows):raise ValueError('duplicate minute bars')
        raw_available=np.asarray([max(int(r['start_ms'])+MINUTE,int(r.get('received_ts_ms') or 0),
            int(r.get('available_at_ms') or 0),int(r.get('source_timestamp_ms') or 0),int(r.get('ts_ms') or 0)) for r in rows],dtype=np.int64)
        self.available=np.asarray([max(raw_available[max(0,i-15):i+1]) for i in range(len(rows))])
        self.valid=np.asarray([not r.get('gap') and r.get('confirm') is not False and
            all(number(r.get(k)) and r[k]>0 for k in ('open','high','low','close')) and
            r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high'] for r in rows])
        self.values=np.zeros((len(rows),len(FEATURES)),dtype=np.float32);self.observed=np.zeros_like(self.values,dtype=bool)
        for i,r in enumerate(rows):
            if not self.valid[i]:continue
            o,h,l,c=[float(r[k]) for k in ('open','high','low','close')];span=max(h-l,1e-9)
            v=[(c/o-1)*1e4,(h/l-1)*1e4,(h-max(o,c))/span,(min(o,c)-l)/span,
               (c-l)/span,float(np.sign(c-o))]+[None]*10
            if i and self.valid[i-1] and self.ends[i]-self.ends[i-1]==MINUTE:
                v[6]=float(h>rows[i-1]['high']);v[7]=float(l>rows[i-1]['low'])
            if r.get('flow_observed') is True and number(r.get('flow_imbalance')):
                v[8]=float(r['flow_imbalance'])
                if not -1<=v[8]<=1:raise ValueError('invalid observed flow')
                v[15]=v[8]-float(np.tanh(v[0]/10))
            if number(r.get('turnover')) and r['turnover']>=0:v[9]=math.log1p(r['turnover'])
            if number(r.get('trade_count')) and r['trade_count']>=0:v[10]=math.log1p(r['trade_count'])
            for n,col in ((5,11),(15,12)):
                if i>=n and self.ends[i]-self.ends[i-n]==n*MINUTE and self.valid[i-n:i+1].all():
                    v[col]=(c/rows[i-n]['close']-1)*1e4
                    if n==15:
                        path=np.asarray([b['close'] for b in rows[i-n:i+1]],dtype=float)
                        v[13]=(path[-1]-path[0])/max(np.abs(np.diff(path)).sum(),1e-9)
                        v[14]=float(np.sqrt(np.mean((np.diff(path)/path[:-1]*1e4)**2)))
            for j,x in enumerate(v):
                if x is not None and math.isfinite(x):self.values[i,j]=x;self.observed[i,j]=True
        self.mean=self.scale=self.x=None
    @classmethod
    def load(cls,path):
        with gzip.open(path,'rt') as f:return cls([json.loads(line) for line in f if line.strip()])
    def normalize(self,cutoff,mean=None,scale=None):
        if mean is None:
            eligible=(self.available<=cutoff)&self.valid
            mean=np.asarray([np.mean(self.values[eligible&self.observed[:,j],j]) if np.any(eligible&self.observed[:,j]) else 0 for j in range(len(FEATURES))],dtype=np.float32)
            scale=np.asarray([max(float(np.std(self.values[eligible&self.observed[:,j],j])),1e-4) if np.any(eligible&self.observed[:,j]) else 1 for j in range(len(FEATURES))],dtype=np.float32)
        self.mean,self.scale=np.asarray(mean,dtype=np.float32),np.asarray(scale,dtype=np.float32)
        values=np.where(self.observed,np.clip((self.values-self.mean)/self.scale,-10,10),0)
        self.x=torch.from_numpy(np.concatenate([values,self.observed.astype(np.float32)],axis=1).astype(np.float32));return self
    def window_ok(self,index,context,as_of):
        start=index-context+1
        return (start>=0 and self.ends[index]-self.ends[start]==(context-1)*MINUTE and self.valid[start:index+1].all() and self.available[start:index+1].max()<=as_of)
    def anchors(self,cfg,start,end):
        return np.asarray([i for i in range(cfg.context-1,len(self.ends)-max(cfg.horizons),cfg.stride)
            if start<=self.ends[i]<end and self.window_ok(i,cfg.context,int(self.ends[i])) and
            all(self.window_ok(i+h,cfg.context,int(self.ends[i+h])) and self.available[i+h]<=end
                and self.ends[i+h]-self.ends[i]==h*MINUTE for h in cfg.horizons)],dtype=np.int64)
    def batch(self,indices,context):return self.x[torch.as_tensor(indices)[:,None]+torch.arange(-context+1,1)]
    def at(self,ts,context):
        i=int(np.searchsorted(self.ends,ts,side='right'))-1
        return i if i>=0 and self.window_ok(i,context,ts) else None
class Encoder(nn.Module):
    def __init__(self,cfg):
        super().__init__();self.gru=nn.GRU(2*len(FEATURES),cfg.hidden,batch_first=True)
        self.projection=nn.Sequential(nn.Linear(cfg.hidden*3,cfg.hidden),nn.GELU(),nn.Linear(cfg.hidden,cfg.latent),nn.LayerNorm(cfg.latent))
    def forward(self,x):
        z,_=self.gru(x);return self.projection(torch.cat([z[:,-1],z[:,-5:].mean(1),z.mean(1)],dim=1))
class NumericJEPA(nn.Module):
    def __init__(self,cfg):
        super().__init__();self.cfg=cfg;self.context=Encoder(cfg);self.target=copy.deepcopy(self.context)
        self.horizon=nn.Embedding(len(cfg.horizons),8)
        self.predictor=nn.Sequential(nn.Linear(cfg.latent+8,cfg.hidden),nn.GELU(),nn.Linear(cfg.hidden,cfg.latent))
        nn.init.zeros_(self.predictor[-1].weight);nn.init.zeros_(self.predictor[-1].bias)
        for p in self.target.parameters():p.requires_grad_(False)
    def forward(self,x):
        z=self.context(x)
        return z,torch.stack([z+self.predictor(torch.cat([z,self.horizon.weight[h].expand(len(x),-1)],dim=1)) for h in range(len(self.cfg.horizons))],1)
    @torch.no_grad()
    def update_target(self):
        for target,current in zip(self.target.parameters(),self.context.parameters()):target.mul_(self.cfg.ema).add_(current,alpha=1-self.cfg.ema)
def objective(model,x,y,masked=True):
    if masked:x=x*(torch.rand(x.shape[:2])>=.1).float().unsqueeze(-1)
    z,pred=model(x)
    with torch.no_grad():target=torch.stack([model.target(a) for a in y],1)
    variance=torch.relu(.15-torch.sqrt(z.var(0,unbiased=False)+1e-5)).square().mean()
    centered=z-z.mean(0);cov=centered.T@centered/max(1,len(z)-1)
    return (pred-target).square().mean()+.1*variance+.002*(cov-torch.diag(torch.diag(cov))).square().mean()
@torch.no_grad()
def predict_latents(model,data,anchors):
    outputs=[[],[],[],[]]
    for start in range(0,len(anchors),128):
        idx=anchors[start:start+128];x=data.batch(idx,model.cfg.context);z,p=model(x)
        values=(z.numpy(),p.numpy(),torch.stack([model.target(data.batch(idx+h,model.cfg.context)) for h in model.cfg.horizons],1).numpy(),model.target(x).numpy())
        for dst,value in zip(outputs,values):dst.append(value)
    if not outputs[0]:raise ValueError('no complete causal windows')
    return tuple(np.concatenate(a) for a in outputs)
def representation_stats(z):
    energy=np.linalg.svd(z-z.mean(0),compute_uv=False)**2;p=energy/max(energy.sum(),1e-12)
    return {'mean_dimension_std':float(z.std(0).mean()),'effective_rank':float(np.exp(-np.sum(p[p>0]*np.log(p[p>0])))),'finite':bool(np.isfinite(z).all())}
def screen(model,data,train,validation):
    z,pred,target,persist=predict_latents(model,data,validation)
    _,_,training_targets,_=predict_latents(model,data,train[:min(len(train),1024)])
    mean=training_targets.mean(0,keepdims=True)
    mse=float(np.mean((pred-target)**2));base=float(np.mean((persist[:,None]-target)**2));constant=float(np.mean((mean-target)**2));stats=representation_stats(z)
    improves=mse<base*.99 and mse<constant*.99
    return {'prediction_mse':mse,'persistence_mse':base,'training_mean_mse':constant,
        'beats_both_trivial_baselines':improves,'representation':stats,
        'passed':bool(improves and stats['mean_dimension_std']>.05 and stats['effective_rank']>3 and stats['finite']),
        'per_horizon':{str(h):{'prediction_mse':float(np.mean((pred[:,i]-target[:,i])**2)),'persistence_mse':float(np.mean((persist-target[:,i])**2))} for i,h in enumerate(model.cfg.horizons)},
        'validation_windows':len(validation),'scope':'held-out SSL latent space, not Local accuracy'}
def train(data,cfg,out,source_hash):
    torch.set_num_threads(2);torch.manual_seed(cfg.seed);out=Path(out);out.mkdir(parents=True,exist_ok=True);data.normalize(cfg.train_cutoff_ms)
    train_idx=data.anchors(cfg,0,cfg.train_cutoff_ms);val_idx=data.anchors(cfg,cfg.validation_start_ms,cfg.validation_end_ms)
    if len(train_idx)<128 or len(val_idx)<32:raise ValueError('insufficient disjoint complete windows')
    model=NumericJEPA(cfg);optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=cfg.learning_rate)
    store=CheckpointStore(out/'ssl_checkpoint');saved=store.load();history=[];epoch=0
    if saved:
        if saved['config']!=asdict(cfg) or saved['dataset_sha256']!=source_hash:raise ValueError('checkpoint/data/config mismatch; refuse overwrite')
        model.load_state_dict(saved['model']);optimizer.load_state_dict(saved['optimizer']);torch.set_rng_state(saved['torch_rng']);epoch=saved['epoch'];history=saved['history']
    if epoch==cfg.epochs and (out/'JEPA_SCREEN.json').exists():
        cached=json.loads((out/'JEPA_SCREEN.json').read_text())
        if cached.get('dataset_sha256')!=source_hash:raise ValueError('screen input mismatch')
        model.eval();return model,cached
    started=time.monotonic()
    while epoch<cfg.epochs:
        order=torch.randperm(len(train_idx)).numpy();losses=[];model.train()
        for j in range(0,len(order),cfg.batch):
            idx=train_idx[order[j:j+cfg.batch]];x=data.batch(idx,cfg.context);y=[data.batch(idx+h,cfg.context) for h in cfg.horizons]
            optimizer.zero_grad(set_to_none=True);loss=objective(model,x,y)
            if not torch.isfinite(loss):raise RuntimeError('nonfinite JEPA objective')
            loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1);optimizer.step();model.update_target();losses.append(float(loss.detach()))
        epoch+=1;history.append({'epoch':epoch,'training_objective':float(np.mean(losses))})
        store.save({'schema':1,'model':model.state_dict(),'optimizer':optimizer.state_dict(),'config':asdict(cfg),
            'epoch':epoch,'torch_rng':torch.get_rng_state(),'history':history,'dataset_sha256':source_hash,
            'normalization':{'mean':data.mean,'scale':data.scale},'training_cutoff_ms':cfg.train_cutoff_ms,
            'downstream_heads':None,'forward_results':[],'promoted':False,'role':'online_challenger_only',
            'features':FEATURES,'torch_version':torch.__version__});print(json.dumps(history[-1]),flush=True)
    model.eval();metrics=screen(model,data,train_idx,val_idx)
    metrics['loss_decreases']=bool(history[-1]['training_objective']<history[0]['training_objective']);metrics['passed']=bool(metrics['passed'] and metrics['loss_decreases'])
    report={'schema':'PANDORA-NUMERIC-JEPA-v1','config':asdict(cfg),'features':FEATURES,'training_windows':len(train_idx),
        'history':history,'screen':metrics,'dataset_sha256':source_hash,'elapsed_seconds':time.monotonic()-started,
        'parameters':sum(p.numel() for p in model.parameters()),'hardware':'CPU,2threads','promoted':False,'champion_unchanged':True,'real_orders':False,
        'historical_receipt_assumption':'completed minute availability at close where actual receipt is absent',
        'subminute_targets':'unavailable from minute archive; no 5s/15s/30s values fabricated',
        'next':'frozen two-probe chronological comparison' if metrics['passed'] else 'STOP: preserve negative result; no probes, scaling or forward promotion'}
    atomic_json(out/'JEPA_SCREEN.json',report);return model,report
def diagnostics(z,previous=None,previous_previous=None,predictions=None,matured_target=None,elapsed_seconds=1.):
    z=np.asarray(z,dtype=float);result={'latent_norm':float(np.linalg.norm(z)),'prediction_error':None}
    if previous is not None:
        result['latent_velocity']=float(np.linalg.norm(z-np.asarray(previous)))/max(float(elapsed_seconds),1e-9);result['latent_distance']=result['latent_velocity']
        if previous_previous is not None:result['latent_acceleration']=float(np.linalg.norm(z-2*np.asarray(previous)+np.asarray(previous_previous)))/max(float(elapsed_seconds)**2,1e-9)
    if predictions is not None:
        result['horizon_disagreement']=float(np.std(predictions,axis=0).mean());result['uncertainty_interpretation']='dispersion, not calibrated posterior uncertainty'
    if matured_target is not None and predictions is not None:result['prediction_error']=float(np.mean((np.asarray(predictions)-np.asarray(matured_target))**2))
    return result
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--minutes',type=Path,default=Path('artifacts/history_30d_local116/compact_1m.jsonl.gz'));ap.add_argument('--output',type=Path,default=Path('artifacts/jepa_research'));args=ap.parse_args()
    with WriterLock(args.output/'.jepa_writer.lock'):train(MarketSequence.load(args.minutes),Config(),args.output,digest(args.minutes))
if __name__=='__main__':main()
