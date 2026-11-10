from research.hype_movement_signature.learner import MovementSignatureLearner


def test_labels_mature_and_predictions_become_ready():
    m = MovementSignatureLearner(round_trip_cost=0.0005)
    px = 100.0
    for i in range(80):
        ts = i * 30_000
        px *= 1.0005
        out = m.observe(ts, px, {"flow_imbalance_raw_60s": 0.5, "buy_efficiency_60s": 1.0})
    assert sum(m.long_labels.values()) > 0
    assert out["research_only"] is True


def test_position_tracks_mfe_and_recoil():
    m = MovementSignatureLearner()
    m.paper_open(0, 100.0, 1)
    m.observe(30_000, 102.0, {})
    out = m.observe(60_000, 101.0, {})
    p = out["position"]
    assert p["mfe"] > 0
    assert p["mfe_recoil"] > 0


def test_no_real_orders_flag():
    m = MovementSignatureLearner()
    out = m.observe(0, 100.0, {})
    assert out["real_orders"] is False
