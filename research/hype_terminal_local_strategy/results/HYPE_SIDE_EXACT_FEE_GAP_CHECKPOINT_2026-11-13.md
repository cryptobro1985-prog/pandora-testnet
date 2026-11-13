# HYPE side-exact execution fee and stop gap stress — 2026-11-13

Research-only numerical checkpoint. Frozen entry/exit unchanged; no retraining, orders, production changes, or new branch.

## Exact linear-contract side model

With entry price P, 1% adverse trigger, and extra adverse execution gap g as fraction of entry price, LONG fill=P*(0.99-g), SHORT fill=P*(1.01+g). For fixed entry notional, fee f=0.075% on entry and exit notionals (illustrative, NOT verified account fee), exact losses per entry notional are:
- LONG = 0.01+g+f*(1+0.99-g)
- SHORT = 0.01+g+f*(1+1.01+g)

The short costs slightly more because its adverse exit notional is higher. The prior flat 0.15% roundtrip approximation suppresses this asymmetry. This is deterministic arithmetic, NOT empirical slippage.

| Extra gap | LONG loss/notional | SHORT loss/notional | Short extra (bps) | Max exposure for 0.25% equity risk, SHORT | Max exposure for 0.5% equity risk, SHORT |
|---:|---:|---:|---:|---:|---:|
| 0.0% | 1.1493% | 1.1507% | 0.150 | 0.2172x | 0.4345x |
| 0.5% | 1.6489% | 1.6511% | 0.225 | 0.1514x | 0.3028x |
| 1.0% | 2.1485% | 2.1515% | 0.300 | 0.1162x | 0.2324x |
| 2.0% | 3.1477% | 3.1522% | 0.450 | 0.0793x | 0.1586x |

## Same hypothetical 1% gap, side-separated account loss

| Account notional exposure | LONG equity loss | SHORT equity loss |
|---:|---:|---:|
| 0.1x | 0.2149% | 0.2152% |
| 0.2x | 0.4297% | 0.4303% |
| 0.2326x | 0.4997% | 0.5004% |
| 0.4x | 0.8594% | 0.8606% |
| 3x | 6.4455% | 6.4545% |
| 5x | 10.7425% | 10.7575% |

## Fee-only break-even move

For a favorable LONG price move r, net per entry notional is r-f-f*(1+r), so r=2f/(1-f) = 0.15011%. For a favorable SHORT, r-f-f*(1-r), so r=2f/(1+f) = 0.14989%. Funding and slippage increase these hurdles.

## Liquidation and evidence boundary

25x instrument leverage implies roughly 4% initial isolated margin per entry notional before maintenance margin and fees, but actual liquidation distance is UNKNOWN without Bybit risk tier, maintenance margin, collateral, mark-price path and funding. A stop-market trigger does not guarantee a fill. Therefore no zero-liquidation claim.

Inputs read from existing branch: HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md (frozen 1% cut, approximate 0.15% roundtrip, 67 simulated sequential trades) and HYPE_RISK_BUDGET_GAP_MATRIX_2026-11-13_RUN6.md (gap stress). This is a new side-aware analytic check, NOT matched Public Trades/L50 replay; no new monthly net equity, MTM DD, fills, MFE or independent forward metrics are available. Rejected profit-protection overlays remain rejected. No strategy promotion.

**Next required empirical step:** recover exact timestamped frozen 67 trades plus tick/mark/depth/funding events; replay identical chronological sample for original 3x/5x and 0.25–0.5% risk sizing, LONG and SHORT separately, nonoverlapping collateral, frozen forward partition. The 0.5%-risk SHORT-side cap with hypothetical 1% extra gap is 0.2324x before other constraints.
