from research.bybit_options.executable_quotes import walk_book, round_trip_quote, paper_action


def test_buy_walks_asks_and_sell_walks_bids():
    book = {"result": {"a": [["10", "1"], ["12", "2"]], "b": [["9", "1"], ["8", "2"]]}}
    assert walk_book(book, "BUY", 2)["vwap"] == 11
    assert walk_book(book, "SELL", 2)["vwap"] == 8.5


def test_insufficient_depth_does_not_quote_fill():
    book = {"result": {"a": [["10", "1"]], "b": [["9", "1"]]}}
    assert not walk_book(book, "BUY", 2)["executable"]


def test_spread_and_fees_are_counted():
    book = {"result": {"a": [["10", "2"]], "b": [["9", "2"]]}}
    q = round_trip_quote(book, 1, 1, 0.001, 0.001)
    assert q["executable"]
    assert abs(q["immediate_round_trip_pnl"] + 1.019) < 1e-9


def test_emergency_sell_and_data_risk():
    assert paper_action("HOLD", -0.2, "CALL", True, True, False) == "EMERGENCY_SELL"
    assert paper_action("HOLD", 0.3, "CALL", False, True, False) == "DATA_RISK_REVIEW"
    assert paper_action("FLAT", 0.3, "CALL", True, True, False) == "BUY_CALL"
