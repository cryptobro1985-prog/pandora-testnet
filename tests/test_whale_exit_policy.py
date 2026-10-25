from risk import evaluate_exit


def _short_local_pullback(features):
    # A short that has already made a clear favorable move and is now bouncing
    # enough to satisfy the generic local-extreme exit.
    return {
        "entry": 100.0,
        "side": -1,
        "leverage": 25.0,
        "peak": 98.0,
        "history": [100.0, 99.5, 99.0, 98.5, 98.0, 98.2, 98.4],
        "features": features,
    }


def test_whale_exit_is_blocked_until_liquidation_target_is_touched():
    features={
        "engine": "whale_liquidation_cluster_v4",
        "victim_side": "long",
        "liquidation_price": 95.0,
        "dynamic_entry_distance_pct": 0.75,
    }
    evaluated,reason=evaluate_exit(_short_local_pullback(features),98.6,"2026-10-25T09:00:00+00:00")
    assert reason is None
    assert evaluated["last_exit_check"]["pre_liquidation_hold"] is True
    assert evaluated["last_exit_check"]["remaining_to_liquidation_pct"] > 0.75
    assert evaluated["last_exit_check"]["local_extreme_exit"] is False


def test_whale_local_exit_resumes_after_liquidation_latch():
    features={
        "engine": "whale_liquidation_cluster_v4",
        "victim_side": "long",
        "liquidation_price": 95.0,
        "liquidation_level_reached_at": "2026-10-25T09:00:00+00:00",
    }
    evaluated,reason=evaluate_exit(_short_local_pullback(features),98.6,"2026-10-25T09:01:00+00:00")
    assert reason == "local_extreme_weakening"
    assert evaluated["last_exit_check"]["pre_liquidation_hold"] is False
    assert evaluated["last_exit_check"]["local_extreme_exit"] is True
