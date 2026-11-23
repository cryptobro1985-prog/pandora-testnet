# D250 causal clock and entry admissibility audit — 2026-11-23 15:35 CET

Research only; no live orders, no detector retraining, no baseline modifications.

## Verified frozen baseline
Read H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md directly on the specified branch. Frozen checkpoint: **250 minutes after candidate/extreme**, with rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, side-normalized flow15 < 0.4504731635235635. Its own result: 71/71 accepted true first on the historical test, 67 completed opposite locals, median MFE giveback 61.2% at K2-available opposite-local exit. The frozen report does not independently certify 71 tradable fills.

## New causal timing audit (no invented historical trades)
The historical report describes a clock measured from the *candidate/extreme*, but the desired strategy explicitly requires an **already confirmed terminal strict-H1 local**. These are different timestamps. The exact admissible order is:

1. t_extreme: H1 extreme's bar closes; this is NOT necessarily when the strict pivot is knowable.
2. t_pivot_available: the terminal H1 pivot first becomes confirmed with only elapsed H1 bars (K2 if that is the actual pivot definition).
3. t_D250_available: all D250 features use fully closed, observed intervals and the 250-minute delay is satisfied.
4. t_order_eligible = max(t_pivot_available, t_D250_available, t_rich_veto_available) with explicit veto data freshness; execution is at the next observable bid/ask, never the extreme or signal bar close retroactively.

For every historical accepted signal, compute t_order_eligible and re-evaluate whether (a) a same-side higher high/lower low printed before that instant; (b) an opposite confirmed H1 local was already available; (c) any data gap, stale book, or unknown feature blocks execution; and (d) any entry is assigned a future fill or uses future ATR/baseline volume. An earlier pivot label cannot be treated as a real-time signal unless its *availability timestamp* is separately present. D250's 250-minute lag is not proof that all features/pivot confirmation were causally available.

**Concrete negative-control timing cases** (logic proofs, not observed HYPE events):
- Extreme at 00:00, D250 ready 04:10, strict pivot known 05:00 => earliest decision 05:00, not 04:10.
- Extreme 00:00, pivot known 02:00, D250 ready 04:10 => earliest decision 04:10.
- Extreme 00:00, D250 ready 04:10, same-side extreme at 04:00 => reject, even if a 04:10 feature row exists.
- Extreme 00:00, D250 ready 04:10, opposite local becomes available at 03:00 => reject; do not enter a completed swing.
- Book becomes fresh at 04:11 after D250 ready 04:10 => earliest *eligible* execution 04:11, not 04:10. If rich veto data are unavailable, mark unknown/blocked; never zero-fill.

These five examples expose a *potential* lookahead issue to test, not a demonstrated error in the original 71.

## Reproducible executable clock check
```python
from datetime import datetime, timedelta, timezone
def eligibility(extreme, pivot_available, d250_available, veto_available, same_side_extreme=None, opposite_available=None):
    if d250_available < extreme + timedelta(minutes=250):
        return "REJECT_D250_EARLY", None
    ready = max(pivot_available, d250_available, veto_available)
    if same_side_extreme is not None and same_side_extreme <= ready:
        return "REJECT_INVALIDATED", None
    if opposite_available is not None and opposite_available <= ready:
        return "REJECT_SWING_FINISHED", None
    return "ELIGIBLE_NEXT_QUOTE_ONLY", ready
t=datetime(2026,1,1,tzinfo=timezone.utc)
assert eligibility(t,t+timedelta(minutes=300),t+timedelta(minutes=250),t)[1]==t+timedelta(minutes=300)
assert eligibility(t,t+timedelta(minutes=120),t+timedelta(minutes=250),t)[1]==t+timedelta(minutes=250)
assert eligibility(t,t+timedelta(minutes=120),t+timedelta(minutes=250),t,t+timedelta(minutes=240))[0]=="REJECT_INVALIDATED"
assert eligibility(t,t+timedelta(minutes=120),t+timedelta(minutes=250),t,None,t+timedelta(minutes=180))[0]=="REJECT_SWING_FINISHED"
assert eligibility(t,t+timedelta(minutes=120),t+timedelta(minutes=250),t+timedelta(minutes=251))[1]==t+timedelta(minutes=251)
print("PASS 5 deterministic causal-clock cases; no historical executions certified")
```

## Status and next evidence requirement
The original 71-signal row-level immutable cohort and per-signal raw Bybit tape are not independently recovered in this checkpoint. Hence **0 newly certified real fills**; historical fill count, net monthly equity, MTM DD, liquidation count and MFE captured remain unknown. Do not interpret this as zero historical fills. Before any stop/trailing comparison, recover the timestamp quartet (extreme, pivot confirmation, D250 feature completion, first executable quote), run this clock test on all 71 with source-attested data, and keep only eligible signals. Compare baseline and low-risk variants on exactly the resulting identical cohort. Rejected fixed ATR trails and MFI+flow exits remain rejected. No new threshold fitted.
