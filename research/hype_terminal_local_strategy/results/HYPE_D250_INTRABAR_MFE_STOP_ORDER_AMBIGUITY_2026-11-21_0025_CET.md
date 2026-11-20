# HYPE D250 — OHLC stop execution identifiability audit (2026-11-21 00:25 CET)

Research-only; **source-code audit + deterministic counterexamples**, not matched Bybit execution replay. No detector changes, orders, or production modifications.

## Frozen inputs verified on this branch
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: D250 thresholds unchanged (rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, flow15 < 0.4504731635235635), 71/71 accepted historically, 67 completed opposite locals; causal opposite exit median MFE giveback 61.2%.
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 67 modeled sequential trades, 22 fixed 1% cuts, assumed 0.15% round-trip cost; not independently verified execution.
- `causal_exit_replay_research.py` inspected directly: bar OHLC, a stop test, and `exit_price=min(stop,close)` LONG / `max(stop,close)` SHORT; no quote-side fills or intrabar event order.

## New audit: two equally valid intrabar tapes, different realizable PnL
Entry 100, LONG stop 99, OHLC for next M1 bar O=100, H=102, L=98, C=101. Both event paths satisfy identical OHLC:
- Path A: O100 -> L98 -> H102 -> C101: stop triggers **before** high, cannot count +2% pre-exit MFE.
- Path B: O100 -> H102 -> L98 -> C101: +2% MFE **before** stop, then loss.
The current replay computes +2% MFE on **both**, then exits at 99 (because min(99,101)=99). This inflates stopped-trade pre-exit MFE on Path A and cannot establish MFE giveback or a profit-lock trigger from M1 OHLC alone. With mark-trigger stop, the exact trigger time is also unknowable from OHLC without Mark Price tape.

SHORT symmetric: entry 100, stop 101, O100 H102 L98 C99. Path A O100->H102->L98->C99 stops before 2% favorable low; Path B O100->L98->H102->C99 realizes favorable low before stop. Replay reports +2% MFE for both and stop exit 101.

A second independent ambiguity: if stop is touched but closes through the stop (LONG C=98, SHORT C=102), the code fills at close 98/102; if close recovers (LONG C=101, SHORT C=99), it fills at stop 99/101. Neither is a verified executable price: stop market fill depends on first available post-trigger bid/ask, depth and latency, not bar close. Thus reported stop losses can be either optimistic or pessimistic, and no finite bound follows from OHLC alone.

## Required fail-closed event replay
1. Resolve entry signal availability UTC and actual first executable bid/ask, depth and quantity; apply frozen D250 unchanged.
2. For each position, process chronological event timestamps: Mark trigger -> quote-side/depth executable stop fill; fees, funding, quantity-step, maintenance margin and portfolio capital.
3. Update MFE/MAE **only until actual exit event**, never using a whole bar's high/low after a stop.
4. Opposite H1 local may close only after its actual confirmation availability timestamp, never at its future extreme; if same-timestamp stop/opposite ordering cannot be resolved, label AMBIGUOUS, not winning.
5. For any M1 bar with both potential stop and MFE threshold and missing event ordering, mark `UNRESOLVED_INTRABAR_ORDER`. Do not score profit-lock superiority from such bars.
6. Compare unchanged 67-trade baseline and 0.25%-0.5% risk sizing on identical verified event subset, retaining excluded/missing trade IDs and reasons. Never zero-impute missing L50/Mark/funding.
7. No promotion of previously rejected flow+MFE, K0/K1, ATR trailing or pyramiding overlays without independent forward evidence.

## Result and scope
Two LONG/SHORT OHLC-equivalent counterexample pairs constructed analytically; **four valid intrabar paths**, same OHLC but opposite MFE-before-stop ordering. Existing OHLC replay cannot identify actual MFE, fill price, MTM drawdown or liquidation count. Historical matched fill count in this checkpoint = **0**. Monthly net equity and independent forward results = **not available**. No claim of improved return or zero liquidations.

This is a distinct new audit of the *exit execution and MFE time ordering*, not an entry detector rerun or a snapshot classifier. Next work must locate and join real Bybit event tapes by UTC and trade ID; if unavailable, keep these metrics unknown.
