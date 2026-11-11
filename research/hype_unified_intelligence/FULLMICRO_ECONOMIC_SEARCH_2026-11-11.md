# HYPE Full-Micro Economic Strategy Search — 2026-11-11

**Verdict: NO REPRODUCIBLE PROFITABLE STRATEGY VALIDATED.**
Research / paper / shadow only. **REAL ORDERS OFF.**

## Input and causal contract

Repository: `cryptobro1985-prog/pandora-testnet`
Branch: `research/hype-h1-local-v5-oi-microstructure-20261104`

Immutable source: GitHub artifact `HYPE-HISTORY-20260712-20261103-MASTER`
SHA256: `c9d588b5c78d0e72a3073ceb62c7fa100381ebf69df911b22a170171a2653975`

The source declares **116 contract points**, but 28 are future TARGET_EVAL and
2 are metadata. Of the 86 legal causal/quality INPUT points, **83** were
historically observed/derived on the 2026-07-12 to 2026-08-07 full-micro
period. The three missing IDs 111–113 were **not invented or zero-filled**.

On 300-second candidate snapshots:
- 1,252 raw candidate observations.
- 161 impossible/crossed L50 book spreads despite `book_valid=1`.
- 1,091 retained quality-clean independent candidate events.
- 293 feature names per snapshot, 289 causal/numerical derived dimensions
  after removing `age_s` and 10 nonstationary raw price/absolute-size/time
  fields.
- Candidate sequence split: train **646**, development **216**, final
  previously-inspected historical test **219**, purged by 121 minutes.
- Side-specific models: LOW-candidate LONG and HIGH-candidate SHORT.
  **Unconfirmed candidate direction is context, NOT proof of final LOW/HIGH.**

## Economic target and replay

Target for training: within 60 minutes, reach favorable +0.75% **before**
adverse −0.40%. Future candle high/low are used for outcome label only, never
as predictors. Same-minute stop vs target is interpreted as stop first.

Paper execution:
- signal is observed at +300 seconds snapshot;
- model entry at the next fully subsequent 1-minute OPEN;
- 60 minute max hold, adverse underlying stop 0.40%, favorable TP 0.75%;
- 12 basis points round-trip estimated fees/spread/slippage;
- one position at a time, at least 30 minutes cooldown;
- **no actual tick-level executable quote, mark-price or exchange liquidation
  replay**. Numbers are research estimates, not realized trading PnL.

Model selection uses only development data. Already inspected historical test
is never treated as a new untouched OOS. Multi-arm trialing and limited
validation examples increase the chance of a lucky positive outcome.

## Verified GitHub Actions result

Run: https://github.com/cryptobro1985-prog/pandora-testnet/actions/runs/42979620987

Source:
`research/hype_unified_intelligence/fullmicro_economic_candidate_search_v1.py`
Result:
`research/hype_unified_intelligence/FULLMICRO_ECONOMIC_ENTRY_LATEST.json`

| Entry model | Development return / trades | Historical test return / trades |
|---|---:|---:|
| Regularized logistic, price + flow | −0.001% / 6 | **−2.651% / 7** |
| Regularized logistic, all 289 derived | −0.938% / 21 | **−7.354% / 23** |
| ExtraTrees, price + flow | −2.129% / 7 | **−0.720% / 8** |
| ExtraTrees, all 289 derived | −0.680% / 13 | **−2.663% / 12** |
| HistGradientBoosting, price + flow | −1.447% / 5 | **−0.424% / 10** |
| HistGradientBoosting, all 289 derived | −2.006% / 5 | **+0.617% / 9** |

The apparent best historical-test case, +0.617%, was **negative on
development (−2.006%)** and therefore is NOT a validated profitable
or deployable model. This is not permission to leverage the account.

For context, the local baseline taking every 300-second candidate:
- development: 49 trades, **−1.805%**;
- final historical test: 38 trades, **−8.249%**;
both use the same hypothetical target/stop/cost assumptions.

## Consequences

1. Using all 289 computed dimensions did **not** reliably dominate price+flow.
   More features can amplify source errors, nonstationarity and overfitting.
2. LONG and SHORT must remain distinct heads; naive local candidates frequently
   fail to generate profitable future paths even when a reversal appears.
3. No tested configuration shows positive expectancy across both development
   and the final historical July test **with sufficient evidence**.
4. There is no empirical basis to select 25x leverage or a 20% equity margin
   for this model. As with the earlier October risk replay, **live equity
   allocation = 0%** until a robust fresh forward sample with real execution.
5. A new hypothesis must improve **both** entry confirmation and MFE retention,
   with causal quality-clean L50/OI/liq and a separate HOLD/CLOSE/FLIP model.
   It must be compared against price+flow on the SAME candidate/time cohort.

## Next research gates

- Finish independent full-micro dynamic MFE exit replay in
  `research/hype_unified_intelligence/fullmicro_mfe_hold_replay_v1.py`.
  Compare opposing-flow confirmation vs bare recoil trail, never optimizing
  on the previously inspected test.
- Use November 8–10 raw datasets only for **compatibility and data-integrity
  audits**, not to claim untouched OOS (the period was already inspected).
- Gather **genuinely new** forward data for full-micro feature transfer.
- Audit future full L50 orderbook synchronization, OI coverage, liquidation
  completeness and quote age. Missing data must remain missing.
- Only after testable positive edge on underlying should leverage/margin
  optimization be attempted.

No strategy can guarantee daily profit, zero liquidation or unlimited compound
growth. A profitable historical pocket is not a reliable trading system.
