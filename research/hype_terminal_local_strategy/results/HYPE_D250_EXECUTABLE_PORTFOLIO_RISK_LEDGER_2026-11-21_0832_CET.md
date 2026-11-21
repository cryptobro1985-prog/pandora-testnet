# D250 post-local portfolio gate: executable reservation checkpoint — 2026-11-21 08:32 CET

Research only. Existing branch; no detector training, production edits, or orders.

## New concrete change
Added `research/hype_terminal_local_strategy/portfolio_risk_ledger_20261121.py`, a standalone, fail-closed paper-risk reservation ledger. Unlike the existing per-trade `stop_geometry_risk_gate_20261121.py`, it reserves risk at order acceptance, rejects duplicate IDs and budget breaches, retains pending/open exposure, and releases only after a confirmed terminal fill/cancel. It also recomputes available capacity from conservative MTM equity without silently resizing existing positions.

## Deterministic executable scenario
Start equity $100, max portfolio risk 1% = $1.00. Reserve $0.50 for LOW→LONG and $0.50 for HIGH→SHORT; a third $0.50 order must be rejected. If MTM equity falls to $90, portfolio risk capacity contracts to $0.90, while existing $1.00 reservations remain; any new order is blocked. Only after confirmed exit of one $0.50 reservation does a new $0.01 order become eligible. The module includes Python assertions for this exact scenario. The assertions are provided but GitHub Actions execution has not been verified.

## Limits
This is a risk-ledger implementation, not an execution replay or proof of a profitable edge. The 1% risk limit is a *modeled reservation budget*, not a guaranteed realized-loss bound under gaps/liquidations. It is not wired to the strategy or exchange and deliberately does not authorize live trades. No 67-trade quote/mark/L50 replay, monthly equity, MTM DD, realized stop fills, funding, liquidation count or MFE protection improvement is claimed. The original D250 thresholds and rejected profit overlays remain frozen.

## Next data gate
Recover exact UTC event IDs and quote/mark/trade coverage for all 67 historical positions; record missing data as UNRESOLVED. Apply the ledger in chronological matched-sample replay with fee/funding/slippage parity, independent forward windows, and distinct LONG/SHORT stop and control-transfer exits. Do not substitute synthetic price paths for real Bybit fills.
