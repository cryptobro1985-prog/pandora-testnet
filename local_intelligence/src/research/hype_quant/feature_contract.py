"""Canonical 116-point contract for HYPE Quant Learner.

Every point is consumed by the research system. Future/post-analysis points are
never allowed into predictive features; they are labels/evaluation only.
Provenance identifiers are metadata, not predictors, to avoid run/time leakage.
"""
POINTS = [
  {
    "id": 1,
    "title": "Last Price",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 2,
    "title": "Mark Price",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 3,
    "title": "Index Price",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 4,
    "title": "M1 OHLCV/turnover",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 5,
    "title": "M3 OHLCV/turnover",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 6,
    "title": "M5 OHLCV/turnover",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 7,
    "title": "H1 OHLCV/turnover",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 8,
    "title": "Initial structural backfill",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 9,
    "title": "Rolling 60m high/low",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 10,
    "title": "Rolling ~6h high/low",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 11,
    "title": "Rolling ~24h high/low",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 12,
    "title": "All public executed trades",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 13,
    "title": "Aggressor side",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 14,
    "title": "Execution price",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 15,
    "title": "Execution quantity",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 16,
    "title": "Execution notional",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 17,
    "title": "Executed buy notional",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 18,
    "title": "Executed sell notional",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 19,
    "title": "Executed trade count",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 20,
    "title": "Flow imbalance family",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 21,
    "title": "Flow imbalance 5s",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 22,
    "title": "Flow imbalance 15s",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 23,
    "title": "Flow imbalance 60s",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 24,
    "title": "Buyer/seller dominance transition",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 25,
    "title": "Cumulative flow/CVD-like balance",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 26,
    "title": "Price response to buy flow",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 27,
    "title": "Price response to sell flow",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 28,
    "title": "Buyer price efficiency",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 29,
    "title": "Seller price efficiency",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 30,
    "title": "Old-side efficiency decay",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 31,
    "title": "New-side efficiency growth",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 32,
    "title": "New-side price response 30-60s",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 33,
    "title": "New-side price response ~3m",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 34,
    "title": "New-side price response ~5m",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 35,
    "title": "Directional persistence",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 36,
    "title": "Retracement from running extreme",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 37,
    "title": "Candidate survival without same-side extension",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 38,
    "title": "Running high",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 39,
    "title": "Running low",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 40,
    "title": "Candidate invalidation on same-side extension",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 41,
    "title": "Current reversal attempts in active swing",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 42,
    "title": "Prior False attempts in same swing",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 43,
    "title": "Current-vs-prior-attempt comparison",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 44,
    "title": "Full Bybit L50 orderbook state/replay",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 45,
    "title": "Bid levels",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 46,
    "title": "Ask levels",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 47,
    "title": "Orderbook level price",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 48,
    "title": "Orderbook level quantity",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 49,
    "title": "Orderbook depth changes",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 50,
    "title": "Liquidity replenishment evidence",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 51,
    "title": "Liquidity disappearance",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 52,
    "title": "Cancellations/withdrawal evidence",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 53,
    "title": "Bid absorption evidence/proxy",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 54,
    "title": "Ask absorption evidence/proxy",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 55,
    "title": "Book imbalance",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 56,
    "title": "Book validity",
    "role": "INPUT_QUALITY"
  },
  {
    "id": 57,
    "title": "Book sequence/reset/invalidation",
    "role": "INPUT_QUALITY"
  },
  {
    "id": 58,
    "title": "Open interest",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 59,
    "title": "OI change",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 60,
    "title": "OI freshness",
    "role": "INPUT_QUALITY"
  },
  {
    "id": 61,
    "title": "Price/OI relationship",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 62,
    "title": "Funding rate",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 63,
    "title": "24h volume",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 64,
    "title": "24h turnover",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 65,
    "title": "Public liquidation events",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 66,
    "title": "Liquidation price",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 67,
    "title": "Liquidation size",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 68,
    "title": "Liquidation side",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 69,
    "title": "Liquidation notional",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 70,
    "title": "Long-liquidation aggregate",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 71,
    "title": "Short-liquidation aggregate",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 72,
    "title": "Liquidation event count",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 73,
    "title": "Liquidation clusters",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 74,
    "title": "Liquidation burst vs price",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 75,
    "title": "Liquidation burst vs flow",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 76,
    "title": "Liquidation burst vs OI",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 77,
    "title": "Raw receive timestamps",
    "role": "INPUT_QUALITY"
  },
  {
    "id": 78,
    "title": "Microstructure snapshot timestamps",
    "role": "INPUT_QUALITY"
  },
  {
    "id": 79,
    "title": "Intra-segment gap detection",
    "role": "INPUT_QUALITY"
  },
  {
    "id": 80,
    "title": "Cross-segment continuity",
    "role": "INPUT_QUALITY"
  },
  {
    "id": 81,
    "title": "Provenance/run/commit/source",
    "role": "METADATA_ONLY"
  },
  {
    "id": 82,
    "title": "Replayable primary data",
    "role": "METADATA_ONLY"
  },
  {
    "id": 83,
    "title": "Current structural state",
    "role": "TARGET_EVAL"
  },
  {
    "id": 84,
    "title": "Last confirmed structural Local High",
    "role": "TARGET_EVAL"
  },
  {
    "id": 85,
    "title": "Last confirmed structural Local Low",
    "role": "TARGET_EVAL"
  },
  {
    "id": 86,
    "title": "Active swing direction",
    "role": "TARGET_EVAL"
  },
  {
    "id": 87,
    "title": "Running structural extreme",
    "role": "TARGET_EVAL"
  },
  {
    "id": 88,
    "title": "Structural maturity",
    "role": "TARGET_EVAL"
  },
  {
    "id": 89,
    "title": "v6 WATCH state",
    "role": "TARGET_EVAL"
  },
  {
    "id": 90,
    "title": "v6 FORMING state",
    "role": "TARGET_EVAL"
  },
  {
    "id": 91,
    "title": "v6 EARLY_HIGH_CONFIDENCE state",
    "role": "TARGET_EVAL"
  },
  {
    "id": 92,
    "title": "v6 CONFIRMED state",
    "role": "TARGET_EVAL"
  },
  {
    "id": 93,
    "title": "v6 HARD_CONFIRMED state",
    "role": "TARGET_EVAL"
  },
  {
    "id": 94,
    "title": "Candidate timestamp",
    "role": "TARGET_EVAL"
  },
  {
    "id": 95,
    "title": "First EARLY_HIGH_CONFIDENCE timestamp",
    "role": "TARGET_EVAL"
  },
  {
    "id": 96,
    "title": "Confirmation timestamp",
    "role": "TARGET_EVAL"
  },
  {
    "id": 97,
    "title": "Signal delay from extreme",
    "role": "TARGET_EVAL"
  },
  {
    "id": 98,
    "title": "Signal price error",
    "role": "TARGET_EVAL"
  },
  {
    "id": 99,
    "title": "First accepted signal True/False",
    "role": "TARGET_EVAL"
  },
  {
    "id": 100,
    "title": "First-accepted precision",
    "role": "TARGET_EVAL"
  },
  {
    "id": 101,
    "title": "False-local rate",
    "role": "TARGET_EVAL"
  },
  {
    "id": 102,
    "title": "Coverage/recall",
    "role": "TARGET_EVAL"
  },
  {
    "id": 103,
    "title": "Median delay",
    "role": "TARGET_EVAL"
  },
  {
    "id": 104,
    "title": "P90 delay",
    "role": "TARGET_EVAL"
  },
  {
    "id": 105,
    "title": "Median price error",
    "role": "TARGET_EVAL"
  },
  {
    "id": 106,
    "title": "P90 price error",
    "role": "TARGET_EVAL"
  },
  {
    "id": 107,
    "title": "Strict H1 Local High/Low label set",
    "role": "TARGET_EVAL"
  },
  {
    "id": 108,
    "title": "Internal locals inside larger movement",
    "role": "TARGET_EVAL"
  },
  {
    "id": 109,
    "title": "Significant extrema timing label set",
    "role": "TARGET_EVAL"
  },
  {
    "id": 110,
    "title": "Time-aligned causal sequence Structure→Flow→Book→OI/Liq→Price response",
    "role": "TARGET_EVAL"
  },
  {
    "id": 111,
    "title": "Bybit server time + runner clock offset",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 112,
    "title": "Instrument metadata: tickSize/qtyStep/contract/risk/funding metadata",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 113,
    "title": "Public long/short holder ratio (5m)",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 114,
    "title": "Mark-index basis / basis bps",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 115,
    "title": "OI notional (OI × reference price)",
    "role": "INPUT_CAUSAL"
  },
  {
    "id": 116,
    "title": "Collector connection/restart/data-gap health markers",
    "role": "INPUT_QUALITY"
  }
]

INPUT_IDS = frozenset(p["id"] for p in POINTS if p["role"].startswith("INPUT_"))
TARGET_IDS = frozenset(p["id"] for p in POINTS if p["role"] == "TARGET_EVAL")
METADATA_IDS = frozenset(p["id"] for p in POINTS if p["role"] == "METADATA_ONLY")

assert len(POINTS) == 116
assert {p["id"] for p in POINTS} == set(range(1,117))
assert not (INPUT_IDS & TARGET_IDS)
assert INPUT_IDS | TARGET_IDS | METADATA_IDS == set(range(1,117))
assert (len(INPUT_IDS),len(TARGET_IDS),len(METADATA_IDS)) == (86,28,2)

def contract_summary():
    return {
        "version": "HYPE-QUANT-116-v1",
        "point_count": len(POINTS),
        "input_point_count":len(INPUT_IDS),
        "target_eval_point_count":len(TARGET_IDS),
        "metadata_point_count":len(METADATA_IDS),
        "input_ids": sorted(INPUT_IDS),
        "target_eval_ids": sorted(TARGET_IDS),
        "metadata_ids": sorted(METADATA_IDS),
        "future_leakage_guard": "TARGET_EVAL ids are forbidden from model inputs",
    }
