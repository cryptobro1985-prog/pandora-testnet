import unittest
from research.bybit_options.scoring import build_candidates, underlying_features


class ScoringTests(unittest.TestCase):
    def test_bullish_context_prefers_call(self):
        ctx = {
            "recent_trades": [
                {"price": "100", "size": "10", "side": "Buy"},
                {"price": "101", "size": "15", "side": "Buy"},
                {"price": "101", "size": "1", "side": "Sell"},
            ],
            "orderbook": {"result": {"b": [["100", "20"]], "a": [["101", "2"]]}},
            "liquidations": [{"p": "100", "v": "10", "S": "Sell"}],
            "ticker": {"price24hPcnt": "0.02", "fundingRate": "0.0001"},
        }
        uf = underlying_features(ctx)
        self.assertGreater(uf["direction"], 0)
        now = 1_000_000
        inst = {
            "BTC-X-100-C": {"symbol": "BTC-X-100-C", "baseCoin": "BTC", "optionsType": "Call", "deliveryTime": str(now + 18*3600*1000)},
            "BTC-X-100-P": {"symbol": "BTC-X-100-P", "baseCoin": "BTC", "optionsType": "Put", "deliveryTime": str(now + 18*3600*1000)},
        }
        common = {"underlyingPrice": "100", "bid1Price": "4.8", "ask1Price": "5", "markPrice": "4.9",
                  "markIv": "0.6", "gamma": "0.02", "vega": "0.1", "theta": "-0.1",
                  "openInterest": "100", "volume24h": "50"}
        rows = [{"symbol": "BTC-X-100-C", "delta": "0.5", **common},
                {"symbol": "BTC-X-100-P", "delta": "-0.5", **common}]
        c = build_candidates(rows, inst, ctx, now, 1, 48, 0.35)
        self.assertEqual(c[0].side, "CALL")
        self.assertGreater(c[0].score, c[1].score)

    def test_no_nan(self):
        uf = underlying_features({})
        self.assertTrue(all(v == v for v in uf.values()))


if __name__ == "__main__":
    unittest.main()
