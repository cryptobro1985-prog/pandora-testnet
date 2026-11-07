import json

import pytest

from research.hype_quant.feature_bus import FeatureObservation, FeatureSnapshot
from research.hype_quant.feature_contract import INPUT_IDS, TARGET_IDS, METADATA_IDS
from research.hype_quant.features import FeatureState
from research.hype_quant.raw_state import RawMarketState
from research.hype_local_only.live_features import live_to_archive_features
from research.hype_local_v5 import context_capture


def observation(**kwargs):
    return FeatureObservation(**{"name":"mark_price","point_ids":(2,),"value":100.0,
                                 "source_ts_ms":1000,"received_ts_ms":1001,"source":"ticker",
                                 "max_age_ms":1000,**kwargs})


def test_contract_partition_and_metadata_are_forbidden():
    assert (len(INPUT_IDS),len(TARGET_IDS),len(METADATA_IDS))==(86,28,2)
    for ident in TARGET_IDS|METADATA_IDS:
        assert observation(point_ids=(ident,)).evaluate(1100)["availability_state"]=="forbidden"


@pytest.mark.parametrize("kwargs,expected",[
    ({"source_ts_ms":1200,"received_ts_ms":1201},"future"),
    ({"received_ts_ms":1201},"future"),
    ({"source_ts_ms":1002,"received_ts_ms":1001},"unreliable"),
    ({"source_ts_ms":None,"received_ts_ms":None},"missing"),
    ({"source_ts_ms":1},"stale"),
    ({"value":float("nan")},"missing"),
    ({"received_ts_ms":None,"historical":True},"source_time_only"),
    ({"source_ts_ms":None},"receive_time_only"),
    ({"name":"live__strict_true"},"forbidden"),
    ({"name":"live__point_107"},"forbidden"),
])
def test_observation_boundary(kwargs,expected):
    evaluated=observation(**kwargs).evaluate(1100)
    assert evaluated["availability_state"]==expected
    assert evaluated["missing_or_unreliable"]==(expected not in {"available","source_time_only","receive_time_only"})


def test_evidence_lists_every_input_without_fabricated_values():
    snap=FeatureSnapshot(1100,(observation(),))
    assert snap.model_values=={"mark_price":100.0}
    evidence=snap.as_dict()
    assert len(evidence["contract_input_availability"])==86
    assert evidence["contract_input_availability"]["44"]["availability_state"]=="unavailable"


def test_unknown_streams_do_not_turn_into_zero_counts():
    state=FeatureState()
    _,features=state.update_micro({"ts_ms":100_000,"mid":100.0})
    assert not any(k.startswith(("trade_","liq_","book_bid_add_","book_ask_cancel_")) for k in features)
    assert features["book_valid_raw"]==0.0


def test_partial_trade_window_is_reported_and_excluded_until_warm():
    state=FeatureState()
    def trade(ts):state.update_event({"kind":"trade","received_ts_ms":ts,"exchange_ts_ms":ts-1,
                                     "price":100,"qty":1,"side":"Buy"})
    trade(1000)
    _,features=state.update_micro({"ts_ms":2000,"mid":100})
    assert "trade_count_60s" not in features
    evidence={r["name"]:r for r in state.last_feature_snapshot.as_dict()["features"]}
    assert evidence["trade_count_60s"]["missing_reason"]=="partial_window_coverage"
    trade(61_000)
    _,features=state.update_micro({"ts_ms":61_001,"mid":100})
    assert features["trade_count_60s"]==1.0


def test_ticker_delta_does_not_refresh_stale_oi_or_mark():
    state=FeatureState()
    state.update_event({"kind":"ticker","received_ts_ms":1000,"exchange_ts_ms":999,
                        "data":{"markPrice":"100","openInterest":"1000"}})
    state.update_event({"kind":"ticker","received_ts_ms":701_000,"exchange_ts_ms":700_999,
                        "data":{"lastPrice":"101"}})
    _,features=state.update_micro({"ts_ms":701_001,"mid":101.0})
    assert "mark_price" not in features
    assert "open_interest_full" not in features
    rejected={r["name"]:r for r in state.last_feature_snapshot.as_dict()["features"]}
    assert rejected["open_interest_full"]["availability_state"]=="stale"
    assert rejected["mark_price"]["received_ts_ms"]==1000


