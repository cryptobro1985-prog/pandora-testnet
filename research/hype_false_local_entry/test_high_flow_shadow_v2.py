from research.hype_false_local_entry.high_flow_shadow_v2 import qualifies,contract

BASE=dict(side="HIGH",primary_emitted=False,expected_side_ok=True,checkpoint_fresh=True,
          retrace_bps=80.0,retrace_fraction_pre_180=0.43,flow_15=-0.20,
          trade_count=500,already_emitted=False)

def test_v2_accepts_strong_retrace_high():
    ok,m=qualifies(**BASE)
    assert ok and m["ready"]

def test_v2_rejects_weak_seller_flow():
    x=dict(BASE);x["flow_15"]=-0.06
    ok,_=qualifies(**x)
    assert not ok

def test_v2_rejects_mid_fraction_weak_retrace():
    x=dict(BASE);x["retrace_bps"]=56.0;x["retrace_fraction_pre_180"]=0.425
    ok,_=qualifies(**x)
    assert not ok

def test_v2_keeps_early_fraction_with_40bps():
    x=dict(BASE);x["retrace_bps"]=46.0;x["retrace_fraction_pre_180"]=0.39
    ok,_=qualifies(**x)
    assert ok

def test_v2_never_authorizes_core_flip():
    c=contract()
    assert c["core_flip_authorized"] is False
    assert c["primary_contract_unchanged"] is True
    assert c["promotion"]=="FORWARD_SCORE_ONLY"
