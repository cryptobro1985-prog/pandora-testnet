"""Candidate leakage tests across train / calibration / test(OOS or forward)."""
import json,pickle
import numpy as np,pytest,torch
from core import DATA
import train_walkforward as W

FOLDS=[f for f in W.FOLDS if (DATA/f"bundle_{f['name']}.pt").exists()]

@pytest.fixture(scope="module")
def bundles():
    return {f["name"]:torch.load(DATA/f"bundle_{f['name']}.pt",weights_only=False) for f in FOLDS}

@pytest.mark.parametrize("fold",FOLDS,ids=[f["name"] for f in FOLDS])
def test_segments_disjoint_and_purged(dataset,fold):
    rows,eps=dataset["rows"],dataset["episodes"]
    seg_idx,seg=W.assign(rows,eps,fold)
    epi={e["episode_id"]:e for e in eps}
    E={k:{rows[i]["episode_id"] for i in v} for k,v in seg_idx.items()}
    M={k:{(rows[i]["side"],rows[i]["member_g"]) for i in v} for k,v in seg_idx.items()}
    for a,b in (("train","cal"),("train","test"),("cal","test")):
        assert E[a].isdisjoint(E[b]),(a,b)
        assert M[a].isdisjoint(M[b]),(a,b)
    cal0=W.B[fold["cal"][0]];test0=W.B[fold["test"][0]]
    # label maturity purge: every train label finalized (and its scoring deadline passed) before calibration starts
    assert max(epi[e]["finalized_s"] for e in E["train"])<=cal0
    assert max(epi[e]["deadline_s"] for e in E["train"])<=cal0
    assert max(epi[e]["finalized_s"] for e in E["cal"])<=test0
    assert max(rows[i]["t"] for i in seg_idx["train"])<=cal0
    assert max(rows[i]["t"] for i in seg_idx["cal"])<=test0
    # chronology
    assert max(epi[e]["tmin_s"] for e in E["train"])<min(epi[e]["tmin_s"] for e in E["cal"])<=max(epi[e]["tmin_s"] for e in E["cal"])<min(epi[e]["tmin_s"] for e in E["test"])

@pytest.mark.parametrize("fold",FOLDS,ids=[f["name"] for f in FOLDS])
def test_thresholds_depend_only_on_calibration_and_train(dataset,bundles,fold):
    rows=dataset["rows"];b=bundles[fold["name"]]
    seg_idx,_=W.assign(rows,dataset["episodes"],fold)
    test_set=set(seg_idx["test"])
    for side,S in b["sides"].items():
        ca,sc=S["scores"]["cal"]
        assert test_set.isdisjoint(ca)
        for bud in W.BUDGETS:
            cf=[s for a,s in zip(ca,sc) if not rows[a]["y"] and rows[a]["dist_pct"]<=bud]
            if cf:
                assert S["thresholds"][bud]["CAL_MAX"]==pytest.approx(max(cf)+1e-9)
                assert S["thresholds"][bud]["CAL_Q99"]==pytest.approx(float(np.quantile(cf,.99)))
                assert S["thresholds"][bud]["SAFE_MAX_OOF_CAL"]>=S["thresholds"][bud]["CAL_MAX"]-1e-12

@pytest.mark.parametrize("fold",FOLDS,ids=[f["name"] for f in FOLDS])
def test_normalization_fit_on_train_only(dataset,bundles,fold):
    rows=dataset["rows"];b=bundles[fold["name"]]
    seg_idx,_=W.assign(rows,dataset["episodes"],fold)
    for side,S in b["sides"].items():
        tr=[i for i in seg_idx["train"] if rows[i]["side"]==side]
        X=W.matrix(rows,tr,S["names"]);n=W.Norm().fit(X)
        assert np.allclose(n.med,S["experts"]["norm"].med,equal_nan=True)
        assert np.allclose(n.sc,S["experts"]["norm"].sc,equal_nan=True)

def test_forward_model_frozen_before_forward_period(dataset,bundles):
    if "FINAL_FORWARD" not in bundles:pytest.skip("forward fold not trained")
    rows=dataset["rows"];fold=[f for f in W.FOLDS if f["name"]=="FINAL_FORWARD"][0]
    seg_idx,_=W.assign(rows,dataset["episodes"],fold)
    nov4=W.B["Nov4"]
    assert max(rows[i]["t"] for i in seg_idx["train"]+seg_idx["cal"])<=nov4
    eps={e["episode_id"]:e for e in dataset["episodes"]}
    assert min(eps[rows[i]["episode_id"]]["tmin_s"] for i in seg_idx["test"])>=nov4

def test_x_never_contains_label_columns(bundles):
    for name,b in bundles.items():
        for side,S in b["sides"].items():
            for k in S["names"]:
                assert not any(x in k.lower() for x in W.BANNED),k
                assert k not in ("y","episode_id","dist_target_pct","member_price","entry")
