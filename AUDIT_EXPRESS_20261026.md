# Express regression audit — 2026-10-26

Baseline deployed commit: d7e68077a950598932e42c1a7b953094080d0d12.
Service: pandora-testnet-monitor (PAPER_ONLY). No real exchange orders enabled.

Observed dashboard sample includes 86 records and a restored aggregate; it is not a complete comparable backtest. Pump/Dump 20 available individual closes net -0.052 USDT, current local strategy 7 closes +3.897, whale strategy 38 closes +2.288, news 18 closes +27.033. Different periods and legacy logic are mixed. A restored aggregate lacks individual rows, so total historical performance cannot be independently reconstructed here.

Concrete defects and changes:
- LOCAL HYPE/NEAR returned the same +0.12% price lock regardless of peak. Net profits around 0.35 USDT followed from that fixed level minus fees. LOCAL and shared NEWS/PUMP/WHALE protection now retain 50% of observed favorable peak, with the existing fee-buffer floor. Local-extreme and weakening exits remain active. The 50% retention is a conservative policy choice, not an optimized profitability result.
- Shared and LOCAL stops booked a synthetic fill at the stop even when the observed mark had crossed it. They now book the observed mark. Gaps can therefore realize a loss; a stop is not a guaranteed fill.
- Whale distance invalidation required two consecutive widening observations; unchanged ticks reset the counter. An observed ZORA short had reached roughly -56% ROE. Absolute distance invalidation no longer depends on this counter; adverse price moves have a 0.8% boundary before and after target touch. Actual fills may be worse due to gaps/check latency.
- Pump continuation admitted ordinary rebound participation via volume OR z-score OR OI. Require both executed-volume burst >=2 and z-score >=1; existing price/flow/book/direction checks remain. This reduces entries; profitable behavior has not been established by backtest.
- News classified Bitmine share buybacks as bullish ETH purchases. Separate equity buybacks from token buybacks, abstain on the observed substitution headline.

Validation: five new regressions reproduce long/short MFE protection, gap fills, absolute whale invalidation with flat history, equity/token distinction and weak-volume rejection. 113 relevant tests pass across regression, engine, news, regime, accounting, momentum, market data, news recovery and PiQ parser suites; Python compilation and diff checks pass.

Known existing checks: whale-exit test expects 15 warmup samples while baseline risk.py uses 8; runtime audit expects a forced network refresh that the baseline commit removed. Neither failure is caused by these changes. Legacy release tests import deleted whale_v2.py. These are not silently counted as passes.

PiQ current ticker was reproduced returning no_story_links: its absolute tracked story URLs live in JSON cfg.items, unsupported by discovery. Added trusted JSON link discovery and a regression; actual fetched ticker now yields 15 links. X delivery remains unverified realtime. No scanner-latency guarantee is made. Parser fixtures passing do not establish current publisher availability. Funding, spread, slippage and actual exchange liquidation are not modeled by the paper engine. Profitability is unvalidated.

Post-deploy position inspection found ZORA had already touched its target; the absolute adverse boundary now remains active after target touch. A regression reproduces this exact failed-cascade case.
