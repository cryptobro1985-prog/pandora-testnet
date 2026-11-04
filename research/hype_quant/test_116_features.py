#!/usr/bin/env python3
from __future__ import annotations
import json
from research.hype_quant.features import FeatureState
from research.hype_quant.feature_contract import INPUT_IDS, TARGET_IDS, METADATA_IDS

def env(ts,seq,msg):
    return {"received_ts_ms":ts,"receipt_sequence":seq,"raw_text":json.dumps(msg,separators=(",",":")),"_source_path":"synthetic"}

def main():
    s=FeatureState()
    t0=1_800_000_000_000
    bids=[[f"{100-i*0.01:.2f}",f"{10+i}"] for i in range(50)]
    asks=[[f"{100.01+i*0.01:.2f}",f"{11+i}"] for i in range(50)]
    s.update_raw_frame(env(t0,1,{"op":"subscribe","success":True}))
    s.update_raw_frame(env(t0+1,2,{"topic":"orderbook.50.HYPEUSDT","type":"snapshot","ts":t0,
        "data":{"u":1,"seq":100,"b":bids,"a":asks}}))
    s.update_raw_frame(env(t0+2,3,{"topic":"publicTrade.HYPEUSDT","ts":t0+2,"data":[
        {"T":t0+1,"seq":1,"S":"Buy","p":"100.00","v":"2","L":"PlusTick","BT":False,"RPI":False},
        {"T":t0+2,"seq":2,"S":"Sell","p":"99.99","v":"1","L":"MinusTick","BT":False,"RPI":False}
    ]}))
    s.update_raw_frame(env(t0+3,4,{"topic":"allLiquidation.HYPEUSDT","ts":t0+3,
        "data":[{"T":t0+3,"S":"Buy","p":"99.8","v":"3"}]}))
    s.update_raw_frame(env(t0+4,5,{"topic":"tickers.HYPEUSDT","ts":t0+4,"data":{
        "lastPrice":"100","markPrice":"100.02","indexPrice":"99.98","openInterest":"100000",
        "fundingRate":"0.0001","turnover24h":"50000000","volume24h":"500000",
        "highPrice24h":"105","lowPrice24h":"95","price24hPcnt":"0.03",
        "bid1Price":"100","ask1Price":"100.01","bid1Size":"10","ask1Size":"11"}}))

    candles={}
    for tf,ms in (("1",60_000),("3",180_000),("5",300_000),("60",3_600_000)):
        rows=[]
        for j in range(8,0,-1):
            st=t0-j*ms
            rows.append({"start_ms":st,"open":99.0,"high":101.0,"low":98.5,"close":100.0,
                         "volume":1000+j,"turnover":100000+j,"interval":tf})
        candles[tf]=rows
    market={"received_ts_ms":t0+5,"initial_backfill":True,"candles":candles,
            "ticker":{"lastPrice":"100","markPrice":"100.02","indexPrice":"99.98","openInterest":"100000",
                      "fundingRate":"0.0001","turnover24h":"50000000","volume24h":"500000"},
            "server_time":{"ok":True,"value":{"api_time_ms":t0}},
            "instrument":{"priceScale":"2","leverageFilter":{"minLeverage":"1","maxLeverage":"25","leverageStep":"0.01"},
                          "priceFilter":{"tickSize":"0.01"},"lotSizeFilter":{"qtyStep":"0.001","minOrderQty":"0.001"}},
            "account_ratio":{"buyRatio":"0.58","sellRatio":"0.42"}}
    s.update_market_context(market)
    s.update_structural_context({"ts_ms":t0+5,"last_price":100.0,"mark_price":100.02,"index_price":99.98,
        "rolling_60m_low":98.0,"rolling_60m_high":102.0,"rolling_6h_low":95.0,"rolling_6h_high":105.0,
        "rolling_24h_low":90.0,"rolling_24h_high":110.0,"basis_bps":4.0,"open_interest":100000.0,
        "oi_notional":10000000.0,"funding_rate":0.0001,"turnover_24h":50000000.0,"volume_24h":500000.0,
        "bybit_server_time_ms":t0,"runner_clock_offset_ms":5.0,"long_holder_ratio":0.58,
        "short_holder_ratio":0.42,"long_short_holder_ratio":0.58/0.42})

    # Feed enough price history to activate return/persistence features.
    for k in range(1,7):
        ts=t0+5+k*5_000
        price=100.0+0.01*k
        micro={"ts_ms":ts,"mid":price,"best_bid":price-0.005,"best_ask":price+0.005,
               "spread_bps":1.0,"book_valid":True,"book_imbalance_5":0.1,"book_imbalance_25":0.08,
               "bid_depth_5":100000.0,"ask_depth_5":90000.0,"bid_depth_25":300000.0,"ask_depth_25":280000.0,
               "flow_imbalance_5s":0.2,"flow_imbalance_15s":0.1,"flow_imbalance_60s":0.05,
               "buy_notional_60s":10000.0,"sell_notional_60s":9000.0,
               "long_liq_notional_5s":100.0,"short_liq_notional_5s":50.0,
               "long_liq_notional_15s":100.0,"short_liq_notional_15s":50.0,
               "long_liq_notional_60s":100.0,"short_liq_notional_60s":50.0,
               "open_interest":100000.0,"oi_change_since_prev_poll_pct":0.01,
               "ask_replenishment_proxy_ratio_60s":1.2,"bid_replenishment_proxy_ratio_60s":1.1,
               "book_invalidations":0,"channel_coverage_seconds":120}
        p,x=s.update_micro(micro)

    required=[
        "l50_bid_50_dist_bps","l50_ask_50_log_qty",
        "m1_lag0_close_rel","m3_lag0_close_rel","m5_lag0_close_rel","h1_lag0_close_rel",
        "flow_imbalance_raw_5s","trade_count_60s","liq_count_60s",
        "instrument_leverageFilter_maxLeverage","account_buy_ratio",
        "struct_long_short_holder_ratio","basis_bps","open_interest_full",
        "raw_frames_seen","book_sequence_raw"
    ]
    missing=[k for k in required if k not in x]
    assert not missing, missing
    assert len(x)>=180, len(x)
    c=s.coverage_report()
    assert len(INPUT_IDS)>0 and len(TARGET_IDS)>0 and len(METADATA_IDS)>0
    assert c["point_count"]==116
    assert not (set(c["input_ids"]) & set(c["target_eval_ids"]))
    print("HYPE_QUANT_116_FEATURE_TEST_OK",len(x),c["seen_input_count"])

if __name__=="__main__":
    main()
