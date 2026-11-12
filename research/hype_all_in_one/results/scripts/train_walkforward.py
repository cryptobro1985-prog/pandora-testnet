"""Early real-H1-Local detector: chronological walk-forward with purge, frozen thresholds.

Experts (re-using the project's stack):
  QUANTUM  = LightGBM nonlinear tabular + repo QuantLocalExpert MLP (value+mask, no zero-imputation semantics)
  FIN-JEPA = repo HypeFinJEPA over the member's causal decision-point sequence
  LOCAL-ONLY = repo River LocalOnlyModel (side x stage heads)
  CORTEX   = repo CortexRelationshipExpert relationship memory (train-only)
  META     = logistic meta-controller fit on time-blocked out-of-fold expert probabilities (train only)
Thresholds: calibration segment only (+ train OOF false scores for SAFE), frozen before test.
Research/paper only. Real orders OFF.
"""
from __future__ import annotations
import math,pickle,json,sys,time,random,copy,os
from pathlib import Path
from collections import defaultdict
import numpy as np,torch
from torch import nn
import torch.nn.functional as F
import lightgbm as lgb
from sklearn.linear_model import LogisticRegression
sys.path.insert(0,"/workspace/pandora-testnet")
from research.hype_local_only.fin_jepa_adapter import HypeFinJEPA
from research.hype_local_only.train_local_ensemble_30d import QuantLocalExpert
from research.hype_local_only.model import LocalOnlyModel
from research.hype_local_only.train_unified_local_intelligence_v2 import CortexRelationshipExpert
from research.hype_quant.feature_contract import INPUT_IDS,TARGET_IDS,METADATA_IDS
from core import T0,DATA
from datetime import datetime,timezone

SEED=20261112
torch.set_num_threads(6)
def S(iso):return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp())-T0
B={"May":S("2026-05-01"),"Jun":S("2026-06-01"),"Jul":S("2026-07-01"),"Aug":S("2026-08-01"),"Sep":S("2026-09-01"),
   "Oct":S("2026-10-01"),"Nov4":S("2026-11-04"),"END":S("2026-11-12")}
FOLDS=[
 {"name":"WF_Jul","train":("May","Jun"),"cal":("Jun","Jul"),"test":("Jul","Aug")},
 {"name":"WF_Aug","train":("May","Jul"),"cal":("Jul","Aug"),"test":("Aug","Sep")},
 {"name":"WF_Sep","train":("May","Aug"),"cal":("Aug","Sep"),"test":("Sep","Oct")},
 {"name":"WF_Oct","train":("May","Sep"),"cal":("Sep","Oct"),"test":("Oct","Nov4")},
 {"name":"FINAL_FORWARD","train":("May","Oct"),"cal":("Oct","Nov4"),"test":("Nov4","END")},
]
BUDGETS=(0.40,0.70,1.00,99.0)
POLICIES=("SAFE_MAX_OOF_CAL","CAL_MAX","CAL_Q999","CAL_Q995","CAL_Q99","CAL_Q98")
BANNED=("strict","label","target","future","episode","dist_target")  # v2: "y_" removed (v1 wrongly dropped fl_intensity_60s_vs_1h, hold_buy_ratio*)
BANNED_EXACT={"y","episode_id","dist_pct","dist_target_pct","entry"}
STAGE_OF={"T600":300,"T900":300,"T1800":300,"T3600":300,"T7200":300,"T10800":300,"T0":60,"T10":60,"T30":60,"T60":60,"A15":60,"A20":60,"A25":60,"A30":180,"A35":180,"A40":180,"T180":180,"A50":300,"A70":300,"T300":300,"A100":300}

OUT=Path(os.environ.get("OUTDIR",str(DATA)));OUT.mkdir(parents=True,exist_ok=True)
def load():
    d=pickle.load(open(DATA/"dataset.pkl","rb"))
    if os.environ.get("LIQ")=="1":   # v2 liquidation layer (liq_features.py), causal by receive time
        add=pickle.load(open(DATA/"liq_feat_rows.pkl","rb"));assert len(add)==len(d["rows"])
        for r,a in zip(d["rows"],add):r["features"].update({k:float(v) for k,v in a.items() if v is not None and np.isfinite(v)})
    return d["rows"],d["episodes"]

