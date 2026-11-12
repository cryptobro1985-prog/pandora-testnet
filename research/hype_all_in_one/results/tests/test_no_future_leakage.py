"""Future-leakage tests: features at decision time t must be invariant to ANY change of data at/after t."""
import copy,inspect,ast,random
import numpy as np,pytest
from core import Tape,T0
import dataset as D
from research.hype_quant.feature_contract import POINTS,INPUT_IDS,TARGET_IDS,METADATA_IDS

def test_contract_counts():
    assert len(POINTS)==116 and len(INPUT_IDS)==86 and len(TARGET_IDS)==28 and len(METADATA_IDS)==2

def test_feature_names_have_no_target_or_label_fields(dataset):
    banned=("strict","label","target","future","episode","next_","confirmed","precision","recall")
    names={k for r in dataset["rows"][::50] for k in r["features"]}
    bad=[k for k in names if any(b in k.lower() for b in banned)]
    assert not bad,bad
    assert "y" not in names and "episode_id" not in names

def test_feature_function_never_sees_labels():
    src=inspect.getsource(D.Feat.features)
    sig=inspect.signature(D.Feat.features)
    assert list(sig.parameters)==["self","side","g","p","t","ctx"]
    tree=ast.parse(src.strip().replace("def features","def features",1))
    names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
    for forbidden in ("labels","ep","eps","episode","is_true","structural_labels","deadline"):
        assert forbidden not in names,forbidden

def test_family_to_contract_ids_are_inputs_only():
    from atlas import FAMILY
    import re
    for _,desc in FAMILY:
        for x in re.findall(r"\d+",desc.split("(ids")[-1] if "ids" in desc else ""):
            assert int(x) in INPUT_IDS,(desc,x)

def _perturb(tp,t,seed=0):
    """Return a shallow copy of tape where every observation at/after decision time t is scrambled."""
    rng=np.random.default_rng(seed);q=copy.copy(tp)
    for k in ("high","low","closef","close","buy","sell","maxn","ntr"):
        a=getattr(tp,k).copy();n=len(a)-t
        if k in ("high","low","closef","close"):a[t:]=a[t:]*rng.uniform(0.8,1.2,n)
        else:a[t:]=(a[t:]*rng.uniform(0,5,n)).astype(a.dtype)
        setattr(q,k,a)
    q.has_trade=tp.has_trade.copy();q.has_trade[t:]=rng.random(len(q.has_trade)-t)>0.5
    q.cbuy=np.concatenate([[0.0],np.cumsum(q.buy.astype(np.float64))]);q.csell=np.concatenate([[0.0],np.cumsum(q.sell.astype(np.float64))])
    q.ccnt=np.concatenate([[0],np.cumsum(q.ntr.astype(np.int64))]);q.cnotrade=np.concatenate([[0],np.cumsum((~q.has_trade).astype(np.int64))])
    if tp.book is not None:
        # avoid copying the 2GB book matrix: every book read strictly after t returns scrambled data
        orig=tp.book_at
        def book_at(g,_t=t,_o=orig,_r=rng):
            r=_o(g)
            return r if (r is None or g<=_t) else r*_r.uniform(0.5,1.5,r.shape)
        q.book_at=book_at
    # aux step series: values whose availability time > t are scrambled
    for ts,vs in (("oi_t","oi_v"),("ra_t","ra_v"),("fu_t","fu_v"),("mk_t","mk_c"),("ix_t","ix_c")):
        T=getattr(tp,ts);V=getattr(tp,vs).copy();m=T>t;V[m]=V[m]*rng.uniform(0.5,1.5,m.sum());setattr(q,vs,V)
    # M1 arrays: minutes not fully completed by t are scrambled
    mt=t//60
    for k in ("m_high","m_low","m_close","m_open"):
        a=getattr(tp,k).copy();a[mt:]=a[mt:]*rng.uniform(0.8,1.2,len(a)-mt);setattr(q,k,a)
    return q

def _same(a,b):
    assert set(a)==set(b),(set(a)^set(b))
    for k in a:
        x,y=a[k],b[k]
        if isinstance(x,float) and np.isnan(x):assert np.isnan(y),k
        else:assert x==pytest.approx(y,rel=1e-9,abs=1e-9),(k,x,y)

def test_features_invariant_to_future_perturbation(tape,dataset):
    rows=dataset["rows"];random.seed(7)
    kinds={}
    for r in rows:kinds.setdefault((r["side"],r["kind"],r["y"]),[]).append(r)
    sample=[random.choice(v) for v in kinds.values()][:40]
    FE0=D.Feat(tape)
    for n,r in enumerate(sample):
        t=r["t"];g=r["member_g"];p=r["member_price"]
        ctx={k:v for k,v in r["features"].items() if k.startswith(("lin_","opp_swing_bps","opp_swing_age","opp_intact"))}
        base=FE0.features(r["side"],g,p,t,ctx)
        _same(base,r["features"])  # reproducible from stored dataset
        q=_perturb(tape,t,seed=n)
        FE=D.Feat(q)
        pert=FE.features(r["side"],g,p,t,ctx)
        _same(base,pert)

def test_lineage_context_invariant_to_future(tape,dataset):
    rows=dataset["rows"];random.seed(3)
    sample=random.sample([r for r in rows if r["kind"]=="T0"],15)
    for side in ("LOW","HIGH"):
        rr=[r for r in sample if r["side"]==side]
        if not rr:continue
        for r in rr:
            gi=r["member_g"];q=_perturb(tape,gi+1,seed=gi%1000)
            out=[]
            for tp_ in (tape,q):
                MEM={sd:D.make_members(tp_,sd) for sd in ("LOW","HIGH")}
                g,price,sup=MEM[side];og,op,osup=MEM["HIGH" if side=="LOW" else "LOW"]
                surv=(osup-og)>=7200;sg,sp,ss=og[surv],op[surv],osup[surv];known=sg+7200
                i=int(np.nonzero(g==gi)[0][0]);rev=1 if side=="LOW" else -1
                mxr=np.zeros(len(g))
                for k in np.nonzero((g>=gi-D.HORIZON)&(g<gi))[0]:
                    a=g[k]+1;b=min(sup[k],g[k]+D.HORIZON,tp_.N)
                    if b>a and sup[k]<=gi:
                        best=tp_.high[a:b].max() if side=="LOW" else tp_.low[a:b].min();mxr[k]=rev*(best/price[k]-1)*1e4
                out.append(D.lineage_context(g,price,sup,mxr,i,gi,float(price[i]),rev,(sg,sp,ss,known)))
            _same(out[0],out[1])

def test_decision_points_precede_supersession(tape,dataset):
    rows=dataset["rows"];random.seed(11)
    for r in random.sample(rows,3000):
        g,t,p=r["member_g"],r["t"],r["member_price"]
        if t-1>g:
            if r["side"]=="LOW":assert tape.low[g+1:t].min()>=p
            else:assert tape.high[g+1:t].max()<=p
        assert t>g
