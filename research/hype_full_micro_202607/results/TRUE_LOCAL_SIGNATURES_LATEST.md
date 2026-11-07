# HYPE True Local Signatures — exact extreme timestamp

This analysis is the corrected objective: all historical strict Local LOW/HIGH are examined at the exact extreme timestamp. No +60/+180/+300 second post-extreme information is used as an input signature.

Strict labels: 48; exact locals inside snapshot period: 47. One warm-up label can fall outside the July-12 17:00 UTC snapshot period.

## LOW
True locals: 23; hard-negative same-side extrema: 632.

Top exact-moment discriminators:

- fullmicro_bid_45_log_qty: true median=5.2949617; false median=4.5469053; directional AUC=0.697; group=L50_BOOK
- fullmicro_ask_01_dist_bps: true median=0.09141687; false median=0.086037049; directional AUC=0.655; group=L50_BOOK
- fullmicro_bid_01_dist_bps: true median=-0.09141687; false median=-0.086037049; directional AUC=0.655; group=L50_BOOK
- fullmicro_spread_bps: true median=0.18283374; false median=0.1720741; directional AUC=0.655; group=L50_BOOK
- imbalance_30s: true median=-0.24546344; false median=-0.44734698; directional AUC=0.651; group=FLOW_PRICE_RESPONSE
- rev_flow_30s: true median=-0.24546344; false median=-0.44734698; directional AUC=0.651; group=FLOW_PRICE_RESPONSE
- distance_low_60m_bps: true median=-13.734138; false median=-7.675485; directional AUC=0.650; group=STRUCTURE
- distance_low_6h_bps: true median=-13.734138; false median=-7.2869134; directional AUC=0.649; group=STRUCTURE
- imbalance_15s: true median=-0.27187737; false median=-0.54386675; directional AUC=0.638; group=FLOW_PRICE_RESPONSE
- rev_flow_15s: true median=-0.27187737; false median=-0.54386675; directional AUC=0.638; group=FLOW_PRICE_RESPONSE
- fullmicro_ticker_high_price: true median=59.942; false median=60.456; directional AUC=0.635; group=TICKER_24H
- fullmicro_ticker_last_price: true median=56.559; false median=58.166; directional AUC=0.633; group=TICKER_24H
- fullmicro_mark_price_mark_price: true median=56.577; false median=58.2015; directional AUC=0.631; group=MARK_INDEX_FUNDING
- fullmicro_mark_price_index_price: true median=56.619; false median=58.2395; directional AUC=0.631; group=MARK_INDEX_FUNDING
- fullmicro_ask_49_dist_bps: true median=9.2331039; false median=8.8570537; directional AUC=0.628; group=L50_BOOK

Group strength:

- L50_BOOK: best AUC=0.697; top-5 mean AUC=0.658
- FLOW_PRICE_RESPONSE: best AUC=0.651; top-5 mean AUC=0.637
- STRUCTURE: best AUC=0.650; top-5 mean AUC=0.622
- TICKER_24H: best AUC=0.635; top-5 mean AUC=0.609
- MARK_INDEX_FUNDING: best AUC=0.631; top-5 mean AUC=0.598
- OPEN_INTEREST: best AUC=0.593; top-5 mean AUC=0.557
- LIQUIDATIONS: best AUC=0.544; top-5 mean AUC=0.537

## HIGH
True locals: 24; hard-negative same-side extrema: 573.

Top exact-moment discriminators:

- distance_high_6h_bps: true median=-8.6482431; false median=-5.2177981; directional AUC=0.638; group=STRUCTURE
- distance_high_60m_bps: true median=-9.0970361; false median=-5.6688306; directional AUC=0.626; group=STRUCTURE
- position_60m: true median=1.0784141; false median=1.0521886; directional AUC=0.625; group=STRUCTURE
- fullmicro_bid_12_log_qty: true median=4.3182768; false median=3.7525582; directional AUC=0.622; group=L50_BOOK
- sell_30s_log: true median=10.962026; false median=9.7974707; directional AUC=0.619; group=FLOW_PRICE_RESPONSE
- buy_30s_log: true median=11.344396; false median=10.633789; directional AUC=0.614; group=FLOW_PRICE_RESPONSE
- fullmicro_ask_14_log_qty: true median=2.9155469; false median=3.6370597; directional AUC=0.614; group=L50_BOOK
- fullmicro_bid_09_log_qty: true median=3.9258957; false median=3.448399; directional AUC=0.612; group=L50_BOOK
- fullmicro_bid_37_log_qty: true median=4.3216; false median=4.4834544; directional AUC=0.612; group=L50_BOOK
- position_6h: true median=1.0317422; false median=1.022549; directional AUC=0.611; group=STRUCTURE
- buy_60s_log: true median=12.159778; false median=11.490968; directional AUC=0.609; group=FLOW_PRICE_RESPONSE
- total_30s_log: true median=11.909717; false median=11.195563; directional AUC=0.607; group=FLOW_PRICE_RESPONSE
- fullmicro_ask_19_dist_bps: true median=3.7864164; false median=3.5112676; directional AUC=0.604; group=L50_BOOK
- fullmicro_ask_42_log_qty: true median=4.8801116; false median=4.5011421; directional AUC=0.604; group=L50_BOOK
- fullmicro_bid_48_log_qty: true median=4.1492528; false median=4.5127259; directional AUC=0.603; group=L50_BOOK

Group strength:

- STRUCTURE: best AUC=0.638; top-5 mean AUC=0.615
- L50_BOOK: best AUC=0.622; top-5 mean AUC=0.613
- FLOW_PRICE_RESPONSE: best AUC=0.619; top-5 mean AUC=0.608
- TICKER_24H: best AUC=0.583; top-5 mean AUC=0.563
- LIQUIDATIONS: best AUC=0.548; top-5 mean AUC=0.536
- OPEN_INTEREST: best AUC=0.539; top-5 mean AUC=0.518
- MARK_INDEX_FUNDING: best AUC=0.530; top-5 mean AUC=0.517
