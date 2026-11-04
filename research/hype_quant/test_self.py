#!/usr/bin/env python3
from __future__ import annotations
import copy
import json
import math
import tempfile
from pathlib import Path

from research.hype_quant.feature_contract import INPUT_IDS, TARGET_IDS, METADATA_IDS, contract_summary
from research.hype_quant.features import FeatureState
from research.hype_quant.learner import OnlineQuantLearner, load_config


def candle_rows(end_ms,interval_ms,count,base=100.0):
    out=[]
    first=end_ms-count*interval_ms
    for i in range(count):
        start=first+i*interval_ms
        o=base*(1+0.0002*i)
        c=o*(1+0.0003*math.sin(i/3))
        hi=max(o,c)*1.001
        lo=min(o,c)*0.999
        out.append({"start_ms":start,"open":o,"high":hi,"low":lo,"close":c,
                    "volume":1000+i*3,"turnover":100000+i*100,"interval":str(interval_ms//60000)})
    return out


def full_feature_smoke():
    state=FeatureState()
    base_ts=1_800_000_000_000
    candles={
        "1":candle_rows(base_ts,60_000,40),
        "3":candle_rows(base_ts,180_000,24),
        "5":candle_rows(base_ts,300_000,20),
        "60":candle_rows(base_ts,3_600_000,16),
    }
    state.update_market_context({
        "received_ts_ms":base_ts,"symbol":"HYPEUSDT","initial_backfill":True,
        "candles":candles,
        "ticker":{"lastPrice":"100","markPrice":"100.01","indexPrice":"99.99",
                  "openInterest":"1000000","fundingRate":"0.0001",
                  "volume24h":"1234567","turnover24h":"123456789",
                  "highPrice24h":"105","lowPrice24h":"95","price24hPcnt":"0.02"},
        "server_time":{"ok":True,"value":{"api_time_ms":base_ts-20}},
        "instrument":{"symbol":"HYPEUSDT","priceScale":"3","fundingInterval":"480",
                      "priceFilter":{"tickSize":"0.001","minPrice":"0.001","maxPrice":"100000"},
                      "lotSizeFilter":{"qtyStep":"0.01","minOrderQty":"0.01","maxOrderQty":"100000"},
                      "leverageFilter":{"minLeverage":"1","maxLeverage":"50","leverageStep":"0.01"}},
        "account_ratio":{"buyRatio":"0.54","sellRatio":"0.46"}
    })
    state.update_structural_context({
        "ts_ms":base_ts,"rolling_60m_low":98.0,"rolling_60m_high":102.0,
        "rolling_6h_low":96.0,"rolling_6h_high":104.0,
        "rolling_24h_low":95.0,"rolling_24h_high":105.0,
        "last_price":100.0,"mark_price":100.01,"index_price":99.99,
        "basis_bps":2.0002,"open_interest":1000000.0,"oi_notional":100000000.0,
        "funding_rate":0.0001,"turnover_24h":123456789.0,"volume_24h":1234567.0,
        "bybit_server_time_ms":base_ts-20,"runner_clock_offset_ms":20.0,
        "long_holder_ratio":0.54,"short_holder_ratio":0.46,
        "long_short_holder_ratio":0.54/0.46
    })

    bids=[[100.0-i*0.001,10+i*.1] for i in range(50)]
    asks=[[100.001+i*0.001,11+i*.1] for i in range(50)]
    state.update_event({"kind":"orderbook","received_ts_ms":base_ts,"exchange_ts_ms":base_ts-5,
                        "type":"snapshot","update_id":1,"sequence":1000,"bids":bids,"asks":asks})

    last_x=None
    for i in range(0,311):
        ts=base_ts+i*1000
        p=100.0*(1+0.00001*i+0.0003*math.sin(i/15))
        side="Buy" if i%3 else "Sell"
        state.update_event({"kind":"trade","received_ts_ms":ts,"exchange_ts_ms":ts-15,
                            "side":side,"price":p,"qty":1+(i%7)*0.1})
        if i%17==0:
            state.update_event({"kind":"liquidation","received_ts_ms":ts,"exchange_ts_ms":ts-20,
                                "side":"Buy" if i%34==0 else "Sell","price":p,"qty":2.5})
        if i%30==0:
            state.update_event({"kind":"ticker","received_ts_ms":ts,"exchange_ts_ms":ts-10,
                                "data":{"lastPrice":str(p),"markPrice":str(p*1.00005),
                                        "indexPrice":str(p*0.99995),
                                        "openInterest":str(1000000+i*40),
                                        "fundingRate":"0.0001","volume24h":"1234567",
                                        "turnover24h":"123456789"}})
        if i and i%10==0:
            state.update_event({"kind":"orderbook","received_ts_ms":ts,"exchange_ts_ms":ts-8,
                                "type":"delta","update_id":1+i,"sequence":1000+i,
                                "bids":[[100.0,10+i*.001]],"asks":[[100.001,11+i*.001]]})
        micro={"ts_ms":ts,"best_bid":p-0.0005,"best_ask":p+0.0005,"mid":p,
               "spread_bps":0.1,"book_valid":True,"book_update_id":1+i,
               "book_sequence":1000+i,"book_invalidations":0,
               "book_imbalance_5":0.1,"book_imbalance_25":0.05,
               "bid_depth_5":50000.0,"ask_depth_5":48000.0,
               "bid_depth_25":250000.0,"ask_depth_25":245000.0,
               "flow_imbalance_5s":0.1,"flow_imbalance_15s":0.08,"flow_imbalance_60s":0.04,
               "buy_notional_60s":100000.0,"sell_notional_60s":92000.0,
               "long_liq_notional_5s":0.0,"short_liq_notional_5s":0.0,
               "long_liq_notional_15s":100.0,"short_liq_notional_15s":50.0,
               "long_liq_notional_60s":500.0,"short_liq_notional_60s":300.0,
               "open_interest":1000000+i*40,"oi_change_since_prev_poll_pct":0.001,
               "ask_replenishment_proxy_ratio_60s":1.2,
               "bid_replenishment_proxy_ratio_60s":1.1,
               "channel_coverage_seconds":300.0}
        _,last_x=state.update_micro(micro)

    assert last_x is not None
    coverage=state.coverage_report()
    missing=set(coverage["missing_seen_input_ids"])
    assert not missing, f"synthetic full-state missed input ids: {sorted(missing)}"
    assert len(last_x)>=350, len(last_x)
    assert any(k.startswith("l50_bid_50") for k in last_x)
    assert any(k.startswith("m1_lag") for k in last_x)
    assert "trade_count_300s" in last_x
    assert "liq_count_60s" in last_x
    assert "instrument_priceFilter_tickSize" in last_x
    assert TARGET_IDS.isdisjoint(INPUT_IDS)
    return state,last_x


def learner_smoke(features):
    cfg=copy.deepcopy(load_config(Path("research/hype_quant/config.json")))
    cfg["horizons_seconds"]=[1,2,3]
    cfg["champion"]["min_forward_labels_before_promotion"]=3
    cfg["pattern_memory"]["neighbors"]=3
    q=OnlineQuantLearner(cfg)
    base=100.0
    for i in range(12):
        ts=i*1000
        price=base*(1+0.0005*i)
        q.observe(ts,price,features)
    assert q.labels>0,q.report()
    assert q.challenger[1].n>0
    assert q.max_feature_count>=350
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"q.pkl"
        q.save(p)
        q2=OnlineQuantLearner.load(p)
        assert q2.labels==q.labels
        assert q2.report()["research_only"] is True
    return q


def main():
    c=contract_summary()
    assert c["point_count"]==116
    assert INPUT_IDS|TARGET_IDS|METADATA_IDS==set(range(1,117))
    state,features=full_feature_smoke()
    q=learner_smoke(features)
    print("HYPE_QUANT_116_SELFTEST_OK")
    print(json.dumps({"coverage":state.coverage_report(),"learner":q.report()},indent=2))


if __name__=="__main__":
    main()
