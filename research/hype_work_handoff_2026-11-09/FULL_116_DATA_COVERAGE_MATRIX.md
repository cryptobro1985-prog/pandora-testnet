# HYPE · покрытие 116-point contract

Процент показывает долю ранних решений с хотя бы одним допустимым значением по ID. Источник исторических минуток указан для каждого блока. Live отражает наличие с момента старта checkpoint и возраст последнего наблюдения. Доля валидных live-решений не измерена.
В master также есть снимки Jul–Aug и Oct–Nov с секундными агрегатами сделок. Матрица показывает общую M1-плоскость. Архивные L50 и ликвидации Jul–Aug ожидают проверки непрерывности, времени получения и масок по каждому окну.

- H1 · 01_JUL12_AUG07_FULL_MICRO · 36419 M1 · 2396 решений · 13650399622/01_JUL12_AUG07_FULL_MICRO/compact_1m.jsonl.gz
- H2 · 02_AUG08_SEP01 · 34559 M1 · 2322 решений · 13650399622/02_AUG08_SEP01/compact_1m.jsonl.gz
- H3 · 03_SEP01_OCT01 · 43199 M1 · 3159 решений · 13650399622/03_SEP01_OCT01/compact_1m.jsonl.gz
- H4 · 04_OCT04_NOV03 · 43198 M1 · 3114 решений · 13650399622/04_OCT04_NOV03/compact_1m.jsonl.gz

