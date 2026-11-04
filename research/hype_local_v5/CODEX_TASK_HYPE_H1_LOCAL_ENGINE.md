# CODEX TASK — HYPE H1 LOCAL ENGINE

You are working in repository:
cryptobro1985-prog/pandora-testnet

Use research branch:
research/hype-h1-local-v5-oi-microstructure-20261104

Read first:
research/hype_local_v5/HYPE_H1_LOCAL_ENGINE_V5_FINAL_HANDOFF.md

Your only goal is to build the strongest causal H1 Local High / Local Low detector possible for HYPEUSDT.

Do not touch real trading.
Do not enable real orders.
Do not optimize for a target PnL.
Do not use future information in live features.

Use all available 30-day HYPE data and the new forward microstructure data.

Primary historical HYPE artifact:
GitHub Actions run 41736806286
artifact universal-minute-HYPE
artifact ID 13278474318

Raw executed-trade refresh:
GitHub Actions run 41826828580
artifacts:
13319113404
13318817968
13319258376
13319686512
13318779319
13319471883

Forward microstructure artifact:
13321242644

Research code already exists at:
research/hype_local_v5/research.py

The current research result is:

A true H1 local is not simply a flow sign flip.

The best current causal architecture is:

ACTIVE_SWING
-> STRUCTURAL_MATURITY
-> RUNNING_EXTREME
-> OLD-SIDE CLIMAX
-> OLD-SIDE PRICE EFFICIENCY DETERIORATION / ABSORPTION
-> EARLY CONTROL TRANSFER
-> EVIDENCE ACCUMULATION
-> CONFIRMED LOCAL

Hard rule:
after a confirmed LOW, only SEEK_HIGH;
after a confirmed HIGH, only SEEK_LOW.

Before confirmation, any new same-side extreme immediately invalidates the current candidate and moves the running extreme.

The strongest discriminator found so far is retracement fraction of the complete active swing:

abs(current_price - running_extreme)
/
abs(running_extreme - previous_confirmed_local)

Do not replace this with one fixed retracement percentage.

Other strong evidence:
- survival without a new same-side extreme;
- efficiency of the new side in moving price;
- deterioration of the old side's price response;
- persistent price acceptance after transfer;
- executed flow persistence;
- H1 structural maturity;
- H1 range / ATR expansion;
- trade velocity / notional climax.

Now extend the detector with:
- Open Interest change and price x OI state;
- liquidation flow;
- L50 order-book absorption/replenishment;
- add/cancel asymmetry;
- depth consumed versus restored;
- price displacement per aggressive notional;
- price displacement per resting-liquidity removal.

Do not use raw static order-book imbalance as the main signal.

Historical OI, historical full order book and historical liquidation data are not yet complete.
Do not synthesize them.
Find a legitimate reproducible source if possible.
If unavailable, keep those features forward-only and document the limitation.

Required chronological validation:
warmup approximately 2026-10-04..2026-10-10
discovery approximately 2026-10-11..2026-10-26
untouched OOS approximately 2026-10-27..2026-11-02

Also do rolling walk-forward validation inside discovery.

The most important evaluation is NOT candidate-level classification accuracy.

Simulate the actual state machine and measure the FIRST candidate it would accept in every active swing.

Primary metrics:
- first-accepted-candidate precision;
- false-local rate;
- missed-local rate;
- median and P90 confirmation delay;
- median and P90 price distance from true extreme;
- invalidation rate by a new same-side extreme;
- MAE after accepted local;
- stability across chronological folds.

Build ablations:
1. price/H1 structure only
2. + executed flow
3. + OI
4. + liquidation
5. + order book
6. full model

Every new feature family must prove incremental OOS value.

Prefer a transparent sequential likelihood / change-point model over a large black-box classifier.

Conceptually:

LLR_t =
LLR_structure
+ LLR_survival
+ LLR_retracement_fraction
+ LLR_old_side_efficiency_decay
+ LLR_new_side_efficiency
+ LLR_flow_persistence
+ LLR_price_acceptance
+ LLR_OI
+ LLR_liquidations
+ LLR_orderbook_absorption

You may improve this formulation if the data justifies it.

Do not curve-fit dozens of thresholds.
Do not tune on the final OOS.
Do not use future-confirmed pivots as live features.
Do not report a hindsight zigzag as a causal result.

Deliver:
- complete implementation in research/hype_local_v5/
- reproducible scripts/workflow
- machine-readable candidate and swing ledgers
- discovery/walk-forward/OOS results
- ablation results
- exact analysis of every OOS false local and missed local
- final recommended causal Local Engine
- final markdown report
- exact data provenance
- explicit list of unavailable data and remaining uncertainty

Work until the research pipeline runs end-to-end and produces the final report.

Do not stop after writing code.
Run it.
Inspect failures.
Fix them.
Run again.
Then report the actual measured result.