def assign(rows,eps,fold):
    """Episode -> segment by target time; purge by label maturity (finalized before next segment starts)."""
    epi={e["episode_id"]:e for e in eps}
    seg={}
    for k in ("train","cal","test"):
        a,b=B[fold[k][0]],B[fold[k][1]]
        nxt=B["END"] if k=="test" else B[fold["cal" if k=="train" else "test"][0]]
        for e in eps:
            if a<=e["tmin_s"]<b and e["finalized_s"] is not None and e["finalized_s"]<=nxt and e["deadline_s"]<=nxt:
                seg[e["episode_id"]]=k
    out={k:[] for k in ("train","cal","test")}
    for i,r in enumerate(rows):
        k=seg.get(r["episode_id"])
        if k:out[k].append(i)
    return out,seg

def feature_names(rows,idx):
    cnt=defaultdict(int)
    for i in idx:
        for k in rows[i]["features"]:cnt[k]+=1
    n=max(1,len(idx))
    names=sorted(k for k,c in cnt.items() if c/n>=0.02 and k not in BANNED_EXACT and not any(b in k.lower() for b in BANNED))
    return names

def matrix(rows,idx,names):
    X=np.full((len(idx),len(names)),np.nan,dtype=np.float32)
    pos={k:j for j,k in enumerate(names)}
    for a,i in enumerate(idx):
        for k,v in rows[i]["features"].items():
            j=pos.get(k)
            if j is not None and v is not None and np.isfinite(v):X[a,j]=v
    return X

class Norm:
    def fit(self,X):
        self.med=np.nanmedian(X,0);mad=np.nanmedian(np.abs(X-self.med),0)
        self.med=np.where(np.isnan(self.med),0,self.med);self.sc=np.maximum(np.nan_to_num(1.4826*mad,nan=1.0),1e-6);return self
    def __call__(self,X):
        m=~np.isnan(X);v=np.where(m,np.clip((X-self.med)/self.sc,-12,12),0.0)  # value only meaningful with mask=1
        return np.concatenate([v,m.astype(np.float32)],1).astype(np.float32)

def wbce(logits,y):
    pos=float(y.sum());neg=float(len(y)-pos);pw=max(1.0,min(20.0,math.sqrt(neg/max(1.0,pos))))
    return F.binary_cross_entropy_with_logits(logits,y,pos_weight=torch.tensor(pw))

def sequences(rows,idx,Z):
    """For row i: causal sequence of the same member's decision points with t<=t_i (max 16)."""
    by=defaultdict(list)
    for a,i in enumerate(idx):by[(rows[i]["side"],rows[i]["member_g"])].append((rows[i]["t"],a))
    seq_idx=[None]*len(idx)
    for k,v in by.items():
        v.sort()
        for j,(t,a) in enumerate(v):seq_idx[a]=[b for _,b in v[max(0,j-15):j+1]]
    return seq_idx

def train_jepa(Z,y,seq_idx,epochs=4):
    torch.manual_seed(SEED)
    m=HypeFinJEPA(n_features=Z.shape[1],dim=48,depth=2,max_seq_len=16)
    opt=torch.optim.AdamW(m.parameters(),lr=3e-4,weight_decay=1e-4)
    bylen=defaultdict(list)
    for a,s in enumerate(seq_idx):bylen[len(s)].append(a)
    rng=random.Random(SEED)
    for ep in range(epochs):
        m.train()
        batches=[]
        for L,ids in bylen.items():
            ids=ids[:];rng.shuffle(ids)
            batches+=[ids[p:p+256] for p in range(0,len(ids),256)]
        rng.shuffle(batches)
        for bt in batches:
            x=torch.tensor(np.stack([Z[seq_idx[a]] for a in bt]));yy=torch.tensor(y[bt],dtype=torch.float32)
            o=m(x);loss=wbce(o["local_logits"]["LOW"],yy)+0.2*o["latent_loss"]  # side-specific model => use one head
            opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(m.parameters(),1.0);opt.step()
    return m

