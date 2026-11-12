"""Score the PROJECT's frozen checkpoints (trained <=2026-11-03) on the post-freeze forward window 2026-11-04..11-11
using the project's own snapshot builder + feature code. Valid only for forward: Jul-Oct folds would leak (models saw Oct)."""
import sys,json,gzip,glob,numpy as np,torch,bisect
from collections import defaultdict
sys.path.insert(0,'/workspace/pandora-testnet')
import __main__
from research.hype_local_only import train_local_ensemble_30d as E
from research.hype_local_only import train_unified_local_intelligence_v2 as U
from research.hype_local_only.fin_jepa_adapter import HypeFinJEPA
from research.hype_local_only.h1_teacher_context import load_minutes,build_index,causal_h1_features
from research.hype_local_only.feature_discovery import scalar_interactions,historical_indicator_features
from research.hype_local_only.timeline_teacher import build_timeline_rows,fit as fit_timeline,attach_candidate_probabilities
__main__.CortexRelationshipExpert=U.CortexRelationshipExpert
P='/workspace/data/p116/'
FWD0=1793750400000   # 2026-11-04T00:00Z
FWD1=1794398400000   # 2026-11-11T12:00Z (maturity margin before tape end 11-12)
rows=E.load_rows(P+'candidate_snapshots_enriched.jsonl.gz')
labs=json.load(gzip.open(P+'labels.json.gz','rt')); strict=labs['strict']; fin_l=[x for x in strict if x.get('reference_finalized',True)]
E.apply_teacher(rows,fin_l)
minutes=load_minutes(P+'compact_1m.jsonl.gz');hidx=build_index(minutes);ends=[int(z['bar_end_ms']) for z in minutes]
fwd=[r for r in rows if FWD0<=int(r['candidate_ts_ms'])<FWD1]
for r in fwd:
    ts=int(r['snapshot_ts_ms']);side=r['side']
    r['features'].update(causal_h1_features(minutes,hidx,ts,side,float(r['extreme_price'])))
    r['features'].update(historical_indicator_features(minutes,ends,ts,side))
    r['features'].update({'discovery__'+k:float(v) for k,v in scalar_interactions(r['features'],side).items() if E.finite(v)})
    r['features'].update(U._minute_regime(minutes,ends,ts))
def samples_for(b):
    names,med,scale=b['feature_names'],b['median'],b['scale']
    by=defaultdict(list)
    for r in fwd: by[r['candidate_id']].append(r)
    out=[]
    for cid,rr in by.items():
        sm={int(r['delay_s']):r for r in rr}
        for st in E.PRED_STAGES:
            r=sm.get(st)
            if not r: continue
            seq=[E.vectorize(sm[d]['features'],names,med,scale) for d in E.DELAYS if d<=st and d in sm]
            out.append({'candidate_id':cid,'side':r['side'],'stage':st,'ts':int(r['candidate_ts_ms']),'y':float(bool(r['strict_true'])),
                        'seq':np.stack(seq).astype(np.float32),'tab':E.vectorize(r['features'],names,med,scale).astype(np.float32),'row':r})
    n=len(names)*2
    fin=HypeFinJEPA(n_features=n,dim=64,depth=3,max_seq_len=len(E.DELAYS));fin.load_state_dict(b['fin_jepa']);fin.eval()
    q=E.QuantLocalExpert(n);q.load_state_dict(b['quant_local']);q.eval()
    for st in E.PRED_STAGES:
        ss=[z for z in out if z['stage']==st]
        if not ss: continue
        with torch.no_grad():
            side=E.side_tensor(ss);fo=fin(torch.tensor(np.stack([z['seq'] for z in ss])))
            fp=torch.sigmoid(torch.where(side==0,fo['local_logits']['LOW'],fo['local_logits']['HIGH'])).numpy()
            qp=torch.sigmoid(q(torch.tensor(np.stack([z['tab'] for z in ss])),torch.tensor([float(st)]*len(ss)),side)).numpy()
        for z,a,c in zip(ss,fp,qp): z['p_fin']=float(a);z['p_quant']=float(c)
    for z in out:
        z['p_river']=float(b['river_local'].probability(z['side'],z['stage'],z['row']['features']))
        m=b['extra_trees'].get((z['side'],z['stage'])); z['p_tree']=0.5 if m is None else float(m.predict_proba(z['tab'][None,:])[0,1])
    return out
def episode_view(acc_by_cid):
    """H1-episode view consistent with v1/v2 metrics: first accepted candidate of the target side inside (prev label start, target end]."""
    L=sorted(fin_l,key=lambda x:int(x['extreme_interval_start_ms']));res=[]
    for j in range(1,len(L)-1):
        prev,t,nx=L[j-1],L[j],L[j+1]
        if not (FWD0<=int(t['extreme_interval_start_ms'])<FWD1): continue
        a=int(prev['extreme_interval_start_ms']);e=int(t['extreme_interval_end_ms'])
        firsts=sorted((v['signal_ts'],cid,v) for cid,v in acc_by_cid.items() if v['side']==t['side'] and a<v['cand_ts']<=e)
        if firsts:
            _,cid,v=firsts[0]; res.append({'side':t['side'],'accepted':True,'true_first':bool(v['y']),'dist_pct':v.get('dist_pct')})
        else: res.append({'side':t['side'],'accepted':False})
    return res
