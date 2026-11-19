# D250 stop-gap compounding: LONG/SHORT asymmetry — 2026-11-19 05:34 CET

Research-only analytical checkpoint. Frozen D250 and the 1% adverse-price cut unchanged. No orders, production edits, retraining, or claim of empirical fills.

## Inputs and source verification
Read the existing H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, and HYPE_D250_FILL_ANCHOR_RISK_CONVENTION_AUDIT_2026-11-19_0427_CET.md on the named research branch. Previous fill-anchored stress approximated 1% stop + 3% stop gap + 0.15% fees + 0.09% funding = 4.24% for both sides.

## New calculation: stop gap measured relative to STOP quote
Let P be actual filled entry VWAP, stop distance d=0.01, adverse gap g=0.03 relative to stop quote, fees f=0.0015 and funding stress u=0.0009 as fractions of initial filled notional (scenario assumptions, NOT measured Bybit values).

LONG: stop S_L=P(1-d); adverse execution X_L=S_L(1-g)=0.9603P. Gross price loss (P-X_L)/P=d+g-dg=0.0397. Stress loss fraction =0.0397+f+u=0.0421 (4.21%).

SHORT: stop S_H=P(1+d); adverse cover X_H=S_H(1+g)=1.0403P. Gross price loss (X_H-P)/P=d+g+dg=0.0403. Stress loss fraction =0.0403+f+u=0.0427 (4.27%).

At $100 equity:
- 0.25% equity risk ($0.25): LONG maximum filled notional $5.93824228; SHORT $5.85480094.
- 0.50% equity risk ($0.50): LONG $11.87648456; SHORT $11.70960187.
- Earlier 4.24% linear stress: $5.89622642 / $11.79245283. This is a symmetric approximation, not the exact side-specific stop-relative-gap calculation.

For an order pre-fill, reserve separate reference-to-fill uncertainty only once; after execution anchor realized PnL to actual fill. If gap is defined as percentage points of ENTRY instead of relative to STOP, the linear 4.24% formula is correct under that different definition. Never silently switch gap definitions. Fees calculated on executed exit notional, and funding on the exchange's applicable notional/times, may differ from this simplified entry-notional stress; matched replay must use exact amounts.

## Replay invariant and risk policy
- Keep same original 67 candidate trade timestamps and unchanged baseline; match M1/Public Trades/L50/mark/OI/liquidations with UTC and validate completeness.
- For LONG use actual ask-side entry and bid-side stop fill; SHORT use bid-side entry and ask-side cover. Round stop/tick and quantity to exchange rules; validate minimum order, margin and mark-price liquidation gap. Missing data -> UNKNOWN, never zero.
- Size at most 0.25%-0.5% equity stop-risk per trade, max concurrent 1% under stress; use the worse SHORT-side scenario as a conservative shared pre-fill ceiling if direction-specific quote and gap model are unavailable.
- A stop-market is not a guaranteed fill price. Stress beyond 3% remains possible, so no absolute loss cap or zero-liquidation claim.
- Causal exit requires confirmed opposite local availability, not the future extreme. Previously rejected profit overlays remain rejected.
- Theoretical arithmetic does not establish new net equity, fills, mark-to-market drawdown, forward results or MFE protection.

## Reproduction
```python
d,g,f,u=0.01,0.03,0.0015,0.0009
for side,loss in [('LONG',d+g-d*g+f+u),('SHORT',d+g+d*g+f+u)]:
    print(side,round(loss*100,4),round(.25/loss,8),round(.50/loss,8))
```

## Next evidence gate
Obtain the per-trade UTC entry/exit/stop/confirmation ledger and contemporaneous bid/ask/mark tape. Execute exact side-specific fill replay with common sample and fees, then report monthly net equity, MTM/closed DD, fill and stop failures, liquidations, MFE captured/given back and independent forward. This checkpoint does not claim that replay is completed.
