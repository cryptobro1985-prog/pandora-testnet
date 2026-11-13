# HYPE frozen stop/gap conservative risk frontier — 2026-11-13
Research only; no orders, detector training, production change, or real tick replay.

Source files verified in branch: H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md (71/71, 50/50 OOS, 22.4% coverage, 61.2% median MFE giveback); HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md (67 trades, 22 stops, 3x $531.16/DD18.56%, 5x $1308.86/DD29.36%); HYPE_EVERY_LOCAL_ROBUST_STRATEGY_2026-11-12.md (322 states not predictions, 411 trades). Earlier conversation misreported the 5x final balance as $531.16; that belongs to 3x.

Formula f=0.00075 fee per side; stop s; extra gap g; LONG loss/notional=s+g+f*(2-s-g); SHORT=s+g+f*(2+s+g). Conservative exposure = equity risk / SHORT loss. Values are scenario-only, NOT measured Bybit slippage.

CSV columns: stop_fraction,gap_fraction,long_loss_per_notional,short_loss_per_notional,max_equity_exposure_at_0.25pct_risk,max_equity_exposure_at_0.5pct_risk
0.010000,0.000000,0.011493,0.011508,0.217250,0.434499
0.010000,0.005000,0.016489,0.016511,0.151412,0.302824
0.010000,0.010000,0.021485,0.021515,0.116198,0.232396
0.010000,0.020000,0.031477,0.031523,0.079308,0.158617
0.031400,0.000000,0.032876,0.032924,0.075933,0.151867
0.031400,0.005000,0.037873,0.037927,0.065916,0.131831
0.031400,0.010000,0.042869,0.042931,0.058233,0.116466
0.031400,0.020000,0.052861,0.052939,0.047225,0.094449

At 25x isolated, 4% initial margin fraction is NOT liquidation distance: maintenance margin and mark price matter. A 3.14% structural stop plus 1% gap moves 4.14% against the position, potentially liquidating before fill. Reducing account notional alone does not cure isolated liquidation geometry.

Next: recover exact 67-trade timestamp ledger and matched Public Trades/mark/L50/funding to test original 3x/5x and conservative 0.25/0.5% risk on same sequential sample. Separate LOW/LONG and HIGH/SHORT; measure fills, stop gaps, liquidation, closed/MTM DD, net monthly equity, MFE bounds, forward. No oracle opposite-extreme exits; prior failed trailing overlays stay rejected. This checkpoint has no new empirical PnL, fill, or liquidation result.
