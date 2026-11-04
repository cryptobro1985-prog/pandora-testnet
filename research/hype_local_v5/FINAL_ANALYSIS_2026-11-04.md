# HYPE H1 Local v5 — research conclusion

Full report is preserved in the project Library as HYPE_H1_LOCAL_ENGINE_V5_FINAL_2026-11-04.md.

## Final causal architecture

STRUCTURAL MATURITY -> RUNNING EXTREME -> OLD-SIDE CLIMAX -> ABSORPTION -> OPPOSITE PRICE RESPONSE -> CONTROL TRANSFER -> SURVIVAL / RETRACEMENT FRACTION -> CONFIRMATION.

Key result: raw executed-flow magnitude is not a robust final discriminator. Across chronological OOS, false locals can have stronger opposite imbalance than true locals. Price response, old-side flow/price efficiency divergence, survival without a new extreme, and retracement as a fraction of the anchor-to-extreme swing are more stable.

The 30-day raw-trade study was re-run at 1-minute and 5-second resolution. The strict H1 L6/K2 target contains 76 alternating structural locals over 2026-10-04..2026-11-02. Fast candidate-level models can detect many true turns close to the extreme, but sequential first-signal precision remains materially lower because earlier corrections can be causally indistinguishable from the terminal reversal.

Therefore the engine must use confidence states rather than one binary local flag:
WATCH -> FORMING -> EARLY_HIGH_CONFIDENCE -> CONFIRMED -> HARD_CONFIRMED.

A new same-side extreme immediately invalidates the current candidate and updates the running extreme.

Forward public microstructure collection is working for HYPEUSDT: L50 order book, trade flow, allLiquidation, and ticker open interest. Those forward-only features must be validated on enough actual H1 reversals before they are promoted into mandatory gates.

Research only; no real order placement.
