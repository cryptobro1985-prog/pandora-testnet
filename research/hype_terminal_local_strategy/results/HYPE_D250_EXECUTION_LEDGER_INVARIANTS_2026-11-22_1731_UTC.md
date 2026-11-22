# HYPE D250 — event ledger invariants and synthetic execution checks
Date: 2026-11-22 17:31 UTC. Research only. No orders, detector retraining, or production modifications.

## Source read in this iteration
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md (frozen D250, 71 accepted; 67 finalized next opposite locals)
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md (67 completed sequential simulated trades, 22 fixed-cut exits, 0.15% flat round-trip cost)
- HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md (LOW/HIGH asymmetry; opposite control-transfer requirement)
Repository code-search on default branch for HYPE_D250, public_trades, L50 returned no matches. This does not establish that rich files are absent on the requested research branch.

## New execution-accounting finding
The published 0.15% round-trip flat notional cost is not necessarily equal to fees assessed on actual entry AND exit execution notional. Let entry fill P0, exit fill P1, quantity Q, and hypothetical symmetric fee rate f=0.00075 per side (only an illustration consistent with 0.15% when P1=P0).
- Actual cash fees = f*Q*(P0+P1), NOT 0.0015*Q*P0.
- LONG at a 1% adverse fill: P1=0.99*P0, loss including fees = Q*P0*(0.01+0.00075*(1+0.99)) = 0.0114925*entry_notional.
- SHORT at a 1% adverse fill: P1=1.01*P0, loss including fees = Q*P0*(0.01+0.00075*(1+1.01)) = 0.0115075*entry_notional.
- The flat 0.0115 approximation is between them; difference is 0.0000075 of entry notional, or $0.00075 per $100 entry notional. Small, but a useful ledger checksum and direction-specific invariant.
These are deterministic synthetic calculations, NOT Bybit actual fees or fills.

## Executable replay contract (no lookahead)
One immutable row per accepted first signal: episode_id, side, anchor_utc, k2_available_utc, d250_utc, signal_utc=max(k2_available_utc,d250_utc,all_feature_available_utc), invalidation_utc, order_submit_utc, order_ack_utc, fill_utc, fill_price, qty, bid/ask at fill, mark_price, mark_utc, fee, funding_utc/amount, stop_order_utc, stop_trigger_source, stop_trigger_utc, stop_fill_utc/price, opposite_k2_available_utc, exit_submit_utc/fill_utc/price, liquidation_utc/price, final_mark_utc, source_file, source_hash.
- Entry invalid if next opposite local or same-side extension occurs BEFORE first causally available authorization; never reassign a prior false-first.
- LONG fill uses executable ask on entry and bid on exit; SHORT fill uses bid on entry and ask on exit. Public Trades prints alone do not prove orderbook fill.
- Stops trigger on the configured Last/Mark/Index source; liquidation tests mark and venue margin rules separately. If same M1 bar crosses both stop and target, resolve from tick event order or mark UNKNOWN, never select favorable ordering.
- Update cash, position, mark-to-market equity, available margin, open stop-risk and fees/funding at every timestamp; four unfinished D250 signals remain censored/open until an observed exit or a declared end-of-data mark.
- Enforce 0.25%-0.5% initial equity stop-risk per trade and <=1% aggregate; reserve fee, gap and slippage allowances before notional calculation. No capital reuse until fill confirms closure.
- Rejected flow+MFE, K0/K1 and ATR trailing overlays remain rejected. Any new control-transfer rule is research-only until independently frozen/forward-tested.

## Exact synthetic unit checks
For entry price 100, quantity 1, f=0.00075/side:
- LONG exit 99: gross -1; fees 0.14925; net -1.14925.
- SHORT exit 101: gross -1; fees 0.15075; net -1.15075.
- LONG exit 101: gross +1; fees 0.15075; net +0.84925.
- SHORT exit 99: gross +1; fees 0.14925; net +0.85075.
- A stop fill worse than trigger must be accounted at fill, not trigger; unfilled stop cannot be treated as protection.
- MFE must use executable-side exit prices and contemporaneous fees, never the future opposite local extreme.

## Promotion gate
No new historical replay was possible from the accessible per-trade data this iteration. Consequently NO new monthly net equity, MTM DD, fills, liquidation count, or independently forward-tested improvement is claimed. Next actionable work is branch-specific enumeration of raw data files and UTC matching of all 71 accepted first signals; stop before claiming results if timestamps, book or mark data are missing. Preserve frozen D250 thresholds and original baseline unchanged.