def pred_jepa(m,Z,seq_idx):
    m.eval();out=np.zeros(len(seq_idx))
    bylen=defaultdict(list)
    for a,s in enumerate(seq_idx):bylen[len(s)].append(a)
    with torch.no_grad():
        for L,ids in bylen.items():
            for p in range(0,len(ids),1024):
                bt=ids[p:p+1024];x=torch.tensor(np.stack([Z[seq_idx[a]] for a in bt]))
                out[bt]=torch.sigmoid(m(x)["local_logits"]["LOW"]).numpy()
    return out

def train_mlp(Z,y,stage,epochs=6):
    torch.manual_seed(SEED);m=QuantLocalExpert(Z.shape[1]);opt=torch.optim.AdamW(m.parameters(),lr=3e-4,weight_decay=1e-4)
    n=len(y);rng=np.random.default_rng(SEED)
    for ep in range(epochs):
        m.train();order=rng.permutation(n)
        for p in range(0,n,256):
            bt=order[p:p+256];x=torch.tensor(Z[bt]);st=torch.tensor(stage[bt],dtype=torch.float32);sd=torch.zeros(len(bt),dtype=torch.long)
            loss=wbce(m(x,st,sd),torch.tensor(y[bt],dtype=torch.float32))
            opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(m.parameters(),1.0);opt.step()
    return m
def pred_mlp(m,Z,stage):
    m.eval()
    with torch.no_grad():
        return torch.sigmoid(m(torch.tensor(Z),torch.tensor(stage,dtype=torch.float32),torch.zeros(len(Z),dtype=torch.long))).numpy()

def train_lgb(X,y):
    pos=y.sum();neg=len(y)-pos
    m=lgb.LGBMClassifier(n_estimators=300,learning_rate=0.03,num_leaves=15,min_child_samples=40,subsample=0.8,subsample_freq=1,
        colsample_bytree=0.6,reg_lambda=5.0,scale_pos_weight=float(min(30,math.sqrt(neg/max(pos,1)))),random_state=SEED,verbose=-1,n_jobs=6)
    m.fit(X,y);return m

class CortexEarly(CortexRelationshipExpert):
    def fit_rows(self,feats,ys,stages,side):
        import statistics
        for stage in (60,180,300):
            ids=[i for i in range(len(ys)) if stages[i]==stage]
            names=sorted({k for i in ids for k in feats[i]})
            rel=[]
            for k in names:
                pos=[feats[i][k] for i in ids if ys[i] and k in feats[i]];neg=[feats[i][k] for i in ids if not ys[i] and k in feats[i]]
                if len(pos)<self.min_pos or len(neg)<self.min_neg:continue
                med,scale=self._robust(pos+neg);eff=(statistics.median(pos)-statistics.median(neg))/scale
                if not math.isfinite(eff) or abs(eff)<.08:continue
                rel.append({"feature":k,"effect":float(eff),"median":float(med),"pos":len(pos),"neg":len(neg)})
            rel.sort(key=lambda x:(abs(x["effect"]),x["pos"]+x["neg"]),reverse=True)
            self.heads[(side,stage)]={"base_rate":float(sum(ys[i] for i in ids)/max(1,len(ids))),"relationships":rel[:self.max_features],
                                      "examples":len(ids),"positives":int(sum(ys[i] for i in ids))}
        return self

def feats_of(rows,idx,names):
    s=set(names);return [{k:float(v) for k,v in rows[i]["features"].items() if k in s and v is not None and np.isfinite(v)} for i in idx]

