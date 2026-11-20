# D250 stop-event replay: executable-price and causality audit — 2026-11-20 02:30 CET

Research-only. No detector retraining, threshold changes, production edits, or orders.

## Source inspection
Read frozen `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, and `quote_event_stop_replay_research.py` at the requested branch.

## New code-level finding
`replay()` returns `HYPOTHETICAL_TOP_OF_BOOK` for a stop when a single quote event crosses the threshold, using its bid (LONG) / ask (SHORT). This is **not an executable stop-market fill**: it does not consume L50 depth, does not model order latency or size, and does not know whether Bybit's configured trigger was Last/Mark/Index. Its `mark` field is only returned at exit; it is never checked against liquidation before exit. Therefore a zero liquidation count cannot be inferred from its result.

`opposite_available` is a boolean attached to a quote event, with no attached source K2 confirmation timestamp or feed latency. It cannot by itself prove that opposite-local availability preceded the fill. The code deliberately returns `ORDER_UNRESOLVED` if stop and opposite become true at the same quote event, which is correct uncertainty handling but leaves trade outcome unresolved.

## Concrete numerical execution counterexample (NOT historical Bybit)
LONG entry VWAP 100.00; 1% stop trigger 99.00; bid jumps directly to 97.00. With 0.15% round-trip cost approximation, nominal risk sizing at 0.5% equity using stop+cost gives notional / equity = 0.005 / 0.0115 = 0.4347826. Realized loss under this jump = 0.4347826 * (0.03 + 0.0015) = **1.369565% of equity**, or **2.73913 times** the nominal 0.5% budget. This excludes depth-driven slippage, funding, liquidation and mark divergence. The same mechanism holds for a SHORT with an upward gap. An order-book quote is not proof that the full quantity fills at that quote.

With 2 percentage points *pre-reserved* adverse gap, notional/equity = 0.005/(0.01+0.02+0.0015)=0.1587302; loss under the stated 3% adverse price move plus 0.15% fee = 0.5% equity. This only protects the **assumed** gap magnitude, not larger tails.

## Research implications / gates
1. Preserve baseline 67-trade reported simulated outcomes unchanged; do not recalculate a fictitious historical equity curve from aggregates.
2. For each matched trade, require timestamped actual local K2 availability, quote bid/ask, mark-price path, L50 executable depth, fee tiers, funding timestamps, trigger source, and latency; missing intervals => UNKNOWN, not zero slippage or zero liquidation.
3. Stop event sequence: trigger-source crossing -> order submission latency -> depth-consumed execution (or unfilled) -> fees; independently mark-based liquidation check along entire open interval.
4. Maintain two distinct labels: `triggered_stop` versus `filled_stop`; report unresolved fills explicitly.
5. On exactly identical chronological trade opportunities, compare frozen 1%-cut baseline with 0.25% and 0.5% risk-sized alternatives; stop-risk sum <=1% equity, no reuse of reserved capital. Treat 1%-cut and structural stop as different policies, not interchangeable.
6. Do not promote previously rejected MFE exits based on this diagnostic.

## Verification status
New analysis: source-level replay semantics + exact arithmetic counterexample. **0 new matched real executions**, **0 historical stop fills verified**. Monthly net equity, MTM drawdown, liquidation count, actual MFE capture and independent forward execution remain UNKNOWN. No claims of realized performance or safety.
