# D250 historical equity ordering / drawdown audit — 2026-11-22 10:33 UTC

Research only. Frozen entry and exit unchanged. No orders or retraining.

## New audit: nonchronological equity checkpoints
Source: `research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`.
The report lists **sealed May first**, followed by Jul12–Aug07, Aug08–Sep01, Sep01–Oct01 and Oct04–Nov03. Calendar order is May -> July -> August -> September -> October, but May is a *pre-development* holdout. The listed 5x intermediate balances are 471.51, 755.20, 583.32, 1037.06, 1308.86 starting from 100. Thus the published intermediate balance path is NOT a chronological market equity curve unless source trade rows prove otherwise.

### Reproducible calculation from report balances
The five consecutive displayed segment factors are:
- May 471.51/100 = 4.7151
- Jul12–Aug07 755.20/471.51 = 1.6016627
- Aug08–Sep01 583.32/755.20 = 0.772405
- Sep01–Oct01 1037.06/583.32 = 1.777851
- Oct04–Nov03 1308.86/1037.06 = 1.262086

The displayed late-Aug segment is a -22.7595% segment-level change, NOT a validated monthly net PnL. Its entry/exit overlap and boundary equity MTM are unknown. Reported 29.36% max *closed* DD cannot be independently reproduced from these five checkpoints. Reordering coarse segment factors leaves their product unchanged mathematically, but changes intermediate balances and may change pathwise drawdown and eligibility if capital is reserved. Never interpret the displayed path as calendar equity, nor label May as forward OOS after July.

## Additional accounting caution
Source reports 5x $100->$1308.86 versus 3x $100->$531.16, and 22/67 modeled stop cuts. The 1% adverse cut plus 0.15% round-trip cost implies a **-5.75% equity** stopped trade at 5x in a zero-gap model, exactly matching the reported worst trade. This arithmetic leaves **no evidence of modeled gap/slippage beyond the cut**. A 2 percentage-point adverse gap would yield -15.75% equity at 5x before additional costs/funding, *illustrative only*, not a reconstructed historical stop. It is incorrect to call the 29.36% closed DD an MTM or gap-stressed DD.

## Execution replay prerequisite
Recover per-trade UTC entries, stop triggers, stop fills, exit timestamps, fee/funding, and open-position MTM for all 71 signals (67 completed + 4 censored). Sort by executable UTC, reserve equity across overlapping trades, compare baseline and 0.25%/0.5% stop-risk variants on identical eligible rows. Only then report chronological monthly equity, closed/MTM DD and liquidation checks. The rich microstructure tape is still unverified for matched execution events. Rejected exit overlays remain rejected.

## Reproduction
```python
balances=[100,471.51,755.20,583.32,1037.06,1308.86]
factors=[balances[i+1]/balances[i] for i in range(5)]
print(factors)
print('late-Aug displayed segment return %',100*(balances[3]/balances[2]-1))
print('5x 1% stop + 0.15% cost equity %',-5*(1+.15))
print('5x 1% stop + 2% gap + 0.15% cost equity %',-5*(1+2+.15))
```
No new event-level execution evidence; no claim of forward performance or no liquidations.