def fit_experts(rows,idx,names,side,epochs_j=4):
    X=matrix(rows,idx,names);y=np.array([rows[i]["y"] for i in idx],dtype=np.float32)
    stage=np.array([STAGE_OF[rows[i]["kind"]] for i in idx],dtype=np.float32)
    norm=Norm().fit(X);Z=norm(X);seq=sequences(rows,idx,Z)
    ex={"names":names,"norm":norm}
    ex["lgb"]=train_lgb(X,y)
    ex["mlp"]=train_mlp(Z,y,stage)
    ex["jepa"]=train_jepa(Z,y,seq,epochs=epochs_j)
    lo=LocalOnlyModel();fe=feats_of(rows,idx,names)
    order=sorted(range(len(idx)),key=lambda a:rows[idx[a]]["t"])
    for a in order:lo.learn(side,int(stage[a]),fe[a],bool(y[a]),repeat=3 if y[a] else 1)
    ex["river"]=lo
    ex["cortex"]=CortexEarly().fit_rows(fe,y.tolist(),stage.tolist(),side)
    return ex

def predict_experts(ex,rows,idx,side):
    names=ex["names"];X=matrix(rows,idx,names);Z=ex["norm"](X);seq=sequences(rows,idx,Z)
    stage=np.array([STAGE_OF[rows[i]["kind"]] for i in idx],dtype=np.float32)
    fe=feats_of(rows,idx,names)
    P=np.zeros((len(idx),5))
    P[:,0]=ex["lgb"].predict_proba(X)[:,1]
    P[:,1]=pred_mlp(ex["mlp"],Z,stage)
    P[:,2]=pred_jepa(ex["jepa"],Z,seq)
    P[:,3]=[ex["river"].probability(side,int(stage[a]),fe[a]) for a in range(len(idx))]
    P[:,4]=[ex["cortex"].predict(side,int(stage[a]),fe[a]) for a in range(len(idx))]
    return P
EXPERTS=["quantum_lgbm","quantum_mlp","fin_jepa","local_only_river","cortex"]

def meta_vec(P,rows,idx):
    L=np.log(np.clip(P,1e-6,1-1e-6)/(1-np.clip(P,1e-6,1-1e-6)))
    ctx=np.array([[STAGE_OF[rows[i]["kind"]]/300.0,min(rows[i]["dist_pct"],3.0),math.log1p(rows[i]["features"].get("px_age_s",0))] for i in idx])
    return np.concatenate([L,L.mean(1,keepdims=True),L.std(1,keepdims=True),ctx],1)

def oof_and_fit(rows,tr_idx,side,names,nblocks=3):
    """Time-blocked OOF on train: block k predicted by experts fit on blocks < k (expanding, purged by episode)."""
    eps_t=sorted({rows[i]["episode_id"] for i in tr_idx},key=lambda e:min(rows[i]["t"] for i in tr_idx if rows[i]["episode_id"]==e))
    nb=len(eps_t);cuts=[eps_t[int(nb*k/(nblocks+1))] for k in range(1,nblocks+1)]
    order_ep={e:j for j,e in enumerate(eps_t)}
    oof_idx=[];oof_P=[]
    for k in range(nblocks):
        lo=int(nb*(k+1)/(nblocks+1));hi=int(nb*(k+2)/(nblocks+1))
        fit_e=set(eps_t[:max(0,lo-1)])  # purge one episode at boundary
        pr_e=set(eps_t[lo:hi])
        fi=[i for i in tr_idx if rows[i]["episode_id"] in fit_e];pi=[i for i in tr_idx if rows[i]["episode_id"] in pr_e]
        if sum(rows[i]["y"] for i in fi)<10 or not pi:continue
        ex=fit_experts(rows,fi,names,side,epochs_j=3)
        oof_idx+=pi;oof_P.append(predict_experts(ex,rows,pi,side))
    P=np.concatenate(oof_P) if oof_P else np.zeros((0,5))
    yo=np.array([rows[i]["y"] for i in oof_idx])
    meta=LogisticRegression(C=0.3,class_weight="balanced",max_iter=3000)
    meta.fit(meta_vec(P,rows,oof_idx),yo)
    final=fit_experts(rows,tr_idx,names,side)
    oof_score=meta.predict_proba(meta_vec(P,rows,oof_idx))[:,1]
    return final,meta,oof_idx,oof_score,P

