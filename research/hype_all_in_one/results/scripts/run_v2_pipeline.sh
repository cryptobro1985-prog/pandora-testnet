#!/bin/bash
# v2 pipeline after liquidation download; each step writes a marker in /workspace/data/v2_steps/
set -x
cd /workspace/hype_early; export PYTHONPATH=.:/workspace/pandora-testnet; PY=/workspace/venv/bin/python
M=/workspace/data/v2_steps; mkdir -p $M
while pgrep -f fetch_liq.py >/dev/null; do sleep 30; done
grep -q DONE /workspace/data/liq_fetch.log || { echo "fetch not DONE"; $PY fetch_liq.py liquidations >> /workspace/data/liq_fetch.log 2>&1; }
step(){ n=$1; shift; [ -f $M/$n ] && return 0; "$@" > /workspace/data/v2_$n.log 2>&1 && touch $M/$n || { echo "FAIL $n"; exit 1; }; }
step liqfeat $PY liq_features.py
step train env LIQ=1 $PY train_walkforward.py
step aggregate $PY aggregate.py
step atlas $PY atlas.py
step liqalign $PY liq_align.py
step latency $PY latency_audit.py
step compare $PY compare_versions.py
step build $PY build_results_v2.py
step charts $PY charts.py
step pytest $PY -m pytest -rA tests/
echo PIPELINE_DONE
