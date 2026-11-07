# HYPE True Local Relation — 116-point retrospective scan

Period: **2026-07-12 17:00 UTC → 2026-08-07 00:00 UTC**

True historical locals inside the snapshot window: **47 = 23 LOW + 24 HIGH**. Same-side non-final extrema used for contrast: **632 LOW + 573 HIGH**.

## The one relationship

**RELATIVE TERMINAL EXHAUSTION / ABSORPTION DIVERGENCE**

A real Local is not simply “buyers became larger than sellers” or the reverse. The repeated state is:

> Price pushes materially farther into the current structural extreme, while the side driving that move loses price-impact efficiency; the opposite side becomes more efficient and near-touch book liquidity thickens/absorbs the continuing pressure.

LOW and HIGH are mirrored versions of this state.

### Local LOW

At true LOW versus similar non-final downside extrema (medians):

- 6h downside penetration: **13.73 bps vs 7.29 bps** (**+88.5% deeper**).
- 60m downside penetration: **13.73 bps vs 7.68 bps** (**+78.9% deeper**).
- Buyer share of 15s aggressive flow: **36.4% vs 22.8%** (**+59.6%**).
- Buyer share of 30s aggressive flow: **37.7% vs 27.6%** (**+36.5%**).
- Seller price-impact efficiency over 60s: **0.00436 vs 0.00634** (**31.3% lower**).
- Seller price-impact efficiency over 180s: **0.00280 vs 0.00478** (**41.4% lower**).
- Opposite-side buyer efficiency magnitude improves by roughly **29% over 30s** and **45% over 180s**.
- Top-5-level book depth: **322.1 vs 278.6** (**+15.6%**).

Plain meaning: sellers are still hitting the market, but they need increasingly more pressure to get less additional downside. Buyers absorb more of the short-window flow, and near-book liquidity is thicker. The final LOW occurs after a deeper structural extension while downside impact is decaying.

### Local HIGH

At true HIGH versus similar non-final upside extrema (medians):

- 6h upside penetration: **8.65 bps vs 5.22 bps** (**+65.7% deeper**).
- 60m upside penetration: **9.10 bps vs 5.67 bps** (**+60.5% deeper**).
- Seller share of 15s counter-flow: **27.5% vs 22.7%** (**+21.1%**).
- Buyer price-impact efficiency over 30s: **0.00452 vs 0.00842** (**46.3% lower**).
- Buyer price-impact efficiency over 60s: **0.00594 vs 0.00742** (**20.0% lower**).
- Buyer price-impact efficiency over 180s: **0.00454 vs 0.00576** (**21.1% lower**).
- Opposite-side seller efficiency magnitude improves by roughly **58% over 30s**.
- Top-5-level book depth: **326.8 vs 248.3** (**+31.6%**).
- Top-10-level depth: **+14.4%**; top-25-level depth: **+17.1%**.

Plain meaning: buyers are still aggressive at the top, but each unit of buy pressure moves price less. Seller-side counter-efficiency improves and near-touch liquidity becomes materially heavier. The final HIGH is a deeper extension with deteriorating upside impact.

## Whole-state scan

I scanned all numeric historical state materialized from the fixed 116-point framework plus derived causal interactions, not only five hand-picked fields. Unstable/noisy dimensions were allowed to drop out rather than being forced into the relation.

A group-balanced whole-state score separates true from non-final same-side extrema with retrospective ROC-AUC:

- **LOW: 0.848**
- **HIGH: 0.813**

Quarter-by-quarter LOW AUC: **0.677, 0.907, 0.755, 0.923**.  
Quarter-by-quarter HIGH AUC: **0.742, 0.886, 0.698, 0.950**.

These are retrospective separation numbers on this history, not a claim of live 85% precision.

## Important coverage audit

The framework contains **116 points**: 86 causal/quality inputs, 28 teacher/evaluation points, and 2 metadata points. The July–August manifest reports 83/86 historical inputs available and misses 111/112/113. The compact artifact also does **not** materialize some promised concepts as independent columns (notably full L50 replenishment/cancellation/absorption dynamics and several explicit sequence/multi-timeframe fields). Therefore this report is the strongest relationship supported by the data actually recorded in that artifact; it does not pretend missing raw dimensions were present.

## Bottom line

**The repeated Local relation is a terminal price-impact divergence.**

The price makes a deeper final extreme, but the continuation side becomes less efficient at moving price while opposite-side absorption/counter-efficiency and near-book liquidity strengthen.

For LOW: **SELL pressure continues → downside impact decays → buyers absorb → LOW matures.**  
For HIGH: **BUY pressure continues → upside impact decays → sellers absorb → HIGH matures.**
