# HYPE D250: stop-gap sensitivity and staged-entry capital reservation — 2026-11-18 10:33 CET

Research only. Deterministic **new scenario calculations**, not Bybit fill replay. Based on frozen reports H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md and HYPE_D250_DUAL_STOP_RISK_STREAK_ENVELOPE_2026-11-18_0929_CET.md on this branch. Do not alter D250, original 67-trade baseline, or previously rejected MFE overlays.

## Question
How sensitive is conservative position sizing to an adverse gap at the 1% frozen price stop? How should a staged entry reserve capital without implicitly doubling stop risk?

## Formula and assumptions
E = equity; budget B = 0.005 E (also evaluate B=0.0025 E). Entry-to-stop price fraction d=0.01, assumed round-trip fee fraction f=0.0015, adverse gap fraction g. Worst-case **scenario**, not a guaranteed bound: N/E = (B/E)/(d+f+g). At instrument leverage 25x, initial margin/E = (N/E)/25. Same model for LOW/LONG and HIGH/SHORT; side-specific market impact and liquidation cannot be inferred from aggregate reports.

## New gap sensitivity at 0.50% equity budget
| Adverse gap after trigger | Loss per notional | Max notional/equity | Initial margin/equity at 25x | Loss/equity at historical 5x account exposure |
|---|---:|---:|---:|---:|
| 0.00% | 1.150% | 0.4348x | 1.739% | 5.75% |
| 0.25% | 1.400% | 0.3571x | 1.429% | 7.00% |
| 0.50% | 1.650% | 0.3030x | 1.212% | 8.25% |
| 1.00% | 2.150% | 0.2326x | 0.930% | 10.75% |
| 2.00% | 3.150% | 0.1587x | 0.635% | 15.75% |

At 0.25% risk, allowable notional and margin are exactly half the 0.50% columns. This grid reveals the fragility of using a nominal 1% stop as a risk guarantee: the assumed 0.5% gap gives 0.3030x notional, while a 2% gap cuts the allowable notional to 0.1587x (47.6% smaller). These are **separate** scenario sizes; a position sized for 0.5% gap would exceed its 0.5% risk budget if the actual gap is 2%.

## New staged-entry invariant (not a claim of better returns)
For two legs of a single trade, allocate the SAME total budget B across legs, not B per leg. For leg i, N_i = B_i/(d_i+f_i+g_i), with B_1+B_2 <= B, and before each fill recheck aggregate portfolio stop risk <=1% of equity, available free collateral, and worst-case cross-position gap. Do not reuse reserved risk until an exit is actually filled.

| Risk budget split leg1/leg2 | Leg1 budget of equity | Leg2 budget of equity | Total |
|---|---:|---:|---:|
| 50/50 | 0.250% | 0.250% | 0.500% |
| 25/75 | 0.125% | 0.375% | 0.500% |
| 100/0 | 0.500% | 0.000% | 0.500% |

A second leg must NOT be filled merely because price has moved favorably. It requires a new causal decision and a fresh mark/last/bid-ask stop-distance check; if the second leg is unfilled, report it as unfilled rather than a hypothetical fill. Recompute first-leg risk after any stop move. A nominal break-even stop still loses fees and potentially gap/slippage; treat it as a new execution policy, not a guaranteed flat result.

## Causality / execution implications
- LOW->LONG: entry at executable ask, stop sells into bids; HIGH->SHORT: entry at executable bid, stop buys from asks. The asymmetry is execution-side and requires actual spread/depth at each timestamp.
- A trigger at last-traded price is not equivalent to stop fill at mark or index. Without trigger basis, matching book/trades, funding, tiered maintenance margin and fee tier, **liquidation distance and count remain unverified**.
- D250's 250-minute waiting period requires rejecting new same-side extremes and opposite-local confirmations BEFORE entry; no hindsight exit at the future exact opposite extreme.
- Same-sample net comparison of baseline, staged, break-even and profit-lock requires UTC individual entries/exits, trade-level book or trades, funding, fees, no overlapping capital and monthly mark-to-market path. No such replay is asserted here.

## Result / decision
This iteration adds a reproducible five-scenario gap grid and staged-entry risk-budget invariants. It does NOT show improved net returns or MFE protection. Preserve baseline (1% adverse cut, no tight trail, causal opposite-local exit) as unchanged comparator; previously rejected overlays remain rejected. No model retraining, production changes or orders.

## Reproduction
For g in [0,0.0025,0.005,0.01,0.02], compute loss=0.01+0.0015+g; notional_multiple=0.005/loss; margin_fraction=notional_multiple/25; old_5x_loss_fraction=5*loss. For staged split a in [0.25,0.5,1], first_budget=0.005*a, second_budget=0.005*(1-a). Values are algebraic and deterministic.
