# HYPE frozen 1% stop: gap-conditioned sizing frontier and non-guaranteed loss budget
Date: 2026-11-15 06:30 CET. Research only; no live orders, training, production edits, or threshold changes.

## Source verification
Read existing frozen files `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` and `HYPE_FROZEN_BLOCK_RETURN_DECOMPOSITION_2026-11-15_0530_CET.md` directly in the requested branch. Frozen D250: rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, side-normalized flow15 < 0.4504731635235635. D250 first acceptance, LOW->LONG / HIGH->SHORT. Preserve 1% adverse-price cut and opposite K2 exit, no tight trailing. 67 completed, 4 censored; do not equate 71 correct historical local labels with 71 profitable fills.

## New deterministic calculation: notional frontier for a $100 account
Loss fraction of notional = 1% planned adverse cut + 0.15% *assumed* complete roundtrip costs + additional adverse stop-fill gap. For stop-risk budgets $0.25 and $0.50: max notional = risk budget / loss fraction. This is a sensitivity calculation, not an observed Bybit execution replay. The assumed 0.15% is a cost simplification, not a verified fee/funding/slippage ledger. Funding is excluded; a nonzero funding reserve requires smaller notional.

| Additional adverse gap after stop | Total modeled loss per notional | Max notional for 0.25% equity risk | Max notional for 0.50% equity risk | Modeled equity loss at unchanged 5x exposure |
|---|---:|---:|---:|---:|
| 0.00% | 1.15% | $21.74 | $43.48 | 5.75% |
| 0.50% | 1.65% | $15.15 | $30.30 | 8.25% |
| 1.00% | 2.15% | $11.63 | $23.26 | 10.75% |
| 2.00% | 3.15% | $7.94 | $15.87 | 15.75% |

At 25x instrument leverage, the $23.26 nominal at 1% gap requires about $0.93 initial margin (excluding exchange margin adjustments), but leverage does not reduce dollar stop loss. For the same 1% gap, the original $500 nominal / $100 equity historical baseline incurs an estimated $10.75 equity loss on one stop (10.75%) before funding, compared with $0.50 for a $23.26 notional. This is a **21.5x difference in per-stop dollar risk**, not evidence of better returns. If multiple positions share the account, the sum of their worst modeled stop losses must be <= $1.00 (1% equity) and reserved capital cannot be reused simultaneously.

## New interpretation / execution gate
The 1% adverse cut is a stop **trigger**, not a guaranteed exit price. These budget numbers are conditional on the assumed gap; gaps can exceed 2%, and stop-market orders can fill worse. Stop-limit orders may not fill at all. For LONG, measure sell-side book depth and downside gap; for SHORT, measure buy-side depth and upside gap separately. Before any promotion, measure trigger basis (last/mark/index), actual order acknowledgement, best bid/ask, L50 staleness, event-time/receipt-time latency, funding accrual, maintenance margin and liquidation distance. With no such records, liquidation count, exact loss cap and mark-to-market DD are **unknown**.

## Reproduction (standard Python)
```python
equity=100
for gap in [0,0.005,0.01,0.02]:
    loss_fraction=0.01+0.0015+gap
    n025=equity*0.0025/loss_fraction
    n05=equity*0.005/loss_fraction
    baseline_loss_pct=100*5*loss_fraction
    print(gap, round(n025,2), round(n05,2), round(baseline_loss_pct,2))
```

## Research status and falsification
This iteration performs a new frozen-rule risk-budget stress calculation; it does NOT claim matched Public Trades/L50 execution replay or net forward performance. No original 71 timestamped signal/67 trade ledger plus event-synchronized order-book/prints were recovered in this calculation. A valid next step is to find and align the original timestamped rows with available historical rich artifacts, reject unmatched intervals, and compare unchanged baseline against budget sizing and candidate profit-locks on identical sequential capital and costs. Previously rejected flow/MFE, K0/K1 and fixed ATR trailing overlays remain rejected pending independent evidence. The August validation closed-equity block was -22.76%; correct local classification did not prevent drawdown.
