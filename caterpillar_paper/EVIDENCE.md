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

## Retrieved empirical evidence

The finite GitHub-native evidence workflow successfully retrieved all five synthesis `evidence.json` artifacts and published the originals on `caterpillar-runtime-evidence` at `6da712ddf20901632b51f3244dcae7c0d2b1c13e`. They were then fetched via native Git and inspected locally. Run `41601978354` is confirmed completed with conclusion **failure**, at the requested `a12e23d8…`; run `41659751109` completed **success**, at the requested `f722ab98…`. A successful synthesis does not establish complete 30-day coverage.

| Token | Synthesis status | Re-entry ready / rejected |
|---|---|---|
| AAVE | PRELIMINARY_MULTI_DAY | 4,323 / 71,658 |
| DOGE | INSUFFICIENT_DATA | 1,276 / 30,626 |
| SUI | INSUFFICIENT_DATA | 6,133 / 120,755 |
| WLD | PRELIMINARY_MULTI_DAY | 12,711 / 254,582 |
| 1000PEPE | INSUFFICIENT_DATA | 9,256 / 205,702 |

Every token has empty Local, Entry, Hold and Re-entry candidate lists. Absorption exit candidates are preliminary on AAVE/WLD only. WLD's short absorption evaluation mean is +1.91bps over 90 samples/6 days, but its daily-mean median is **-7.46bps**, which argues against declaring a robust universal rule. AAVE evaluation MFE-recoil LONG mean is **-8.04bps** (270 samples/5 days), DOGE discovery MFE-recoil LONG **-9.91bps** (429/7), SUI discovery MFE-recoil LONG **-8.75bps** (1,175/16), WLD discovery MFE-recoil LONG **-8.18bps** (1,642/18). These heterogeneous observational books do not support a standalone universal MFE stop or a calibrated profitable replacement strategy.

All requested entry rejection families appear in the actual no-trade evidence. The six requested re-entry rejection reasons are present across all five tokens. For example AAVE records ORIGINAL_CONTROL_NOT_RETURNED 53,907, ORIGINAL_FLOW_NOT_ACCELERATING 37,349, NO_CORRECTION_DEPTH 32,582, ORIGINAL_SIDE_ABSORBED 1,784, ORIGINAL_LOCAL_LOST 20 and STRUCTURE_OPPOSES_REENTRY 8. Counts are overlapping research opportunities, not independent trades or calibrated probabilities. No per-token optimization was applied.

The new runtime is an auditable PAPER candidate using confirmed source components, not a claim that the successful historical brain or a profitable optimum has been recovered. Original profitable account identity, complete historical fills and a uniquely validated H1 parameter set remain NOT VERIFIED.

Validation: 37 new PAPER tests, 112 existing research tests and 13 existing transport regressions passed, including actual loopback websocket ingress/ACK, entry/exit/re-entry, exact equity/PnL reconciliation, conservative margin, liquidation gaps, H1 causality, corruption and restore. Mobile monitor was opened in real Chromium at 360px: five token cards, position rendering, no horizontal overflow, escaped external text, stale transition and no JS exceptions. Those UI inputs were synthetic test state, not real exchange results. A separate CLI probe verified startup health timeout exits 2 after writing an ERROR snapshot/checkpoint.

Actual Actions run `41681455983`, commit `9557d25`, passed its critical tests and all research regressions, retrieved research evidence and started session `a0d35022-e1a0-4c1d-aa57-5a9cbebfa25f`. Its published state reports ERROR, $500 equity, no positions and no selected tokens. A separate access check confirms the official Bybit response is HTTP 403 with `The Amazon CloudFront distribution is configured to block access from your country`. WebSocket heartbeat with zero subscribed symbols is not a usable live trading feed. GitHub Pages is absent (`has_pages=false`, Pages GET 404); creating it from the runtime failed. These are external blockers, not passing live acceptance checks.

Follow-up diagnostics at evidence branch commit `3c1fc76` confirmed Pages creation fails **403 Resource not accessible by integration** even with the workflow Pages permission. A repository owner must enable the site. The public raw snapshot URL returned HTTP 200 from the remote check, with the expected session/run and zero positions; this verifies snapshot delivery only, not a working mobile Pages site. The finite check successfully requested cancellation of our empty country-blocked first run, and concurrency cancelled a superseded pending run. Subsequent revisions must be distinguished from the initial executed commit when reporting validation. Final local source has 37 critical tests; the first remote source had 31.

The legacy root application suite was previously observed to fail (218 executed; 30 failures, 9 errors, no skips). Its files are unchanged by this branch. New runtime's critical gates and research tests are separate; this does not make the legacy suite green.