# ---------- episode-level evaluation ----------
def first_signals(rows,idx,score,thr,budget):
    by=defaultdict(list)
    for a,i in enumerate(idx):
        r=rows[i]
        if r["dist_pct"]<=budget and score[a]>=thr:by[r["episode_id"]].append((r["t"],a,i))
    return {e:min(v) for e,v in by.items()}

def evaluate(rows,idx,score,thr,budget,episodes,teacher=None):
    epi={e["episode_id"]:e for e in episodes}
    eids=sorted({rows[i]["episode_id"] for i in idx})
    fs=first_signals(rows,idx,score,thr,budget)
    recs=[]
    for e in eids:
        E=epi[e];rec={"episode_id":e,"side":E["side"],"target_ts":E["tmin_s"]+T0,"target_price":E["target_price"],"next_price":E["next_price"]}
        if e in fs:
            t,a,i=fs[e];r=rows[i]
            rec.update(accepted=True,true_first=bool(r["y"]),signal_ts=t+T0,kind=r["kind"],entry=r["entry"],score=float(score[a]),
                       member_dist_pct=r["dist_pct"])
            if r["y"]:
                rev=1 if E["side"]=="LOW" else -1
                rec["delay_s"]=t-(r["member_g"]+1)
                rec["dist_pct"]=rev*(r["entry"]/E["target_price"]-1)*100
                full=abs(E["next_price"]-E["target_price"])
                rec["remaining_move_pct"]=rev*(E["next_price"]/r["entry"]-1)*100
                rec["captured_mfe_ratio"]=max(0.0,rev*(E["next_price"]-r["entry"]))/max(full,1e-12)
        else:rec["accepted"]=False
        recs.append(rec)
    return recs

def summarize(recs):
    acc=[r for r in recs if r["accepted"]];tp=[r for r in acc if r["true_first"]]
    def q(v,p):return float(np.percentile(v,p)) if v else None
    d=[r["dist_pct"] for r in tp];dl=[r["delay_s"] for r in tp];cm=[r["captured_mfe_ratio"] for r in tp];rm=[r["remaining_move_pct"] for r in tp]
    n=len(recs)
    return {"true_terminal_locals":n,"accepted":len(acc),"tp":len(tp),"false_first":len(acc)-len(tp),"fn":n-len(tp),
            "precision":len(tp)/len(acc) if acc else None,"coverage":len(tp)/n if n else None,
            "median_delay_s":q(dl,50),"p90_delay_s":q(dl,90),"median_dist_pct":q(d,50),"p90_dist_pct":q(d,90),
            "median_remaining_move_pct":q(rm,50),"median_captured_mfe_ratio":q(cm,50),"mean_captured_mfe_ratio":float(np.mean(cm)) if cm else None,
            "mfe_giveback_vs_ideal_median":(1-q(cm,50)) if cm else None}

def thresholds(cal_scores_false_by_budget,oof_false_by_budget):
    out={}
    for b in BUDGETS:
        cf=np.array(cal_scores_false_by_budget[b]);of=np.array(oof_false_by_budget[b])
        allf=np.concatenate([cf,of]) if len(of) else cf
        mx=lambda v:float(v.max())+1e-9 if len(v) else 0.5
        out[b]={"SAFE_MAX_OOF_CAL":mx(allf),"CAL_MAX":mx(cf),
                "CAL_Q999":float(np.quantile(cf,.999)) if len(cf) else .5,"CAL_Q995":float(np.quantile(cf,.995)) if len(cf) else .5,
                "CAL_Q99":float(np.quantile(cf,.99)) if len(cf) else .5,"CAL_Q98":float(np.quantile(cf,.98)) if len(cf) else .5}
    return out