def test_basis_rejects_one_constituent_with_invalid_source_clock():
    state=FeatureState()
    state.update_event({"kind":"ticker","received_ts_ms":1001,"exchange_ts_ms":1002,"data":{"markPrice":"100"}})
    state.update_event({"kind":"ticker","received_ts_ms":1005,"exchange_ts_ms":1000,"data":{"indexPrice":"99"}})
    _,features=state.update_micro({"ts_ms":1100,"mid":100})
    assert "basis_bps" not in features


def test_micro_oi_keeps_original_source_and_receive_clock():
    state=FeatureState()
    _,features=state.update_micro({"ts_ms":10_000,"mid":100,"open_interest":123,
                                  "oi_ts_ms":9900,"oi_exchange_ts_ms":9800})
    assert features["open_interest_full"]==123
    evidence={r["name"]:r for r in state.last_feature_snapshot.as_dict()["features"]}
    assert evidence["open_interest_full"]["source_ts_ms"]==9800
    assert evidence["open_interest_full"]["received_ts_ms"]==9900


def test_trade_extrema_captures_transient_trade_between_sampled_book_mids():
    state=FeatureState()
    state.update_micro({"ts_ms":1000,"mid":100})
    for recv,source,price in [(1500,1490,100),(2000,1990,110),(2500,2490,98),(3000,1500,101),
                              (3500,6000,999),(6000,5990,1000)]:
        state.update_event({"kind":"trade","received_ts_ms":recv,"exchange_ts_ms":source,
                            "price":price,"qty":1,"side":"Buy"})
    extremes=state.causal_trade_extrema(1000,5000)
    assert extremes["high"]=={"price":110.0,"source_ts_ms":1990,"received_ts_ms":2000}
    assert extremes["low"]=={"price":98.0,"source_ts_ms":2490,"received_ts_ms":2500}
    assert extremes["trade_count"]==4
    assert not extremes["complete_window"]
    assert state.causal_trade_extrema(1000,1100)["high"] is None


def test_future_source_or_receive_does_not_enter_price_flow_or_ticker():
    state=FeatureState()
    state.update_event({"kind":"trade","received_ts_ms":1000,"exchange_ts_ms":5000,
                        "price":100,"qty":1,"side":"Buy"})
    state.update_event({"kind":"ticker","received_ts_ms":5000,"exchange_ts_ms":4999,
                        "data":{"markPrice":"500"}})
    _,features=state.update_micro({"ts_ms":2000,"mid":100})
    assert "trade_count_5s" not in features
    assert "last_trade_price_rel" not in features
    assert "mark_price" not in features


def test_future_raw_frame_does_not_leak_through_transport_counters():
    state=FeatureState()
    state.update_raw_frame({"received_ts_ms":5000,"raw_text":json.dumps({"op":"ping"})})
    _,features=state.update_micro({"ts_ms":2000,"mid":100})
    assert "raw_frames_seen" not in features
    assert "control_frames" not in features


@pytest.mark.parametrize("received,source,as_of",[(5000,4999,2000),(1000,999,200_000),(1000,5000,2000)])
def test_price_fallback_cannot_launder_future_or_stale_ticker(received,source,as_of):
    state=FeatureState()
    state.update_event({"kind":"ticker","received_ts_ms":received,"exchange_ts_ms":source,
                        "data":{"lastPrice":"500"}})
    with pytest.raises(ValueError,match="no valid price"):
        state.update_micro({"ts_ms":as_of})


def test_future_dated_snapshot_cannot_set_current_price():
    with pytest.raises(ValueError,match="prediction clock"):
        FeatureState().update_micro({"ts_ms":5000,"received_ts_ms":5001,"mid":500},as_of_ms=2000)


def test_candles_require_receipt_close_and_confirmation():
    state=FeatureState()
    for start,confirm,received,source in [(60_000,True,200_000,120_000),
                                          (120_000,False,200_000,190_000),
                                          (180_000,True,300_000,240_000),
                                          (240_000,True,250_000,300_000)]:
        state.candles["1"][start]={"start_ms":start,"confirm":confirm,"received_ts_ms":received,
                                   "source_timestamp_ms":source,"open":100,"high":102,"low":99,"close":101}
    assert [r["start_ms"] for r in state.available_candles("1",250_000)]==[60_000]


