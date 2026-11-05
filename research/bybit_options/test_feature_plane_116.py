from types import SimpleNamespace

from research.bybit_options.feature_plane_116 import build_feature_plane_116
from research.bybit_options.agent_ensemble import evaluate_agents


def _candidate(side="CALL", ask=10.0):
    return SimpleNamespace(
        side=side,
        underlying=80000.0,
        strike=80000.0,
        ask=ask,
        bid=9.8,
        delta=0.52 if side == "CALL" else -0.48,
        gamma=0.0002,
        vega=12.0,
        theta=-3.0,
        mark_iv=0.55,
        open_interest=1000.0,
        volume24h=800.0,
        dte_hours=18.0,
    )


def _context(now):
    return {
        "ws_recent_trades": [
            {"T": now - 10_000, "p": "79900", "v": "1", "S": "Buy"},
            {"T": now - 5_000, "p": "80050", "v": "2", "S": "Buy"},
            {"T": now - 2_000, "p": "80100", "v": "1", "S": "Sell"},
        ],
        "liquidations": [
            {"T": now - 7_000, "p": "80000", "v": "0.5", "S": "Sell"},
        ],
        "ws_orderbook": {
            "b": [["80000", "12"], ["79990", "8"]],
            "a": [["80010", "6"], ["80020", "7"]],
        },
        "ws_ticker": {
            "lastPrice": "80005",
            "markPrice": "80003",
            "indexPrice": "80000",
            "prevPrice24h": "79000",
            "price24hPcnt": "0.012",
            "fundingRate": "0.0001",
            "openInterest": "15000",
            "openInterestValue": "1200000000",
            "turnover24h": "2500000000",
            "volume24h": "30000",
            "bid1Price": "80000",
            "ask1Price": "80010",
        },
    }


def test_feature_plane_is_exactly_116_and_named():
    now = 1_800_000_000_000
    depth = {"spread_fraction": 0.02, "depth_balance": 0.8, "exitability": 0.7, "liquidity_score": 0.8}
    plane = build_feature_plane_116(_context(now), _candidate(), depth, now)
    assert plane["count"] == 116
    assert len(plane["names"]) == 116
    assert len(plane["values"]) == 116
    assert len(set(plane["names"])) == 116


def test_five_agents_return_bounded_consensus():
    now = 1_800_000_000_000
    depth = {"spread_fraction": 0.02, "depth_balance": 0.8, "exitability": 0.7, "liquidity_score": 0.8}
    cand = _candidate()
    plane = build_feature_plane_116(_context(now), cand, depth, now)
    decision = evaluate_agents(cand, plane, depth, cheapest_valid_ask=8.0)
    assert len(decision.votes) == 5
    assert 0.0 <= decision.consensus <= 1.0
    assert 0 <= decision.quorum <= 5
