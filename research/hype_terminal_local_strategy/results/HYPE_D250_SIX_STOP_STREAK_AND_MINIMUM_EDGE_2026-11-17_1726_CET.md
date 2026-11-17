# HYPE D250 — six-stop-streak survivability and break-even threshold (2026-11-17 17:26 CET)

Research-only **new deterministic sensitivity analysis**, NOT a matched historical execution replay. No detector training or changed entry/exit thresholds.

## Sources read in this iteration
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: frozen D250; 71/71 historical first-accepted and 50/50 OOS; 67 finalized next opposite locals; median MFE giveback 61.2%; late-Aug exit failure.
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 67 sequential model trades, 22 fixed stops, 49.25% positive after cost, 6 maximum losing streak; 5x worst modeled -5.75% equity; 3x closed DD 18.56%; execution not validated.
- `hype_stop_risk_envelope_20261117.py`: deterministic risk sizing using stop + costs + scenario slippage and gap.

## Frozen and directional constraints
D250: rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; side-normalized flow15 < 0.4504731635235635. LOW -> LONG, HIGH -> SHORT only AFTER the causal signal; never use future exact opposite extreme. Keep the 1% adverse-price stop and causal opposite-local baseline unchanged. Previously rejected flow+MFE, K0/K1, and tight trail overlays remain rejected.

## New sensitivity calculations
For equity E, notional N, stop distance d=0.01, modeled round-trip fees f=0.0015, scenario slip s=0.001, gap reserve g=0.005:
- stress loss per notional u=d+f+s+g=0.0175;
- N/E <= risk_fraction/u;
- 0.25% risk: N/E <= 0.14285714, initial margin at 25x <= 0.00571429 E;
- 0.50% risk: N/E <= 0.28571429, initial margin at 25x <= 0.01142857 E.
These are conservative **scenario allocations**, not empirically calibrated gap percentiles. No exchange minimum-order validation.

For six consecutive full-budget stress-stop losses, assuming independent sequential resizing and no additional funding:
- risk 0.25% each: remaining equity = (1-0.0025)^6 = 98.50934% of start; loss 1.49066%;
- risk 0.50% each: remaining equity = (1-0.005)^6 = 97.03725%; loss 2.96275%.
Compare original 5x baseline worst modeled loss 5.75% **per trade**, and 6 identical worst-case modeled losses would leave (1-0.0575)^6 = 70.088% of equity (hypothetical, not the realized six-loss streak).

At 49.25% positive outcomes, an illustrative two-outcome break-even condition before any unmodeled costs is average win / average loss > (1-0.4925)/0.4925 = 1.03046. This does **not** establish a win/loss distribution for the conservative sizing case; published baseline average winner +14.16% and loser -4.37% at 5x are model outcomes, not exchange fills.

## New failure-mode decision
A smaller notional scales both wins and losses and does NOT independently improve per-notional expectancy or rescue a flawed exit. Six-stop survivability is improved mechanically, but **risk-adjusted positive net returns remain unproven**. Do not promote or claim zero liquidations from this sensitivity calculation.

## Required next replay / unresolved
Recover the actual 67 UTC trade rows (signal, entry, exit, side, stop, quantities, fees, opposite-local confirmation) and map to timestamped Bybit Public Trades, mark price, L50 and funding with explicit availability masks. Reject same-bar path ambiguity; report both best/worst bound when sequencing is unknown. Replay unchanged 5x baseline and conservative 0.25%/0.5% variants on identical events, with sequential equity, no reused capital, stop fills and liquidation-distance checks; then monthly net equity, closed and MTM DD, realized MFE giveback, forward sealed results. Current file does not assert those results.

No production changes, no live orders.