def test_old_checkpoint_candles_without_receipt_cannot_leak():
    state=FeatureState()
    state.candles["60"][3_600_000]={"start_ms":3_600_000,"open":100,"high":150,"low":50,"close":130}
    assert state.available_candles("60",8_000_000)==[]


def test_rest_bar_that_closed_after_fetch_was_not_available_at_fetch():
    state=FeatureState()
    state.update_market_context({"received_ts_ms":180_000,"candles":{"1":[
        {"start_ms":120_000,"received_ts_ms":179_999,"open":100,"high":102,"low":99,"close":101}]}})
    assert state.available_candles("1",180_001)==[]


def test_live_adapter_filters_target_aliases_and_future_candles():
    state=FeatureState()
    state.update_micro({"ts_ms":600_001,"mid":100})
    features=live_to_archive_features("LOW",60,99,100,{"strict_true":1,"point_107":1,"label_available_ms":500},state)
    assert not any("strict_true" in k or "point_107" in k or "label_available_ms" in k for k in features)
    assert features["m1__age_s"]==60.0
    assert "atr_h1_frac" not in features


def test_micro_prediction_uses_explicit_receipt_clock_and_rejects_replay():
    state=FeatureState()
    state.update_micro({"ts_ms":1000,"received_ts_ms":1100,"mid":100})
    assert state.last_feature_snapshot.as_of_ms==1100
    with pytest.raises(ValueError,match="strictly"):
        state.update_micro({"ts_ms":1000,"received_ts_ms":1100,"mid":100})


def raw(state,recv,msg):
    state.ingest_envelope({"received_ts_ms":recv,"raw_text":json.dumps(msg)})


def test_raw_book_requires_snapshot_and_stops_after_bad_sequence():
    state=RawMarketState()
    def book(kind,u,seq):return {"topic":"orderbook.50.HYPEUSDT","type":kind,"ts":1000,
                               "data":{"u":u,"seq":seq,"b":[[99,1]],"a":[[101,1]]}}
    raw(state,1000,book("delta",2,2))
    assert "raw_best_bid" not in state.features(1000)
    raw(state,1001,book("snapshot",10,10))
    features=state.features(1002)
    assert features["raw_best_bid"]==99
    assert "bid_add_notional_raw_60s" not in features
    raw(state,1003,book("delta",9,9))
    assert "raw_best_bid" not in state.features(1004)
    raw(state,1005,book("delta",1,1))
    assert state.features(1006)["raw_best_bid"]==99


def test_raw_historical_query_cannot_see_future_received_trades():
    state=RawMarketState()
    raw(state,2000,{"topic":"publicTrade.HYPEUSDT","ts":1999,"data":[{"T":1999,"S":"Buy","p":"100","v":"1"}]})
    assert "trade_count_5s" not in state.features(1500)
    assert state.features(2001)["trade_count_5s"]==1
    assert "raw_best_bid" not in state.features(2001)


def test_collector_records_response_completion_not_request_start(monkeypatch):
    moments=iter([1.0,5.0])
    monkeypatch.setattr(context_capture.time,"time",lambda:next(moments))
    response=context_capture.safe(lambda:{"answer":1})
    assert response["request_started_ts_ms"]==1000
    assert response["received_ts_ms"]==5000


def test_structural_collector_excludes_unfinished_and_not_yet_received_bars(monkeypatch):
    monkeypatch.setattr(context_capture.time,"time",lambda:180.0)
    def bar(start,low,high,received):return {"start_ms":start,"open":100,"close":100,"high":high,"low":low,"received_ts_ms":received}
    snapshot=context_capture.structural_snapshot({"1":[bar(60_000,99,101,130_000),bar(120_000,1,999,181_000),bar(180_000,0.1,9999,180_000)]},{"lastPrice":"100"})
    assert snapshot["rolling_60m_low"]==99
    assert snapshot["rolling_60m_high"]==101
