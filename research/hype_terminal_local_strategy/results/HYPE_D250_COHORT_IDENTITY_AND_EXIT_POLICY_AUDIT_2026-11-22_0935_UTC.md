# HYPE D250 cohort identity and exit-policy comparability audit — 2026-11-22 09:35 UTC

Research-only; no retraining, no production change, no orders. This checkpoint audits source-reported trade cohorts and tests whether their outcomes can be validly combined. Not an event-level Bybit execution replay.

## Verified source files
- `research/hype_terminal_local_strategy/results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`
- `research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`
- `research/hype_terminal_local_strategy/results/HYPE_D250_CENSORING_AND_PORTFOLIO_REPLAY_GATE_2026-11-22_0830_UTC.md`

## New cohort-integrity finding
There are **different entry-authority cohorts**, not one interchangeable set:
- D250 minimal rule: 71 accepted among 317 scored episodes; 67 with finalized opposite locals, four censored; 250-minute checkpoint, 22.4% coverage.
- Unified frozen high-confidence cascade: 118 first confirmations among 253 strong episodes, 46.64% coverage; distinct branches and episode definition.
- Broader 256/256 fitted coverage cascade: explicitly meta-selected on preserved sample and SHADOW-only, not an independently validated entry authority.

**Do not union the 71, 118 and 256 or import the 118-cascade's early entry geometry into the D250 67-trade PnL.** They have different denominators, confirmation latencies, target definitions, and selection histories. A row-level join needs `episode_id`, `anchor_utc`, `side`, `rule_id`, `first_eligible_utc`, and provenance of available fields. Otherwise any claimed same-sample early-vs-late entry or MFE improvement is invalid.

## New outcome-policy arithmetic
From the frozen 67-trade asymmetric-risk report:
- 22/67 = **32.8358%** of completed simulated trades were cut by the 1% adverse-price rule.
- 49.25% positive of 67 corresponds to approximately 33 positive, 34 nonpositive; 33/67 = 49.2537%.
- 5x mean winner +14.16% equity and mean loser -4.37% equity imply approximate **+4.756% arithmetic mean equity return per closed trade**: `(33*14.16-34*4.37)/67`. This is **not** compounded return, not a per-month return, and cannot be mapped to the 3x portfolio without per-trade data.
- 67 opposite-local finalized trades and 71 accepted signals imply 4 censored events. No inference about their MTM exposure or equity can be made from completed-only aggregates.
- The 5x result $100->$1308.86 and 3x $100->$531.16 are modeled closed-equity sequences under a fixed assumed 0.15% round-trip cost, not exchange fill or mark-to-market validation.

## Causal execution-replay gate
1. Reconstruct the **exact D250 71-row manifest** before comparing exit variants; preserve 67 finalized and four censored entries, not a different 118-row cascade.
2. For each event, require anchor/confirmation/first executable UTC, direction, entry/stop trigger basis (last vs mark), actual fee tier, funding intervals, orderbook depth or explicit missingness, price tape and per-minute coverage. LOW->LONG and HIGH->SHORT have separate geometry and fill assumptions.
3. Enforce stop-risk <=0.25%-0.5% equity/trade, aggregate <=1%; reserve capital for open and censored positions. Apply conservative gap/slippage and liquidation buffer. Reject if missing data makes execution unverifiable.
4. Replay unchanged baseline and variants on identical eligible trades and timestamps: risk sizing, staged entry, mandatory cut, no-trail opposite-local hold; preserve rejected overlays as rejected unless a **new untouched** test proves benefit.
5. Record open-equity MTM by UTC, monthly net equity, max intraday/MTM and closed DD, fills, stop trigger/fill deviations, forced liquidation checks, MFE capture/giveback, and chronological forward.
6. Never use oracle opposite extreme as an executable exit or silently fill missing L50/OI/liquidation features.

## Reproduce arithmetic
```python
n=67; winners=33; stops=22
print(round(100*stops/n,4), round(100*winners/n,4))
print(round((winners*14.16+(n-winners)*(-4.37))/n,4))
# 32.8358 49.2537 4.756...
```

## Evidence status
New work is a source-backed **cohort/provenance and outcome-accounting audit**. No individual UTC 67-trade ledger or matched rich Bybit execution tape was retrieved in this run. Thus no new validated monthly net PnL, fills, MTM DD, liquidations or forward MFE capture. Frozen D250 and earlier rejected overlays remain unchanged.
