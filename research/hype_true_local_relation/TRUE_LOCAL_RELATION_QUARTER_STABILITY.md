# HYPE True-Local relation — quarter-stability baseline

This is the stability baseline from the completed July–August artifact, before the new dynamic-L50 rebuild.

## LOW

The strongest relation is not one indicator. It is a synchronized terminal state:

- seller share on the 15s window is lower: **63.6% vs 77.2%**;
- buyer counter-share on 30s is higher: **37.7% vs 27.6%**;
- the downside structural penetration is deeper: **13.73 bps vs 7.68 bps** over 60m;
- trade activity is higher: **661 vs 559 trades/60s**;
- the short-vs-long continuation-impact profile is weakening;
- spread is slightly wider and the whole flow state changes together.

A single rank-composite built from the stable dimensions produced quarter AUCs:

**0.875 / 0.821 / 0.831 / 0.821**

That is important because the LOW signature does not disappear when the history is split chronologically.

## HIGH

The old static-book artifact gives a weaker but still repeated relation:

- top-5 book depth: **326.8 vs 248.3**;
- reversal-side 25-level depth: **1455.3 vs 1208.3**;
- the 6h extreme is deeper;
- the 60s-vs-300s buy price-impact slope is lower at the final HIGH.

Quarter AUCs:

**0.713 / 0.738 / 0.690 / 0.775**

The HIGH relation is clearly less complete than LOW in the old artifact. The main missing measurement is dynamic L50 behavior: ask replenishment, removal, churn and absorption while buyers continue to hit the top.

## What is being rebuilt now

The active full run adds:

- explicit bid/ask replenishment;
- insertions and removals;
- cancellation/withdrawal proxies;
- book churn over 5/15/30/60/180/300s;
- bid and ask absorption relative to executed sell/buy flow;
- separate BUY and SELL price-impact efficiency;
- causal M1/M3/M5/H1 state ending at the exact local timestamp.

The new result must beat this stability baseline, especially for HIGH.
