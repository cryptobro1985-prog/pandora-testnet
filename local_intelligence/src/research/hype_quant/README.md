# HYPE Quant Learner v1

Research-only online learner for HYPEUSDT. It never places orders.

## Why Python

The market collector is already Python and the research bottleneck is causal
learning/validation, not transport latency. Python gives direct access to River
for incremental learning/drift detection, NumPy/Polars/PyTorch if later needed,
and Bybit websocket tooling. A Rust transport layer can be introduced later only
if measured latency/CPU proves Python is the bottleneck.

## Causal loop

1. Read the same HYPE 1s microstructure + 1m structural context produced by
   `research/hype_local_v5`.
2. At time t, build features using information available at or before t.
3. Predict 1m/3m/5m/10m/15m/30m outcomes.
4. Store the prediction without learning from its future.
5. When the horizon matures, label return, max-up/MFE and max-down/MAE.
6. Score champion and challenger on the prediction made before the label existed.
7. Update only challenger.
8. Promote challenger only after enough forward labels and positive net
   expectancy after modeled costs.
9. Keep a causal Pattern Memory of matured similar states.

## Action research

The model scores FLAT/LONG/SHORT plus a simulated leverage and margin-fraction
grid. These are counterfactual research actions, not orders.

The config contains an aspirational +100% daily return benchmark because that is
the research target. It is lexicographically subordinate to survival:
simulated liquidation/ruin avoidance -> drawdown control -> positive net
expectancy -> MFE capture -> aspirational return target.

No code in this package authenticates to Bybit, accesses private endpoints, or
submits an order.

## Anti-leakage

- predictions are made before labels are known;
- new states cannot train themselves;
- gaps >10s invalidate pending path labels, because MFE/MAE would otherwise be
  understated;
- historical compact packages are progressive-replayed and explicitly marked
  bootstrap/discovery, never final forward evidence;
- champion is frozen while challenger learns;
- future live data is the forward judge.

## Files

- `learner.py`: online models, Pattern Memory, action/risk scorer.
- `features.py`: causal feature merger.
- `bootstrap_compact.py`: progressive replay of HYPE110-COMPACT-v1 history.
- `live_daemon.py`: tails the existing collector in real time.
- `test_self.py`: synthetic no-future-leak smoke test.
- `config.json`: objective, costs, risk and action-space contract.
