# HYPE Ultra Survival Trading Layer — 2026-11-11

## Executive result

This work deliberately **returns to the strongest reproducible Local detector**
instead of the later weak generic ensembles.

Detector:
`HYPE_LOCAL_ULTRA_SURVIVAL_V2` frozen unchanged.

Frozen detector evidence:
- development: 167 accepted / 167 true-first / 0 false-first;
- sealed May 2026: 31 accepted / 31 true-first / 0 false-first;
- new replay across May + Jul-Aug + Aug-Sep + Sep-Oct + Oct-Nov:
  **152 accepted / 152 true-first / 0 false-first**.
This remains a high-confidence subset, not 100% coverage and not a future
guarantee.

The trading layer is research/paper-only. Real orders remain OFF.

---

## 1. Entry geometry

Verified workflow:
`HYPE Ultra Survival V2 — Entry Exit Stop Geometry`
GitHub Actions run: **42996512191**.

Aggregate over 152 accepted frozen signals:
- median entry distance from true Local: **1.992%**;
- p90 entry distance: 3.919%;
- median remaining reference swing fraction: **42.37%**;
- median MFE after entry: **1.297%**;
- p90 MFE: 3.929%;
- median MAE: **0.356%**;
- p90 MAE: 0.981%.

A simple wait-until-next-opposite-Ultra-signal exit is NOT good enough:
- 147 matched signal-to-opposite-signal legs;
- median return around **-0.049%** before a full execution model;
- positive fraction ~48.98%.

Therefore:
**Ultra is used for high-confidence entry, but MFE is protected dynamically;
the strategy does not wait indefinitely for the next rare Ultra signal.**

---

## 2. Emergency stop geometry

MAE before the first +0.5% MFE on true signals:
- median: 0.280%;
- p90: 0.929%;
- p95: **1.160%**;
- p99: **1.933%**;
- maximum: 2.841%.

True-signal survival before first +0.5% MFE:

| Emergency stop | True signals surviving |
|---|---:|
| 0.50% | 69.74% |
| 0.80% | 84.21% |
| 1.00% | 92.11% |
| 1.25% | 95.39% |
| 1.50% | 96.71% |
| 2.00% | **99.34%** |
| 3.00% | 100% historical |

On sealed May, a 2.0% stop would have preserved all 31 correct signals in
this historical OHLC geometry. This is not a guarantee of future execution.

---

## 3. Two dynamic exit variants

Exit parameters were selected using ONLY:
- Jul12-Aug07;
- Aug08-Sep01;
- Sep01-Oct01.

The selected parameters were then scored on Oct04-Nov03.
May is shown separately as a diagnostic; May detector itself was genuinely
sealed, but the exit parameters were chosen later and therefore May is NOT an
untouched exit validation.

### Variant A — robust-growth / flow-confirmed

Parameters:
- emergency stop: **2.0% underlying**;
- enable MFE protection after MFE >= **+0.50%**;
- allowed recoil: `max(0.35%, 45% of current MFE)`;
- require opposite 3-minute executed-flow/price response confirmation;
- exit at next minute open;
- opposite frozen Ultra signal -> CLOSE + FLIP.

Development:
- Jul-Aug: +5.651%, 20/26 wins, DD 2.12%;
- Aug-Sep: +3.101%, 19/27 wins, DD 3.34%;
- Sep-Oct: +3.380%, 26/34 wins, DD 3.91%.

Later historical Oct-Nov:
- 34 trades;
- 26 winners;
- win rate **76.47%**;
- compound underlying return after 12bps modeled roundtrip cost:
  **+4.466%**;
- max drawdown 2.371%;
- median MFE capture ~31.98%.

May diagnostic:
- 28/31 winners;
- +22.297% underlying;
- DD 2.12%.

This variant is more conservative but gives back too much MFE.

### Variant B — MFE-capture-first

Chosen only among parameter combinations that were positive on ALL three
development blocks, maximizing worst-block median MFE capture.

Parameters:
- emergency stop: **1.50% underlying**;
- MFE protection activation: **+0.75%**;
- exit when recoil from MFE reaches
  `max(0.25%, 35% of current MFE)`;
- one completed bar of confirmation;
- no flow veto required for the trailing exit;
- opposite frozen Ultra signal -> CLOSE + FLIP.

Development:
- Jul-Aug: 22/26 wins, **+4.272%**, DD 3.214%, median capture 58.79%;
- Aug-Sep: 20/27 wins, **+0.375%**, DD 6.628%, median capture 55.95%;
- Sep-Oct: 28/34 wins, **+6.152%**, DD 3.617%, median capture 57.41%.

Later historical Oct-Nov:
- **34 trades**;
- **30 winners**;
- win rate **88.24%**;
- compound underlying return after modeled 12bps roundtrip cost:
  **+15.017%**;
