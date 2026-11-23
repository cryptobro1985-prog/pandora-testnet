# HYPE D250 side-exact sizing implementation — 2026-11-23 09:26 CET

Scope: research only, existing branch, no orders, no detector retraining, no changed D250 thresholds.

## Concrete change
Added `d250_side_exact_stop_risk_v2.py` as a separate research module, preserving the prior approximate `d250_cost_aware_risk_gate.py` as unchanged baseline. The new module computes side-specific adverse fill prices, quantity, entry/exit fees, and risk-based notional. It fails closed for invalid direction, nonfinite costs, and unavailable margin. It does **not** claim liquidation safety: mark-price liquidation, tier maintenance margin, funding and liquidation fees must be validated separately.

## Deterministic scenario
Equity $100, budget 0.5%, entry reference 100, LONG stop 99 / SHORT stop 101, entry slip 0.03%, stop slip 0.05%, adverse gap 1%, fees 0.06% each side, leverage 5x.

Direction-exact modeled loss / entry notional:
- LONG: 2.187638%; notional $22.855701
- SHORT: 2.212382%; notional $22.600075

Both nominal modeled stop losses are $0.50 by construction, conditional on stated scenario. They are not guaranteed loss bounds. The SHORT notional must be smaller than LONG under these inputs.

## Test / reproducibility
Run `python research/hype_terminal_local_strategy/d250_side_exact_stop_risk_v2.py`. Six deterministic assertions are included; execution in the GitHub runner is not yet verified. Independently recalculated the example arithmetic in a local Python interpreter. No matched historical replay was run.

## Outstanding blockers
Recover the exact 71 D250 event timestamps, their K2 availability timestamps, and the matched Bybit M1 trades/mark/L50/funding data. Then compare unchanged original baseline against exact-size mandatory-stop and staged-entry variants on the same chronology with common costs and shared capital. Do not promote rejected profit-lock overlays without independent unseen evidence. Monthly net equity, MTM/closed DD, stop fills, liquidations and MFE capture remain unknown.

Frozen rule: rev_atr>2.0840049433824706; trade_ratio5>0.2727842248141979; flow15<0.4504731635235635. LOW→LONG, HIGH→SHORT.
