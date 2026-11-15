# HYPE stop-to-liquidation buffer audit — 2026-11-15 07:27 CET

Research-only checkpoint. No retraining, production changes, or orders. Frozen D250 and 1% adverse-price cut unchanged.

## Verified source baseline
Read the existing frozen D250 walk-forward report, asymmetric-risk report, and 06:30 CET stop-gap frontier directly from this branch. 71 accepted historical local classifications are not 71 executable fills; only 67 opposite-local outcomes finalized. The 5x exposure $100->$1,308.86 and 29.36% closed DD are historical simulation, not mark-to-market or forward trading. The old 0.15% roundtrip cost is assumed, not a measured ledger.

## New stress: stop-to-liquidation *distance*, separate from nominal stop budget

A 25x isolated linear position has an initial margin of about 4% of notional. Ignoring maintenance margin, fees, funding, and mark/last basis, a **4% adverse mark move** consumes that initial margin. Actual liquidation occurs *before* this simplified boundary, depending on maintenance margin, account mode, risk tier, other positions and exchange mechanics. Thus 4% is a generous theoretical ceiling, **not** a calculated Bybit liquidation price.

For a 1% adverse stop trigger and adverse post-trigger price gap g, the adverse price excursion before fill is 1% + g. This table measures the naive residual distance to the generous 4% ceiling; the true buffer is smaller or unknown:

| Additional adverse gap g | Price excursion from entry at fill | Naive buffer to 4% ceiling | Assessment at 25x isolated |
|---:|---:|---:|---|
| 0.0% | 1.0% | 3.0 percentage points | not a liquidation guarantee |
| 0.5% | 1.5% | 2.5 pp | mark/index divergence still unknown |
| 1.0% | 2.0% | 2.0 pp | fill before liquidation unverified |
| 2.0% | 3.0% | 1.0 pp | narrow theoretical buffer |
| 3.0% | 4.0% | 0.0 pp | theoretical margin exhausted; liquidation may precede fill |
| 5.0% | 6.0% | -2.0 pp | cannot assume ordinary stop execution before liquidation |

**Crucial:** reducing notional to $23 does not by itself widen the *price* distance to liquidation at fixed 25x isolated leverage. Lower leverage (or more collateral under correctly modeled margin rules) may increase distance. Risk-based sizing limits nominal dollar exposure, not execution/liq certainty.

## New capital-risk sensitivity including funding reserve
For equity $100, frozen 1% trigger, assumed roundtrip fee 0.15% of notional, *illustrative* 0.06% funding reserve, and additional adverse fill gap g:

Loss per nominal = 0.0100 + 0.0015 + 0.0006 + g. Max notional = equity risk budget / loss per nominal.

| Gap | All-in assumed loss/nominal | Notional at 0.25% equity risk | Notional at 0.50% equity risk | Initial margin at 25x for 0.50% |
|---:|---:|---:|---:|---:|
| 0.0% | 1.21% | $20.66 | $41.32 | $1.65 |
| 0.5% | 1.71% | $14.62 | $29.24 | $1.17 |
| 1.0% | 2.21% | $11.31 | $22.62 | $0.90 |
| 2.0% | 3.21% | $7.79 | $15.58 | $0.62 |
| 3.0% | 4.21% | $5.94 | $11.88 | $0.48 |

These are *conditional scenario limits*, not empirical Bybit slippage quantiles or guaranteed maximum loss. At 1% gap the $22.62 nominal supersedes the fee-only $23.26 figure only when explicitly reserving the extra 0.06% illustrative funding. Funding rates and accrual must be taken from matched real records, not substituted by this constant.

## LONG/SHORT execution geometry
- LOW -> LONG: confirm D250 availability before entry; stop-market sell triggers 1% below actual long fill, measure available bid depth, bid-side impact, sell sweep, mark-vs-last basis and order acknowledgement.
- HIGH -> SHORT: confirm D250 availability before entry; stop-market buy triggers 1% above actual short fill, measure ask depth, buy-side impact, squeeze/liquidation bursts, mark-vs-last basis and order acknowledgement.
- The two sides cannot share an assumed slippage distribution without evidence. No same-side extension or future opposite extreme may be consulted for entry.
- Use exchange-confirmed order state; on stop gap, record whether liquidation preceded execution. No assumption of stop fill if a stop-limit is not marketable.

## Reproduction and checks
```python
equity=100
for gap in (0,.005,.01,.02,.03):
    loss=.01+.0015+.0006+gap
    n25=.25/loss
    n50=.50/loss
    print(f"{gap:.3f} {loss:.4f} {n25:.2f} {n50:.2f} {n50/25:.2f}")
    assert abs(n50*loss-.50)<1e-9
    assert abs(n25*loss-.25)<1e-9
    assert n50<=equity
    print("naive_liq_buffer_pp",100*(.04-(.01+gap)))
```

## Evidence status / next concrete replay requirement
This is a new deterministic margin-buffer and funding-inclusive stress calculation, **not** matched event replay. GitHub default-branch code searches for `hype_terminal_local_strategy trade_ledger`, `HYPEUSDT public_trades l50`, and `hype_unified_entry_mfe` returned no indexed hits; these negative default-branch results do **not** establish that the research branch or Actions artifacts lack data. Need original 71 timestamped accepted rows, 67 fills plus 4 censored episodes, event/receipt timestamps, Public Trades, L50 snapshots, mark price, liquidation stream, funding and OI coverage to compute true stop-first replay. Reject any missing or stale interval rather than imputing zero.

No new measured net equity, monthly DD, liquidation count, MFE capture or independent forward trading result. Existing rejected flow/MFE and K0/K1 overlays remain rejected. Stop-to-liquidation risk should be explicitly modeled before claiming any low-risk 25x strategy.