def evaluate(ss,scorer,th,name):
    by=defaultdict(list)
    for z in ss: by[z['candidate_id']].append((z['stage'],scorer(z),z))
    acc={}
    for cid,rr in by.items():
        for st,p,z in sorted(rr,key=lambda x:x[0]):
            if p>=th:
                r=z['row'];rb=float(r['features'].get('retrace_bps',0.0))
                acc[cid]={'side':z['side'],'y':z['y'],'cand_ts':z['ts'],'signal_ts':z['ts']+st*1000,'stage':st,'dist_pct':None};break
    # entry distance vs true extreme for TP: price at signal from compact M1 close
    closes={int(m['bar_end_ms']):float(m['close']) for m in minutes}
    for cid,v in acc.items():
        ex=[float(r['extreme_price']) for r in fwd if r['candidate_id']==cid][0]
        k=(v['signal_ts']//60000)*60000; px=closes.get(k)
        if px: v['dist_pct']=abs(px/ex-1)*100
    tp=sum(1 for v in acc.values() if v['y']);fp=len(acc)-tp;tot=len({z['candidate_id'] for z in ss if z['y']})
    ep=episode_view(acc)
    out={'model':name,'threshold':th,'candidate_level':{'candidates':len(by),'reference_true_candidates':tot,'accepted':len(acc),'tp':tp,'fp':fp,
         'median_delay_s_tp':float(np.median([v['stage'] for v in acc.values() if v['y']])) if tp else None,
         'median_dist_pct_tp':float(np.median([v['dist_pct'] for v in acc.values() if v['y'] and v['dist_pct'] is not None])) if tp else None},
         'h1_episode_level':{s:{'episodes':sum(1 for r in ep if r['side']==s),'accepted':sum(1 for r in ep if r['side']==s and r['accepted']),
              'true_first':sum(1 for r in ep if r['side']==s and r.get('true_first')),'false_first':sum(1 for r in ep if r['side']==s and r['accepted'] and not r.get('true_first'))} for s in ('LOW','HIGH')}}
    print(json.dumps(out),flush=True); return out
res={'forward_window_utc':['2026-11-04T00:00Z','2026-11-11T12:00Z'],'forward_candidates':len({r['candidate_id'] for r in fwd}),'results':[]}
A='/workspace/proj_art/'
for nm in ('HYPE_LOCAL_ENSEMBLE.pt','HYPE_LOCAL_FULL30D_TEACHER.pt'):
    b=torch.load(glob.glob(A+'HYPE-LOCAL-ENSEMBLE-30D-*/'+nm)[0],weights_only=False,map_location='cpu')
    w=b.get('weights') or b.get('ensemble_weights'); th=b.get('threshold') or b.get('ensemble_threshold')
    ss=samples_for(b)
    for z in ss: z['p_timeline']=0.0   # weight is 0.0 in the frozen ensemble
    assert w[4]==0.0
    res['results'].append(evaluate(ss,lambda z:w[0]*z['p_fin']+w[1]*z['p_quant']+w[2]*z['p_river']+w[3]*z['p_tree'],float(th),nm))
# Unified V2: timeline expert not saved -> deterministic refit on the project's own artifact (train split, seed fixed)
b=torch.load(glob.glob(A+'HYPE-UNIFIED-*/HYPE_UNIFIED_LOCAL_INTELLIGENCE_V2.pt')[0],weights_only=False,map_location='cpu')
art=glob.glob(A+'local116-HYPE-*')[0]
am=load_minutes(art+'/compact_1m.jsonl.gz'); al=json.load(gzip.open(art+'/labels.json.gz','rt'))
tl_rows=build_timeline_rows(am,al['strict'] if isinstance(al,dict) and 'strict' in al else al)
tlm,tln=fit_timeline(tl_rows,E.split_name,4,all_data=False)
ss=samples_for(b)
fw_tl=build_timeline_rows(minutes,strict)
attach_candidate_probabilities({'x':ss},fw_tl,tlm,tln)
for z in ss:
    z['p_cortex']=float(b['cortex_relationship'].predict(z['side'],z['stage'],z['row']['features']))
    f=z['row']['features']; z['regime_score']=float(f.get('discovery__market_regime_score',0.0) or 0.0); z['regime_accel']=float(f.get('discovery__market_accel_60v360',0.0) or 0.0)
meta=b['meta_model']
res['results'].append(evaluate(ss,lambda z:float(meta.predict_proba(U._meta_vector(z)[None,:])[0,1]),float(b['meta_threshold']),'HYPE_UNIFIED_LOCAL_INTELLIGENCE_V2.pt'))
res['note']='Timeline expert of Unified V2 was not saved in the bundle; refit deterministically (seed 20261107) on the project artifact train split, as in the project code.'
json.dump(res,open('/workspace/data/project_ckpt_forward.json','w'),indent=1)
print('DONE')
