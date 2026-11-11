# HYPE Risk / MFE Decision — 2026-11-11

Research mode **only**. No live trading authorization; no exchange order path.

## Verified runs
- Unified Quantum+JEPA+Cortex v2 workflow run **42970809302**: SUCCESSFUL TRAINING, but **OOS_GATE_REJECT**.
- Paper OHLC execution and leverage stress workflow run **42973182059**: SUCCESSFUL AUDIT.
- Equity exposure sizing and paper state-machine unit tests workflow run **42973370716**: SUCCESS.
- Master archive SHA256: `c9d588b5c78d0e72a3073ceb62c7fa100381ebf69df911b22a170171a2653975`.

## Unified local model was NOT accepted

Previously inspected Oct27-Nov03 OOS:
- 253 candidate structures, 19 true locals
- accepted 7, TP 2, FP 5, FN 17
- precision **28.57%**, recall **10.53%**, F1 **15.38%**, median lag 300s
- 55 calibration candidates with only **4 positives**: insufficient support (required >=5)
- every tri-brain ablation marked `INSUFFICIENT_CALIBRATION_SUPPORT`

This does not demonstrate reliable early local detection. Local confidence is a
separate diagnostic context, not permission to trade.

## Frozen causal price/flow paper benchmark

Model fitted on Jul12-Aug07 with development-selected score threshold 0.80.
Signals are observed at a COMPLETED minute and executed at the NEXT minute
OPEN, one position at a time, 30m opening cooldown.

Model assumptions:
- 12bp estimated roundtrip cost per notional
- 35bp adverse underlying hard stop
- fixed policy: 50bp take-profit
- alternative trend policy: do not exit for a minor MFE recoil alone;
  only HOLD/CLOSE on sustained opposing flow + price response and a substantive
  giveback; max hold 120min
- adverse stop wins when both favorable/adverse touched in same OHLC candle
- no historical bid/ask executable quotes, mark-to-liquidation replay or latency
  data in this paper benchmark: these are NOT verified exchange fills.

| Period | Fixed: trades / underlying return | Trend hold: trades / underlying return |
|---|---:|---:|
| Development Aug08–Sep01 | 14 / **-1.482%** | 11 / **+7.949%** |
| Validation Sep01–Oct01 | 2 / **+0.761%** | 2 / **+0.296%** |
| Historical Oct04–Nov03 | 15 / **-1.108%** | 13 / **+0.960%** |

Trend hold in October had **2 wins and 11 losses**. Its two winners
were +4.117% and +2.125% underlying; excluding its largest win changes the
underlying compounded result to about **-3.032%**. This is fragile, not a
validated statistical edge.

October median MFE/MAE for the trend policy: **31.14bp / 53.26bp**.
Median gross-return/MFE capture is negative (-1.124) because most trades lost
despite some favorable excursion. Thus the current MFE exit **is not solved**.

## Stress at user-specified 25x / 20% equity margin

Notional exposure = leverage * fraction of equity used as margin:
`25 * 0.20 = 5.0x total-equity exposure`.

The following is hypothetical compounded portfolio outcome over only the
already-inspected October historical sample:

| Model | Baseline cost | Baseline + 8bp extra cost | Baseline + 25bp extra cost |
|---|---:|---:|---:|
| Fixed TP / stop | -5.681% | -11.207% | -21.961% |
| HOLD / flow exit | +2.697% | -2.516% | -12.793% |

For trend HOLD, baseline drawdown ~11.211% equity; additional 25bp extra cost
stress increases drawdown to ~21.364%. Simulated approximate liquidations = 0,
which **does not** mean liquidation risk is zero. The model lacks historical
tick-level executable quotes and exact exchange mark/liquidation mechanics.

**VERDICT: 25x at 20% margin is rejected for real deployment and does not
pass the bounded equity risk sizing policy.**

## Bounded loss budget for paper-only sizing

This is a conservative, explicitly hypothetical risk gate, NOT an empirically
optimal leverage. Let:
- adverse underlying stop = 35bps;
- roundtrip cost = 12bps;
- extra slippage = 8bps;
- additional severe gap shock = 100bps;
- combined stress = **155bps = 1.55% underlying**;
- target total-equity loss budget **0.5% per trade**;
- approximate liquidation boundary = `1 / leverage - 0.5%` underlying,
  requiring >=4x shock-distance cushion.

Then stressed equity loss fraction is:
`equity_margin_fraction × leverage × 0.0155`.

| Paper scenario | Equity notional exposure | 0.5%-budget shocked loss | Approx liquidation distance | Gate |
|---|---:|---:|---:|---|
| 3x / 10% margin | 0.30x | 0.465% equity | ~32.83% adverse underlying | PASS as bounded scenario |
| 5x / 5% margin | 0.25x | 0.3875% equity | ~19.50% | PASS as bounded scenario |
| 10x / 3% margin | 0.30x | 0.465% equity | ~9.50% | PASS as bounded scenario |
| 25x / 2% margin | 0.50x | 0.775% equity | ~3.50% | REJECT |
| 25x / 20% margin | 5.00x | 7.750% equity | ~3.50% | REJECT |

These gates offer only limited scenario risk control. Unbounded price jumps,
venue outages, stale data, liquidity collapses and failed protective orders
can violate the assumed loss budget. No finite leverage can guarantee zero
liquidations under arbitrary adverse moves.

## Recommendation

**REAL MONEY: 0% equity margin, no leveraged orders**, until the strategy
has passed a genuinely new untouched forward sample with executable data and
adequate trade count; the current OOS and tiny validation do not justify Kelly
or 'optimal leverage' estimation.

For **paper-only** conservative stress research, compare **3x/10%** and
**5x/5%** margin first. This is a provisional scenario range, NOT a trading
recommendation or verified optimal risk level.

Next: train and validate stronger local-free LONG/SHORT entry and MFE exit
heads on compatible full-micro; use regime/price response and L50/OI/liqs only
where observed and timestamped causally. Require costs, capacity, drawdown and
fresh forward approval before any risk regime promotion.

Source files:
- `research/hype_local_only/results/HYPE_UNIFIED_LOCAL_INTELLIGENCE_V2_LATEST.json`
- `research/hype_unified_intelligence/PAPER_RISK_STRESS_LATEST.json`
- `research/hype_unified_intelligence/paper_risk_replay_v1.py`
- `research/hype_unified_intelligence/exposure_sizing.py`
- `research/hype_unified_intelligence/EXPERIMENT_LEDGER.jsonl`
