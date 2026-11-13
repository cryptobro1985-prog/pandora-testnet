# HYPE post-local stop-distance / risk-budget compatibility audit — 2026-11-13 run 6

Research-only deterministic calculation from frozen historical reports. **Not a tick replay, not measured fills, not a new profitability result.** No retraining, no production changes, no orders.

## Provenance / frozen evidence
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: frozen D250 rule, 71/71 accepted true (50/50 OOS) on historical test, 22.4% coverage, 67 finalized trades; structural stop 0.25 ATR beyond original local, **median entry-to-stop distance 3.140%** (not a fixed stop on every trade). Causal opposite-local exit median MFE giveback 61.2%; late-Aug net weakness.
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: separate 67-trade experiment with 1% adverse cut, no tight trail, ~0.15% round-trip fees, 3x/5x account exposure. Do not equate its trades/fills with D250 sample without timestamp matching.
- `results/HYPE_SIDE_EXACT_FEE_GAP_CHECKPOINT_2026-11-13.md`: illustrative side-exact fee and gap arithmetic.
- `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`: causal LOW->LONG, HIGH->SHORT; control-transfer principle. Previously rejected MFE overlays remain rejected.

## New analysis: risk caps depend on *actual stop distance*, not merely a 1% trigger
For entry notional N, adverse price stop distance d, additional adverse execution gap g, entry and exit taker fee f=0.00075 each, assuming linear USDT contract and no funding:
- LONG loss / N = d+g+f*(2-d-g)
- SHORT loss / N = d+g+f*(2+d+g)
- risk-limited notional/equity = risk_budget / max(side loss/N)
- initial margin/equity at 25x = (notional/equity)/25.

Illustrative table (caps use worst-side SHORT; 3.14% is the **historical median structural distance**, not a universal stop):

| Stop distance | Extra adverse gap | LONG loss/notional | SHORT loss/notional | Cap for 0.25% equity risk | Cap for 0.50% equity risk |
|---:|---:|---:|---:|---:|---:|
| 1.00% | 0.00% | 1.1493% | 1.1507% | 0.2172x | 0.4345x |
| 1.00% | 0.50% | 1.6489% | 1.6511% | 0.1514x | 0.3028x |
| 1.00% | 1.00% | 2.1485% | 2.1515% | 0.1162x | 0.2324x |
| 3.14% | 0.00% | 3.2876% | 3.2924% | 0.0759x | 0.1519x |
| 3.14% | 0.50% | 3.7873% | 3.7927% | 0.0659x | 0.1318x |
| 3.14% | 1.00% | 4.2869% | 4.2931% | 0.0582x | 0.1165x |

**Finding:** for the same 0.5%-equity stress budget and hypothetical 1%-of-entry-price gap, using a 3.14% structural stop requires reducing account exposure from 0.2324x to 0.1165x (~49.9% less). Thus a risk budget without a per-entry stop geometry is not executable.

## Important 25x liquidation feasibility gate
At 25x instrument leverage, initial margin is ~4% of entry notional before fees and maintenance. A 3.14% structural stop **plus 1% gap = 4.14% adverse move**: it can cross the initial-margin distance, and liquidation may occur earlier depending on mark price, maintenance margin, margin mode, risk tier, collateral and funding. **Smaller position size alone does not make a 25x isolated position's liquidation price farther away in percentage terms.** The 3.14% structural-stop rows therefore do NOT authorize 25x isolated trades; they are mathematical loss-budget scenarios only. Use measured liquidation-price buffer or lower instrument leverage/collateral settings and require stop-before-liquidation with an explicit mark-price stress buffer. If liquidation data missing, mark **NOT EXECUTABLE / SHADOW ONLY**.

## Implementation contract for subsequent matched replay
1. Freeze existing H1 local confirmation timestamps and rule thresholds. Reject lookahead and snapshot-only signals.
2. For each candidate, store anchor extreme timestamp, confirmation timestamp, first executable tick, side, entry, structural stop, 1% adverse stop, selected active stop, spread, funding, mark/index and actual liquidation-price estimate.
3. Separate LONG and SHORT, and separately score same-side adverse movement *before* confirmation (not tradable MAE) versus MAE after entry.
4. Enforce no capital overlap; at any event time, sum remaining worst-case stop risks <=1% of equity. Partial staged entries must reserve their combined risk before placing any leg.
5. Replay frozen baseline 3x/5x, 0.25% and 0.5% risk sizing, and staged fills on identical timestamp-matched trades. Model stop trigger, gaps, slippage and depth; never assume stop fill at trigger.
6. Evaluate opposite-side **sustained price-impact efficiency/control transfer** only on prior timestamps. No raw counter-volume trigger, future opposite extreme or retroactive threshold selection. Keep previously rejected overlays rejected until independent forward evidence.
7. Output per-month net equity, MTM and closed DD, fills, stop and liquidation events, MFE capture/giveback, fees/funding, and truly unseen forward partition. Missing tick/mark/depth => NA, not zero.

## Reproducibility
Pure deterministic arithmetic; use d in {0.01,0.0314}, g in {0,0.005,0.01}, f=0.00075, r in {0.0025,0.005}; formulas above. Values rounded to four decimal places. 3.14% is a cross-sample median and **must not be substituted for individual trade stop distances**.

## Status
No matched historical Public Trades/L50/mark-price replay performed in this checkpoint; no new net PnL, fills, MTM drawdown, MFE or liquidation counts claimed. No strategy promotion.
