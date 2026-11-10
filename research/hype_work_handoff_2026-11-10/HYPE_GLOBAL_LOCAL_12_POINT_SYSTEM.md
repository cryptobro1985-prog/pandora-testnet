# HYPE GLOBAL LOCAL — 12-POINT CAUSAL SYSTEM
Date: 2026-11-10
Status: frozen research baseline, not a guaranteed production rule
Scope: GLOBAL / TERMINAL H1 Local High and Local Low only. Not tactical bounces inside the same directional leg.

## Objective
Detect the earliest causal confirmation that a GLOBAL terminal H1 Local Low or Local High has formed, using only information available by that timestamp. Target entry distance from the true extreme: ideally about 0.3%-0.7%, while minimizing false-first confirmations.

## Teacher / ground truth
Primary historical teacher: STRICT H1 L6/K2 terminal-final labels.
Important semantics:
- K2 confirms a pivot, not terminality.
- A stronger same-side pivot replaces the prior provisional pivot.
- Terminal final is recognized only after the opposite-side sequence confirms.
- Teacher/future labels are for scoring only and must NEVER enter predictors.
- Do not confuse terminal locals with tactical rebounds or provisional pivots.

## The 12 causal points
1. STRUCTURAL EXTREME — meaningful same-side extreme inside the active structural leg; stronger same-side extreme immediately replaces the old candidate and resets stage clocks.
2. CANDIDATE SURVIVAL / NO NEW EXTENSION — no new lower low after LOW candidate / no new higher high after HIGH candidate during confirmation.
3. RETRACEMENT SPEED / PRICE RESPONSE — response away from extreme normalized by preceding impulse and recent volatility/range; use 30s/60s/180s/300s and M1/M3/M5.
4. TRAJECTORY PERSISTENCE — evaluate 30s -> 60s -> 180s -> 300s path, not one snapshot.
5. MULTI-TIMEFRAME PERSISTENCE — M1/M3/M5 agreement; no M15 requirement.
6. PRICE-IMPACT EFFICIENCY — buyer/seller flow must actually move price; impact efficiency matters more than raw notional.
7. FLOW TRANSITION — imbalance/CVD/control transition around extreme; raw imbalance alone is insufficient.
8. LIQUIDATION EXHAUSTION — LOW: long-liquidation climax decays; HIGH: short-liquidation squeeze decays; missing data = unavailable, never zero.
9. ORDER-BOOK RECOVERY / TRANSFER — L10/L50 transition and replenishment/cancellation, not only absolute imbalance.
10. OPEN INTEREST + PRICE RELATIONSHIP — interpret OI with price and flow state; OI alone is not directional.
11. PRE-EXTREME IMPULSE NORMALIZATION — normalize by prior impulse, 60m/180m range and causal volatility scale; context only, never a waiting gate.
12. FALSE-ATTEMPT / SAME-LEG COMPARISON — compare with earlier failed candidates in the same leg: response speed, impact efficiency, liquidation decay, book recovery, survival and later extension.

## Strongest discovered causal chain
STRUCTURAL EXTREME
-> PRICE RESPONSE
-> FLOW EFFICIENCY
-> LIQUIDATION EXHAUSTION
-> BOOK RECOVERY / TRANSFER

## Historical relationships already found
TRUE LOW:
- stops printing lower lows;
- retraces faster;
- reversal return persists;
- buyer price-impact efficiency rises;
- long-liquidation pressure decays;
- L10/L50 book recovers.

FALSE LOW:
- buys can appear without strong price response;
- seller efficiency stays alive;
- liquidation pressure remains;
- bid recovery is weak/absent;
- another lower low tends to follow.

TRUE HIGH is the mirror image.

Selected historical medians:
- LOW 60s reversal return Jul-Aug: true ~0.1344% vs false ~0.0396%.
- LOW 60s reversal return Oct-Nov: true ~0.1412% vs false ~0.0687%.
- LOW 60s reversal efficiency Jul-Aug: true ~0.00855 vs false ~0.00324.
- LOW 60s reversal efficiency Oct-Nov: true ~0.01275 vs false ~0.00783.
- Jul-Aug LOW long-liquidation exhaustion at +5m: true ~0.00018 vs false ~0.0415.
- Jul-Aug LOW L10 imbalance change +180s to +300s: true ~+0.494 vs false ~-0.0075.
- HIGH 300s reversal return Jul-Aug: true ~0.1991% vs false ~0.0334%.
- HIGH 300s reversal return Oct-Nov: true ~0.2212% vs false ~0.1389%.
- Jul-Aug HIGH short-liquidation exhaustion: true ~0.00219 vs false ~0.0564.

## Validation contract
For every proposed change:
- chronological replay;
- no future leakage;
- first-signal objective;
- LOW/HIGH separate;
- TP/FP/FN;
- precision/recall/coverage;
- median/p90/worst distance and latency;
- false-first severity;
- regime stability;
- sealed/OOS + forward confirmation.

## Optimization target
- identify GLOBAL terminal locals as early as realistically possible;
- avoid tactical bounces being classified as terminal locals;
- ideal entry around 0.3%-0.7% from the extreme when evidence is sufficient;
- prefer UNCERTAIN over a weak false-first;
- one compact frozen rule/model after evaluation, not an ad-hoc filter cascade.