- max drawdown: **2.846%**;
- median MFE: 0.913%;
- median MAE: 0.397%;
- median MFE capture: **60.15%**;
- emergency stops: 3;
- MFE exits: 30;
- opposite-Ultra flips: 1.

May diagnostic:
- 31 trades;
- 27 winners;
- +11.046% underlying;
- DD 3.223%;
- median MFE capture 58.30%.

**This is the strongest current historical trading layer.**
It is promising, NOT production-proven: hundreds of exit combinations were
examined, so a genuinely new forward period is mandatory.

---

## 4. Leverage / margin stress of Variant B

Paper stress assumptions:
- selected 1.50% emergency stop;
- base modeled roundtrip cost already included in trade returns: 12bps;
- add another 8bps friction in the selected stress;
- emergency-stop-only gap shock: +0.25% underlying;
- approximate maintenance rate: 0.5%;
- require approximate liquidation distance >= 2.5x stressed-stop distance;
- require stressed stop loss <= 2% of account equity.

Selected bounded-aggressive paper scenario:
- leverage: **5x**;
- equity used as margin: **20%**;
- effective notional exposure: **1.0x account equity**;
- stressed compound Oct-Nov: **+11.090%**;
- stressed max DD: **3.650%**;
- approximate liquidation distance: 19.5%;
- stressed stop distance: 1.95%;
- liquidation-distance cushion: 10.0x;
- stressed one-stop equity loss: 1.95%.

Equivalent 1.0x effective exposure at 10x / 10% margin produces the same
paper PnL but has materially less liquidation cushion (~4.87x). Therefore
5x/20% is the cleaner bounded scenario if effective exposure is the same.

More aggressive selected examples under +8bps/+0.25% stop-gap stress:
- 10x / 7.5% margin = 0.75x exposure: +8.256%, DD 2.740%;
- 15x / 5% margin = 0.75x exposure: +8.256%, DD 2.740%;
- 20x / 5% margin = 1.0x exposure: +11.090%, but fails 2.5x liquidation cushion;
- 25x / 5% margin = 1.25x exposure: +13.964%, but fails both chosen safety gates;
- 25x / 20% margin = 5.0x exposure: historical stress shows +61.678%, but
  worst stressed stop ~9.75% equity and liquidation cushion only ~1.79x:
  **REJECTED**.

Under harsher +8bps +0.75% emergency-stop gap shock, a safe bounded scenario
still exists around <=0.75x effective exposure, but this is a scenario model,
not a guarantee.

No finite stop/leverage configuration can guarantee non-liquidation under
arbitrary gaps, exchange outage, stop failure or mark-price dislocation.

---

## 5. Earlier entry

The reproducible HARD120 detector:
- median historical entry distance ~**1.293%** from Local, closer than Ultra;
- Oct-Nov first-signal precision ~92.98%, recall ~44.17%;
- it has historical false signals.

EARLY60 can be even earlier, but it failed a later untouched September
promotion check as an additive stack component.

Therefore:
- **DO NOT replace full-size Ultra with HARD120/EARLY60**.
- If an earlier-entry layer is researched, it should be a small PAPER probe
  with strict risk budget, then scale only when frozen Ultra confirms.
- This two-stage probe/full-position architecture still needs its own
  chronological economic replay before any position-size recommendation.

---

## Current strategy state

**ENTRY**
- structural 6h extreme lineage;
- same-side extension resets candidate;
- frozen Ultra Survival confirmation;
- LOW -> LONG; HIGH -> SHORT.

**HOLD**
- once MFE >= 0.75%, do not close on a normal small pullback.

**MFE PROTECTION**
- Variant B: trailing causal recoil
  `max(0.25%, 35% of MFE)`, then next-minute exit.

**FLIP**
- confirmed opposite frozen Ultra signal immediately closes old side and
  authorizes the opposite side.

**EMERGENCY**
- 1.50% underlying emergency stop in capture-first variant.
- This is an emergency tail-risk control, not the normal exit.

**CURRENT PAPER RISK REFERENCE**
- 5x leverage / 20% margin (1.0x account notional exposure) passed the defined
  bounded stress better than higher leverage at equal/excess exposure.
- REAL ORDERS remain OFF until new untouched forward evidence.

---

## Statistical status

What is genuinely strong:
- the detector was frozen before May and scored **31/31 true-first, 0 false**
  on sealed May;
- the same frozen detector reproduced 152/152 true-first across the replayed
  blocks.

What is NOT yet sealed:
- the 1.5% stop;
- the MFE activation/recoil exit parameters;
- leverage/margin;
- the two-stage early-probe idea.

Therefore the full trading system must now be **frozen exactly** and scored
without retuning on newly collected forward data.

The historical result is promising evidence, not a promise of daily profit,
zero drawdown or zero liquidation.
