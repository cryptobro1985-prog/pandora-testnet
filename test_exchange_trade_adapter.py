import unittest
from exchange_trade_adapter import (
    normalize_bybit_public_trade, normalize_hyperliquid_trade,
    validate_latency, to_legacy_observation,
)


class ExchangeAdapterTests(unittest.TestCase):
    def test_bybit_buy(self):
        t = normalize_bybit_public_trade({"s":"HYPEUSDT","p":"82.5","v":"2","T":100000,"S":"Buy","i":"abc"})
        self.assertEqual((t.venue,t.symbol,t.aggressor_side),("bybit","HYPE","BUY"))
        self.assertEqual(to_legacy_observation(t)["side"],"B")
        self.assertEqual(validate_latency(t,101000),(True,"fresh"))

    def test_bybit_sell(self):
        t = normalize_bybit_public_trade({"s":"BTCUSDT","p":"70000","v":"0.01","T":100000,"S":"Sell","i":"def"})
        self.assertEqual((t.symbol,t.aggressor_side),("BTC","SELL"))

    def test_stale_fail_closed(self):
        t = normalize_bybit_public_trade({"s":"ETHUSDT","p":"2500","v":"1","T":100000,"S":"Buy","i":"a"})
        self.assertEqual(validate_latency(t,120000),(False,"stale_executed_trade"))

    def test_bad_message(self):
        self.assertIsNone(normalize_bybit_public_trade({"s":"BTCUSDT","p":"NaN","v":"1","T":1,"S":"Buy","i":"x"}))

    def test_hyperliquid(self):
        t = normalize_hyperliquid_trade({"coin":"SOL","px":"120","sz":"3","time":100000,"side":"A","tid":10})
        self.assertEqual((t.venue,t.aggressor_side),("hyperliquid","SELL"))


if __name__ == "__main__":
    unittest.main()
