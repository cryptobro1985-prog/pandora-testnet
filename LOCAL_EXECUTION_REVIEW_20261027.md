# Pandora Local H1 / M15 execution review

## Intended state machine

A causally confirmed H1 local high authorizes SHORT entries; a confirmed H1
local low authorizes LONG entries. Confirmation uses four preceding closed H1
candles and one following closed confirmation candle. The exact turning point
is not known beforehand. A possible opposite extreme pauses entries until its
confirmation; it does not reverse the direction early.

Inside that direction: enter with M15 recovery and fresh aligned executed flow,
exit on confirmed opposing pressure, observe a real counter-direction pullback,
then re-enter only after price and flow resume the H1 direction. Reopening from
an unchanged pre-exit signal is forbidden. Long and short behavior is symmetric.
The opposite confirmed H1 pivot invalidates the position and re-entry watch.

Routine weakening exits follow confirmed opposing pressure even at a loss,
matching the requested exit/pullback/resumption sequence. PnL labels the exit
but no longer vetoes it. Fresh executed counter-flow, M15 pressure and an
observed recoil are still mandatory. H1 invalidation and the liquidation proxy
remain separate exits.

## Changes

- Evaluate all 12 symbols before allocating free margin. Rank eligible signals
  by M15 recovery score, lower adverse score, aligned executed-flow imbalance,
  then observed 60-second notional. Symbol is only a deterministic tie breaker.
  This ranking compares current evidence; it is not a fitted profit forecast.
- Reject missing/nonfinite liquidity observations, incomplete flow coverage,
  stale/future M15 observations and conflicting M15/H1 direction. Require at least
  five observed trades, $100 observed notional and 60 seconds of flow coverage.
- Revalidate current executed flow, H1 anchor, actual entry price and persistent
  re-entry watch inside the position mutation, after ranking.
- Roll back a consumed signal if the position insert conflicts. A failed entry
  cannot silently prevent a later valid attempt.
- Run Local price protection independently every 0.5 seconds using cached marks
  no older than eight seconds, without extra REST requests. Candle bootstrap and
  scan latency no longer determine the cadence of this price protection.
- Persist a newly armed profit floor immediately rather than waiting up to
  30 seconds; a failed persistence attempt remains due for retry.
- Normal Docker startup does not run the legacy history purge. Historical
  position repair is disabled unless explicitly enabled by an operator through
  `PANDORA_RUN_HISTORICAL_REPAIR=1`. Deployment preserves existing trade records.
- Expose candidate ordering and evidence in dashboard JSON and the H1 status
  table. Keep the existing mark-to-market compounding and position sizing.

## Evidence

The deployment revision incorporates the three newer main-branch fixes for
durable candle history, structural H1 confirmation independent of candle color,
and PostgreSQL text-timestamp daily-PnL comparison. With pressure exits allowed
at a loss and historical repair disabled for normal startup, the current
release CI command passes **133 tests**. Fixed 25x PAPER leverage is retained
at the user's request; a Bybit connector is outside this deployment.

The 112-test CI strategy suite plus 15 new allocation/risk/storage regressions
passed: 127 tests. Storage regressions use real PostgreSQL in a disposable
schema and check conflict rollback, subsequent retry, duplicate prevention, and
compounding the next entry's margin without resizing existing positions.
Compilation and `git diff --check` passed. Relevant Local regressions were rerun
after the final entry-price revalidation adjustment: 40 passed.
The new regression modules are included in `.github/workflows/tests.yml`.

The final local application was restarted against its isolated development
database. Both open paper positions were recovered. All 12 native candle
histories became ready, the WebSocket trade feed and independent Local risk
worker were healthy, and `/`, `/api/dashboard` and `/health/risk` returned
successful responses. The full warmup/readiness check completed within 200
seconds. Runtime evidence is saved in
`/workspace/pandora-local/market-review/final-runtime.json`.

Actual Hyperliquid metadata and 120-hour H1 / 12-hour M15 histories were retrieved
for all 12 symbols. Removing unclosed H1 candles left each confirmed direction
and its confirmation time unchanged in all 12 snapshots. Raw snapshots are in
`/workspace/pandora-local/market-review`, outside the checkout. They do not
contain reconstructed historical order flow or a portfolio backtest.

The full legacy discovery suite was already failing before this change,
including tests importing the absent `whale_v2` module. It is not represented as
passing by the focused checks above.
Final full discovery ran 294 tests and reported 28 failures and eight errors;
archived release/storage tests and their shared-state assumptions still need
a separate cleanup. This review does not claim that the full suite is green.

## Limits that matter for interpreting returns

The Local experiment remains PAPER_ONLY with fixed 25x leverage and up to 20%
of current mark-to-market equity as margin per entry. Current exchange metadata
for this universe allows only 3x–10x. Its paper exposure is therefore not directly
reproducible on the exchange. Margin reserved against unrealized gains can
increase exposure before those gains are booked. Existing positions are not
retroactively resized.

Paper fills use observed mids and configured fees. Actual spread, slippage,
funding and exchange liquidation execution are not fully modeled. An observed
price gap can cross a protective floor; an estimated cost floor cannot guarantee
a positive realized exit. Confirmed-pressure exits can realize losses. The
existing loss guard is not a calibrated portfolio drawdown limit.

No untouched out-of-sample portfolio backtest or multi-day forward evaluation
establishes that this candidate ordering improves daily returns. No daily profit
or compounding rate is guaranteed. Production readiness requires the monitor to
report the deployed commit and a successful `/health/risk` check; local tests
alone do not establish deployment success.