| ID | Поле | Роль | Допуск / X | H1 | H2 | H3 | H4 | Live |
|---:|---|---|---|---|---|---|---|---|
| 1 | Last Price | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.2 s |
| 2 | Mark Price | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.2 s |
| 3 | Index Price | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.2 s |
| 4 | M1 OHLCV/turnover | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.6 s |
| 5 | M3 OHLCV/turnover | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.6 s |
| 6 | M5 OHLCV/turnover | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.6 s |
| 7 | H1 OHLCV/turnover | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.6 s |
| 8 | Initial structural backfill | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 51.4 s |
| 9 | Rolling 60m high/low | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 48.7 s |
| 10 | Rolling ~6h high/low | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 48.7 s |
| 11 | Rolling ~24h high/low | INPUT_CAUSAL | да / да | 94.8% verified_causal | 94.3% verified_causal | 95.9% verified_causal | 97.2% verified_causal | seen · 48.7 s |
| 12 | All public executed trades | INPUT_CAUSAL | да / да | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | seen · 0.0 s |
| 13 | Aggressor side | INPUT_CAUSAL | да / да | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | seen · 0.0 s |
| 14 | Execution price | INPUT_CAUSAL | да / да | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | seen · 0.0 s |
| 15 | Execution quantity | INPUT_CAUSAL | да / да | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | seen · 0.0 s |
| 16 | Execution notional | INPUT_CAUSAL | да / да | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | 100.0% aggregate_or_derived | seen · 0.0 s |
| 17 | Executed buy notional | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 18 | Executed sell notional | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 19 | Executed trade count | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 20 | Flow imbalance family | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 21 | Flow imbalance 5s | INPUT_CAUSAL | да / нет | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 22 | Flow imbalance 15s | INPUT_CAUSAL | да / нет | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 23 | Flow imbalance 60s | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 24 | Buyer/seller dominance transition | INPUT_CAUSAL | да / да | 72.7% verified_causal | 73.0% verified_causal | 71.9% verified_causal | 70.5% verified_causal | seen · 0.0 s |
| 25 | Cumulative flow/CVD-like balance | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 26 | Price response to buy flow | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 27 | Price response to sell flow | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 28 | Buyer price efficiency | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 29 | Seller price efficiency | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 30 | Old-side efficiency decay | INPUT_CAUSAL | да / да | 72.7% verified_causal | 73.0% verified_causal | 71.8% verified_causal | 70.5% verified_causal | seen · 0.0 s |
| 31 | New-side efficiency growth | INPUT_CAUSAL | да / да | 72.7% verified_causal | 73.0% verified_causal | 71.9% verified_causal | 70.5% verified_causal | seen · 0.0 s |
| 32 | New-side price response 30-60s | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 33 | New-side price response ~3m | INPUT_CAUSAL | да / да | 72.7% verified_causal | 72.9% verified_causal | 71.8% verified_causal | 70.4% verified_causal | seen · 0.0 s |
| 34 | New-side price response ~5m | INPUT_CAUSAL | да / да | 53.2% verified_causal | 53.0% verified_causal | 52.2% verified_causal | 51.1% verified_causal | seen · 0.0 s |
| 35 | Directional persistence | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 36 | Retracement from running extreme | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 48.7 s |
| 37 | Candidate survival without same-side extension | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 48.7 s |
| 38 | Running high | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 48.7 s |
| 39 | Running low | INPUT_CAUSAL | да / да | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 48.7 s |
| 40 | Candidate invalidation on same-side extension | INPUT_CAUSAL | да / нет | 94.4% verified_causal | 94.0% verified_causal | 94.2% verified_causal | 94.9% verified_causal | seen · 48.7 s |
| 41 | Current reversal attempts in active swing | INPUT_CAUSAL | да / да | 100.0% candidate_lineage_proxy | 100.0% candidate_lineage_proxy | 100.0% candidate_lineage_proxy | 100.0% candidate_lineage_proxy | seen · 0.0 s |
| 42 | Prior False attempts in same swing | INPUT_CAUSAL | да / да | 100.0% candidate_lineage_proxy | 100.0% candidate_lineage_proxy | 100.0% candidate_lineage_proxy | 100.0% candidate_lineage_proxy | seen · 0.0 s |
| 43 | Current-vs-prior-attempt comparison | INPUT_CAUSAL | да / да | 94.4% candidate_lineage_proxy | 94.0% candidate_lineage_proxy | 94.2% candidate_lineage_proxy | 94.9% candidate_lineage_proxy | seen · 0.0 s |
| 44 | Full Bybit L50 orderbook state/replay | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 45 | Bid levels | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 46 | Ask levels | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 47 | Orderbook level price | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 48 | Orderbook level quantity | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 49 | Orderbook depth changes | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 50 | Liquidity replenishment evidence | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 51 | Liquidity disappearance | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 52 | Cancellations/withdrawal evidence | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 53 | Bid absorption evidence/proxy | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 54 | Ask absorption evidence/proxy | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 55 | Book imbalance | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 56 | Book validity | INPUT_QUALITY | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 57 | Book sequence/reset/invalidation | INPUT_QUALITY | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 58 | Open interest | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 59 | OI change | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 60 | OI freshness | INPUT_QUALITY | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 61 | Price/OI relationship | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 62 | Funding rate | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 63 | 24h volume | INPUT_CAUSAL | да / да | 94.8% aggregate_or_derived | 94.3% aggregate_or_derived | 95.9% aggregate_or_derived | 97.2% aggregate_or_derived | seen · 0.0 s |
| 64 | 24h turnover | INPUT_CAUSAL | да / да | 94.8% aggregate_or_derived | 94.3% aggregate_or_derived | 95.9% aggregate_or_derived | 97.2% aggregate_or_derived | seen · 0.0 s |
| 65 | Public liquidation events | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 66 | Liquidation price | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 67 | Liquidation size | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 68 | Liquidation side | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 69 | Liquidation notional | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 70 | Long-liquidation aggregate | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 71 | Short-liquidation aggregate | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 72 | Liquidation event count | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 73 | Liquidation clusters | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 74 | Liquidation burst vs price | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 75 | Liquidation burst vs flow | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 76 | Liquidation burst vs OI | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 77 | Raw receive timestamps | INPUT_QUALITY | да / нет | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 78 | Microstructure snapshot timestamps | INPUT_QUALITY | да / нет | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 79 | Intra-segment gap detection | INPUT_QUALITY | да / нет | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 80 | Cross-segment continuity | INPUT_QUALITY | да / нет | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | 100.0% verified_causal | seen · 0.0 s |
| 81 | Provenance/run/commit/source | METADATA_ONLY | нет / нет | verified_manifest | verified_manifest | verified_manifest | verified_manifest | checkpoint_provenance |
| 82 | Replayable primary data | METADATA_ONLY | нет / нет | compact_only | compact_only | compact_only | compact_only | raw_capture_inventory |
| 83 | Current structural state | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 84 | Last confirmed structural Local High | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 85 | Last confirmed structural Local Low | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 86 | Active swing direction | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 87 | Running structural extreme | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 88 | Structural maturity | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 89 | v6 WATCH state | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 90 | v6 FORMING state | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 91 | v6 EARLY_HIGH_CONFIDENCE state | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 92 | v6 CONFIRMED state | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 93 | v6 HARD_CONFIRMED state | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 94 | Candidate timestamp | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 95 | First EARLY_HIGH_CONFIDENCE timestamp | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 96 | Confirmation timestamp | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 97 | Signal delay from extreme | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 98 | Signal price error | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 99 | First accepted signal True/False | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 100 | First-accepted precision | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 101 | False-local rate | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 102 | Coverage/recall | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 103 | Median delay | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 104 | P90 delay | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 105 | Median price error | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 106 | P90 price error | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 107 | Strict H1 Local High/Low label set | TARGET_EVAL | нет / нет | strict_teacher | strict_teacher | strict_teacher | strict_teacher | not_measured |
| 108 | Internal locals inside larger movement | TARGET_EVAL | нет / нет | offline_internal_scope | offline_internal_scope | offline_internal_scope | offline_internal_scope | not_measured |
| 109 | Significant extrema timing label set | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 110 | Time-aligned causal sequence Structure→Flow→Book→OI/Liq→Price response | TARGET_EVAL | нет / нет | reserved_evaluation | reserved_evaluation | reserved_evaluation | reserved_evaluation | not_measured |
| 111 | Bybit server time + runner clock offset | INPUT_CAUSAL | да / нет | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 112 | Instrument metadata: tickSize/qtyStep/contract/risk/funding metadata | INPUT_CAUSAL | да / нет | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 113 | Public long/short holder ratio (5m) | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 48.7 s |
| 114 | Mark-index basis / basis bps | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 115 | OI notional (OI × reference price) | INPUT_CAUSAL | да / нет | 0.0% uncertified | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
| 116 | Collector connection/restart/data-gap health markers | INPUT_QUALITY | да / нет | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | 0.0% unavailable | seen · 0.0 s |