def run_fold(rows,eps,fold,log):
    seg_idx,seg=assign(rows,eps,fold)
    res={"fold":fold["name"],"segments":{k:{"episodes":len({rows[i]['episode_id'] for i in v}),"rows":len(v),
          "true_members":len({(rows[i]['side'],rows[i]['member_g']) for i in v if rows[i]['y']})} for k,v in seg_idx.items()},
         "sides":{}}
    bundle={"fold":fold["name"],"sides":{}}
    for side in ("LOW","HIGH"):
        tr=[i for i in seg_idx["train"] if rows[i]["side"]==side];ca=[i for i in seg_idx["cal"] if rows[i]["side"]==side]
        te=[i for i in seg_idx["test"] if rows[i]["side"]==side]
        names=feature_names(rows,tr)
        t0=time.time()
        final,meta,oof_idx,oof_score,_=oof_and_fit(rows,tr,side,names)
        Pc=predict_experts(final,rows,ca,side);sc_c=meta.predict_proba(meta_vec(Pc,rows,ca))[:,1]
        # thresholds frozen from cal (+train OOF) BEFORE test predictions are computed
        cf={b:[sc_c[a] for a,i in enumerate(ca) if not rows[i]["y"] and rows[i]["dist_pct"]<=b] for b in BUDGETS}
        of={b:[oof_score[a] for a,i in enumerate(oof_idx) if not rows[i]["y"] and rows[i]["dist_pct"]<=b] for b in BUDGETS}
        TH=thresholds(cf,of)
        frozen=json.dumps(TH,sort_keys=True)
        Pt=predict_experts(final,rows,te,side);sc_t=meta.predict_proba(meta_vec(Pt,rows,te))[:,1]
        assert json.dumps(TH,sort_keys=True)==frozen
        grid={}
        for b in BUDGETS:
            for pol in POLICIES:
                th=TH[b][pol]
                grid[f"B{b}_{pol}"]={"budget_pct":b,"policy":pol,"threshold":th,
                    "calibration":summarize(evaluate(rows,ca,sc_c,th,b,eps)),
                    "test":summarize(evaluate(rows,te,sc_t,th,b,eps))}
        # expert-level AUC diagnostics on test rows (no selection)
        from sklearn.metrics import roc_auc_score
        yt=np.array([rows[i]["y"] for i in te])
        auc={}
        if 0<yt.sum()<len(yt):
            for j,nm in enumerate(EXPERTS):auc[nm]=float(roc_auc_score(yt,Pt[:,j]))
            auc["meta"]=float(roc_auc_score(yt,sc_t))
        res["sides"][side]={"n_features":len(names),"grid":grid,"thresholds":TH,"test_row_auc":auc,
                            "train_secs":time.time()-t0,"meta_coef":meta.coef_.tolist()}
        bundle["sides"][side]={"names":names,"experts":final,"meta":meta,"thresholds":TH,
                               "scores":{"cal":(ca,sc_c.tolist()),"test":(te,sc_t.tolist())},"test_P":Pt}
        log(f"{fold['name']} {side} done {time.time()-t0:.0f}s feats={len(names)} auc={auc}")
        for key in ("B0.4_SAFE_MAX_OOF_CAL","B0.7_SAFE_MAX_OOF_CAL","B1.0_SAFE_MAX_OOF_CAL","B0.4_CAL_Q99","B99.0_SAFE_MAX_OOF_CAL"):
            g=grid[key];log(f"   {key} cal={ {k:g['calibration'][k] for k in ('tp','false_first','true_terminal_locals')} } test={ {k:g['test'][k] for k in ('tp','false_first','true_terminal_locals','median_dist_pct')} }")
    return res,bundle,seg

if __name__=="__main__":
    which=sys.argv[1:] or [f["name"] for f in FOLDS]
    rows,eps=load()
    logf=open(OUT/"train.log","a")
    def log(s):print(s,flush=True);logf.write(s+"\n");logf.flush()
    for fold in FOLDS:
        if fold["name"] not in which:continue
        res,bundle,seg=run_fold(rows,eps,fold,log)
        json.dump(res,open(OUT/f"fold_{fold['name']}.json","w"),default=float)
        torch.save(bundle,OUT/f"bundle_{fold['name']}.pt")
        pickle.dump(seg,open(OUT/f"seg_{fold['name']}.pkl","wb"))
