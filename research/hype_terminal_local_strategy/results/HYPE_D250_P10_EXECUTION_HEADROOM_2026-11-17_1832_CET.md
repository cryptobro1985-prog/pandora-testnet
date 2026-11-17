# D250 low-tail execution headroom audit — 2026-11-17 18:32 CET
Research only; no orders, no detector retraining, no production changes.

## Provenance
Read frozen H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md and HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md from this branch. Frozen thresholds unchanged. This is an aggregate **feasibility bound**, NOT a per-trade replay or forward result.

## Newly quantified execution issue
The 67 fully finalized entries have **p10 gross move from entry to the future exact opposite-local extreme = 0.519%**, an **oracle-only**, untradeable exit ceiling. Thus for a bottom-decile opportunity, **even an impossible perfect exit** has very little friction headroom. At 0.15% round-trip assumed fees, the theoretical residual is 0.369% of notional, before execution slip, delayed entry, funding and exit giveback.

With symmetric total entry+exit adverse slippage S (expressed as a percent of notional price) and additional adverse delayed-entry price D, the optimistic upper-bound residual at p10 is:
  oracle_net_p10_upper_bound = 0.519% - 0.150% - S - D - funding - unprotected_exit_giveback.
This equation is a **quantile illustration**, not a claim that the same trades are at p10 after delayed entry. Any of the omitted terms may eliminate the apparent edge.

| total slippage S | maximum combined D + funding + exit giveback for positive oracle net at p10 |
|---:|---:|
| 0.00% | 0.369% |
| 0.10% | 0.269% |
| 0.25% | 0.119% |
| 0.50% | negative (-0.131%); cannot break even even at D=0 |

The 61.2% median MFE giveback on causal opposite-local exits is measured on a different statistic and **must not** be applied to p10 gross as though paired trade-by-trade. No synthetic 'improved' PnL is claimed.

## Decision for replay
1. Separate LOW->LONG and HIGH->SHORT; link UTC candidate, D250 confirmation, first executable post-signal bid/ask, fill, stop trigger and actual exit.
2. Report oracle gross and causal realized outcomes as distinct columns. Flag trades where oracle gross <= roundtrip fees+measured slip+funding; such trades cannot profit under the tested execution assumptions.
3. Capture price displacement between signal and first executable fill (adverse and favorable), mark-to-market path, 1% stop and any gaps. Apply actual venue constraints and no capital overlap.
4. Keep all 67 finalized outcomes and four remaining D250 accepted entries separately labelled; do not silently drop censored entries or infer their result.
5. Compare original 5x account exposure baseline unchanged to 0.25%/0.5% equity stop-risk sizing using exactly the same eligible trades. No promotion of rejected MFE overlays without independent forward evidence.

## Data status
No individual matched 67-trade execution tape is verified in this checkpoint. No new monthly net equity, MTM DD, fill, liquidation or protected MFE statistic is asserted. This audit identifies an important lower-tail execution fragility and a precise acceptance test for the upcoming matched-event replay.
