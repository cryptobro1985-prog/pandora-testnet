# CODEX HANDOFF — PANDORA Strategy 1
Updated: 2026-10-28

## Start here
Repository: cryptobro1985-prog/pandora-testnet
Branch: main
Render service: pandora-testnet-monitor
Render service id: srv-dbfmf3i9lscs73amdrjg
Render monitor: https://pandora-testnet-monitor-nfoc.onrender.com

The user wants to continue development in Codex from this exact repository state.

## Current decision
The experimental "algo-footprint / peer lead-lag / absorption-exhaustion optimizer" branch was REJECTED after a causal 12h test and has been removed from the active codebase and Render image.

Rejected test:
- window: 2026-10-27 12:00–24:00 UTC
- symbols: INIT, NEAR, GRASS, HYPE
- start equity: $500
- 20% current equity margin, 25x reference leverage, compounding
- algo-footprint result: $233.1250 (-53.375%)
- baseline in that same comparator: $214.9279 (-57.014%)
Therefore do NOT reintroduce strategy1_algo_footprints, peer lead-lag filters, or the rejected optimizer unless explicitly requested.

## Canonical Strategy 1 to continue
File: local_caterpillar.py
Current file is byte-identical to baseline commit:
3dcc908e90c442d914a98977ba2cd0329b4ba976

Policy:
local_h1_multihorizon_flow_caterpillar_v14_universal

Symbols currently used:
- INIT
- NEAR
- GRASS
- HYPE

Paper model:
- starting equity: $500
- margin per position: 20% of CURRENT MTM equity
- leverage reference: fixed 25x in this paper experiment
- compounding: ON
- maximum positions: 4

Structural direction:
- H1 confirmed Local High => SHORT only until confirmed H1 Local Low
- H1 confirmed Local Low => LONG only until confirmed H1 Local High
- lower timeframes may manage execution but must NOT reverse the H1 side independently

Execution concept:
1. Enter only when M15 recovery and fresh executed-flow agree with H1 direction.
2. Hold while flow continues to support H1 side.
3. Exit on genuine weakening / control transfer, not on one green/red candle.
4. After exit remain flat through the pullback/bounce.
5. Re-enter only after pullback + opposite pressure + renewed original-side flow.
6. Repeat until opposite H1 local invalidates the trade side.
7. No arbitrary fixed TP.
8. No spam entries.
9. Catastrophic/protective stop only; routine exit is weakening/control transfer.
10. No averaging down.

Current multi-horizon executed flow:
- 15s
- 30s
- 60s
- 300s when available

Current v14 thresholds in local_caterpillar.py:
- weakening: aligned15 < .02, aligned30 < .06, aligned15 <= aligned60 - .08
- counter control: aligned15 <= -.12 and aligned30 <= -.08
- resumed: aligned15 >= .16, aligned30 >= .12, aligned60 >= .08
- strong resumed: aligned15 >= .20, aligned30 >= .15, aligned60 >= .10

Important live corrections already made:
- legacy independent profit-floor exit was removed from Strategy 1
- post-exit watch no longer starts with counter-pressure pre-marked true
- re-entry must observe actual post-exit counter-pressure and fresh resumption

## What the "$800+" number actually was
Do not treat "$800+" as confirmed stable causal performance.

Earlier actual-entry MFE analysis produced an upper-bound opportunity of approximately:
$500 -> $877.36
This was a hindsight / MFE ceiling from favorable excursions after actual entries, NOT realized causal PnL and NOT a guaranteed/stable result.

The goal is to improve causal capture of those large moves without lookahead.

## Research data
Official Bybit public trade archives were used for trade-level historical flow:
https://public.bybit.com/trading/<SYMBOL>/

Available/recently tested symbols:
INITUSDT, NEARUSDT, GRASSUSDT, HYPEUSDT

strategy1_week_backtest.py remains as a baseline research utility.
Heavy research autostart was removed; run research explicitly so it does not compete with live PAPER workers.

## What to improve next
Do NOT optimize to a target dollar amount.

Priority:
1. Audit every losing Strategy 1 entry and re-entry.
2. Compare entry timing vs subsequent MFE/MAE.
3. Find which existing H1/M15/15s-30s-60s conditions distinguish:
   - continuation
   - temporary bounce
   - genuine H1-side failure
4. Improve exit capture: reduce giving back MFE while avoiding premature closes.
5. Improve re-entry: eliminate repeated low-quality reentries during chop.
6. Keep rules universal across tokens; avoid symbol-specific hacks.
7. Use causal walk-forward / out-of-sample validation.
8. Report:
   - final equity
   - net PnL
   - max drawdown
   - trades
   - win rate
   - profit factor
   - MFE capture ratio
   - per-symbol stats
9. Never label reconstructed/counterfactual trades as executed.
10. Never claim guaranteed profit or 100% win rate.

## Operational rule for deploys
When asked to deploy:
1. use latest main HEAD
2. deploy to existing Render service srv-dbfmf3i9lscs73amdrjg
3. verify exact commit is LIVE
4. inspect runtime diagnostics after deploy
5. do not substitute "Render is on an old version" for actually deploying

## Do not delete historical PAPER data without explicit approval
Destructive history/database cleanup requires explicit user confirmation.

## Suggested first Codex task
"Audit current Strategy 1 (local_caterpillar.py + the Strategy 1 path in app.py) against the canonical rules in CODEX_HANDOFF_STRATEGY1.md. Do not alter other PANDORA strategies. Build a causal replay diagnostic that identifies why each losing entry/re-entry occurred and measures MFE capture loss. Propose and validate universal changes on INIT/NEAR/GRASS/HYPE with walk-forward testing before modifying live logic."
