# HYPE D250: execution-evidence gate regression — 2026-11-17 12:28 CET

Research only. Frozen D250 thresholds unchanged; no retraining, production modification or orders.

## Sources inspected in target branch
- `research/hype_terminal_local_strategy/d250_trade_replay_manifest_gate.py`
- `research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `research/hype_terminal_local_strategy/results/HYPE_D250_ENTRY_FILL_CAUSAL_GAP_AUDIT_2026-11-17_1130_CET.md`

## Concrete new execution check
Implemented and ran a separate **local** Python evidence-manifest audit (not deployed) and eight synthetic regression cases: valid STOP manifest; same-timestamp signal/submission rejection; SHORT stop on wrong side; missing stop-fill event ID; missing independently verified tape; stop triggered before entry; valid confirmed opposite-local exit; same-timestamp opposite confirmation/exit rejection. Result: **8/8 passed** (Python unittest, 2026-11-17). This proves only test-case behavior, not market replay or that supplied evidence is authentic.

Required evidence columns include feature availability, signal emission, order submission, exchange acknowledgment, first fill, stop trigger basis/time, stop order ID, stop fill event ID, quantities/VWAP, and separate event/mark/order tape SHA-256 digests. Equal acknowledgment/fill timestamps require independently verified event ordering. A SHA-256 string alone does not prove its contents; provenance must be independently checked. Stop fills and opposite-local exits must be ordered after entry, and exit fill after confirmed opposite local.

## Quantitative consequence of original stop budget
Frozen 1% adverse-price stop + 0.15% assumed round-trip costs + 0.10% *scenario* execution allowance = 1.25% loss per notional at modeled stop. For 0.25% equity stop-risk: 0.20x notional/equity; for 0.50%: 0.40x. A further 0.5% adverse gap raises modeled equity losses to 0.35% and 0.70%, respectively. Not a liquidation or risk guarantee. The original 5x baseline remains unchanged and must be reported separately.

## Research status
No per-trade UTC ledger, exchange-level stop-fill events, mark path, or verified matched L50/Public Trades tape was obtained in this iteration. **67-trade event replay remains blocked**. No new empirical monthly equity, closed/MTM DD, fills, liquidations, or MFE captured. Do not promote rejected overlays or claim forward validation. The next iteration must recover actual ledger and exchange event artifacts and verify hashes/content before running baseline-versus-conservative comparisons on the same chronological sample.

## Local reproducibility
Local files created/tested in this run: `d250_execution_evidence_gate.py`, `test_d250_execution_evidence_gate.py`. Command: `python -m unittest -v test_d250_execution_evidence_gate.py`. These files are **not** claimed to be in GitHub; this checkpoint records their test outcome and evidence schema.
