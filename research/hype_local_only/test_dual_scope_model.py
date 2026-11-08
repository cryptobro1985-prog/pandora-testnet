from research.hype_local_only.model import LocalOnlyModel


def test_internal_scope_is_isolated_and_cold_started():
    m=LocalOnlyModel()
    x={"retrace_bps":42.0,"rev_flow_180s":0.3}
    assert not m.internal_ready("LOW",60)
    p,accepted=m.predict_internal("LOW",60,x)
    assert 0.0<=p<=1.0
    assert not accepted
    assert m.labels[("LOW",60)]==0

    for i in range(20):
        m.learn_internal("LOW",60,x,bool(i<4),source="live")
    assert m.internal_ready("LOW",60)
    assert m.internal_labels[("LOW",60)]==20
    assert m.internal_positive[("LOW",60)]==4
    assert m.labels[("LOW",60)]==0
    assert m.live_labels==0
    assert m.internal_live_labels==20


def test_old_checkpoint_shape_upgrades_conservatively():
    m=LocalOnlyModel()
    for name in ("internal_models","internal_labels","internal_positive",
                 "internal_thresholds","internal_live_labels"):
        delattr(m,name)
    m._ensure_internal_scope()
    assert m.internal_thresholds[("HIGH",300)]==0.80
    assert not m.internal_ready("HIGH",300)
    r=m.report()
    assert r["internal_tactical"]["teacher"]=="INTERNAL_L3_K1"
    assert r["internal_tactical"]["core_flip_authorized"] is False
