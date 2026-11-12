"""V2 liquidation layer: features at decision second t use only events RECEIVED before t; missing hours stay missing."""
import random,copy,numpy as np,pytest
import liq_features as LF

@pytest.fixture(scope="module")
def liq(tape):
    return LF.load_liq(tape.N)

def _perturb_after(L,t):
    M={k:(v.copy() if isinstance(v,np.ndarray) else v) for k,v in L.items()}
    rng=np.random.default_rng(0)
    for k in ("cl","cs_","cnl","cns"):
        a=M[k]; inc=np.diff(a); inc[t:]=rng.uniform(0,1e7,size=len(inc)-t)  # rewrite all events received at/after t
        M[k]=np.concatenate([[0.0],np.cumsum(inc)])
    return M

def test_liq_features_invariant_to_events_received_at_or_after_t(tape,dataset,liq):
    rows=dataset["rows"];random.seed(7)
    sample=random.sample(range(len(rows)),40)
    for i in sample:
        r=rows[i];t=r["t"]
        f0=LF.LiqFeat(liq,tape).features(r["side"],r["member_g"],t)
        f1=LF.LiqFeat(_perturb_after(liq,t),tape).features(r["side"],r["member_g"],t)
        for k in f0:
            a,b=f0[k],f1[k]
            assert (np.isnan(a) and np.isnan(b)) or a==pytest.approx(b,rel=1e-9,abs=1e-9),(k,a,b)

def test_events_bucketed_by_receive_time_not_exchange_time():
    import inspect
    src=inspect.getsource(LF.load_liq)
    assert "received_time" in src and "rs=(df['received_time']" in src

def test_missing_hour_is_nan_not_zero(tape,liq):
    av=liq["avail"]; miss=np.where(~av[:tape.N])[0]
    if len(miss)==0: pytest.skip("no missing hours")
    g=int(miss[len(miss)//2]); lf=LF.LiqFeat(liq,tape)
    f=lf.features("LOW",g-30,g+30)
    assert np.isnan(f["liq_old_60s"]) and f["liq_avail"]==0.0

def test_liq_rows_aligned_with_dataset(dataset):
    import pickle
    from core import DATA
    add=pickle.load(open(DATA/"liq_feat_rows.pkl","rb"))
    assert len(add)==len(dataset["rows"])
    assert all(k.startswith("liq_") for k in add[0])
