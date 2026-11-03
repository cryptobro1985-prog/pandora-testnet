# Evidence and evolution

Inspected local history contains 1,316 commits at initial checkout `47023e5`. No profitability is inferred from commit messages.

| Point | Verified content / problem solved | Behavioral effect / failure mode |
|---|---|---|
| `0788b22a67f9f2a11e1dcb85676403721f76b074` | 27 Oct 2026, one-line rename to Caterpillar 1.0 | Original `local_order_flow` uses fresh 60s majority volume for entry, opposite majority for exit and resumption for re-entry. No price-response protection: absorption can be mistaken for control. Historical profit NOT VERIFIED. |
| Original H1 `hype_h1_swing.py` at that SHA | Policy `local_swing_h1_fractal_m15_execution_v12`; closed H1 pivot, separate M15 functions | More than one strategy path existed in app.py. A name alone does not identify which account generated successful trades. |
| `8c6b681a46c59e92e5e206d74189ba997add5ac9` | Causal immutable adaptive H1 reconstruction | Changes Local algorithm, not merely transport; cannot transfer claimed PnL to another Local algorithm. |
| 29–31 Oct history | Numerous commits alternately introduce/remove MFE gates and M1/M3/M5 requirements | Conflicting execution variants exist; a uniquely successful canonical account cannot be established from source alone. |
| `1c3d14787f188f403e84adecf1eb6b8ef3c5cd3d` | Sharded sockets and strict 15s trade freshness | Transport reliability; insufficient alone to validate strategy. |
| `8c94e84b1fe769c98f4af8fbd3e011b06a574cd4` | Preserve history across short reconnects | Infrastructure change that can alter decision continuity. New isolated runtime deliberately rewarms after reconnect as required by this task. |
| `c786af04c86b270e89e665464b4c67303adb6152` | Opposite confirmed active Local closes existing positions during warmup | Separates allocation readiness from emergency management. Implemented in new runtime independently of flow warmup. |
| `a12e23d8e0507725844ec0466e18db69afddf84b` | Existing 30d trigger, period 2026-10-04 to 2026-11-03, split 2026-10-27 | Exact ten-symbol research dataset verified; it is not a live selection list. |
| Research source | H1 variants lb2/4/6/10, retreat 0/5/10bps, 1/2 confirming bars; separate entry/exit/re-entry hypothesis streams | These are competing hypotheses, not established results. Fees 4.5bps and slippage 2bps per side are source-confirmed defaults. |
| Current late flow commits | 60/108/180/300 consensus, profitable MFE prerequisites, fixed ten-token cohort | Material strategy changes, not transport repairs. New runtime does not silently inherit them. |

After resolving native Git authentication through `gh auth git-credential`, the requested missing branches and PR ref were fetched without changing main:

- `9a3b9c5f41cb59f29e8df084f112daa0dd869619`: final audit branch. Adds liquidity admission, explicit 3s counter-control evidence, structural exit checks and accounting/mobile fixes. `EXIT_CONTROL_CONFIRM_SECONDS=3`, max event gap 5s, evidence window 15s are strategy behavior changes; these timers are not inherited into the event-block runtime. Its own audit says synthetic tests do not establish actual ETH trade behavior.
- PR #18 head resolves to `65b5efc20661a4222cae7ea123af622f514709fe` via `refs/pull/18/head`. It increases `CONTROL_DEADBAND` from .03 to .12, fixes resumed control from absolute imbalance to own-side aligned imbalance, and adds net-profitable MFE recoil to normal exits. Solves churn and wrong-side resumption; changes behavior and can keep losing positions until H1 invalidation. The new runtime uses research .15 control and does not inherit the profit/MFE exit restriction.
- `f722ab98c0f464cda844ddf01216ee774bed8c4f`: five-token synthesis workflow exists. It extracts AAVE (artifact 13216296844), DOGE (13217067189), SUI (13217755862), WLD (13217654406), 1000PEPE (13218807932), with counts, top hypotheses, pattern metrics, synthesis and open books. This verifies the provenance and schema, not the actual artifact outcomes.

Actions run contents `41601978354` and `41659751109`, five-token synthesis evidence.json, actual research PnL and cross-token outcomes remain NOT VERIFIED. The current cloud proxy denied GitHub API access. Research source contains the requested rejection families, H1 variants and nine exit families; source labels are not empirical validation of those rules. The new runtime is an auditable PAPER candidate using confirmed source components, not a claim that the successful historical brain or a profitable optimum has been recovered.

Validation: 31 new PAPER tests and 112 existing research tests passed, including actual loopback websocket ingress/ACK, entry/exit/re-entry, account conservation, conservative margin, liquidation gaps, H1 causality, corruption and restore. Mobile monitor was opened in real Chromium at 360px: five token cards, position rendering, no horizontal overflow, escaped external text, stale transition and no JS exceptions. Those UI inputs were synthetic test state, not real exchange results.

The legacy root application suite was previously observed to fail (218 executed; 30 failures, 9 errors, no skips). Its files are unchanged by this branch. New runtime's critical gates and research tests are separate; this does not make the legacy suite green.
