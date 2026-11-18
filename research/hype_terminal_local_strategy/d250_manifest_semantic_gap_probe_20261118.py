#!/usr/bin/env python3
"""Regression probes for the existing D250 manifest gate. Research only.
Run: python research/hype_terminal_local_strategy/d250_manifest_semantic_gap_probe_20261118.py
"""
import importlib.util
from pathlib import Path
p=Path(__file__).with_name("d250_trade_replay_manifest_gate.py")
spec=importlib.util.spec_from_file_location("gate",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
base=dict(trade_id="probe",side="LONG",local_kind="LOW",
 local_extreme_utc="2026-09-01T00:00:00Z",h1_confirmed_utc="2026-09-01T02:00:00Z",
 d250_signal_utc="2026-09-01T04:10:00Z",entry_utc="2026-09-01T04:11:00Z",
 entry_price="100",rev_atr="2.2",trade_ratio5="0.3",flow15="0.4",
 rev_atr_asof_utc="2026-09-01T04:10:00Z",
 trade_ratio5_asof_utc="2026-09-01T04:10:00Z",
 flow15_asof_utc="2026-09-01T04:10:00Z",
 exit_utc="2026-09-01T05:00:00Z",exit_price="101",exit_reason="STOP",
 m1_coverage="COMPLETE",public_trades_coverage="COMPLETE",mark_coverage="COMPLETE")
assert not m.audit(base),m.audit(base)
# Current manifest schema cannot express intervening same-side invalidation.
invalidated=dict(base,same_side_new_extreme_utc="2026-09-01T03:00:00Z")
assert not m.audit(invalidated),m.audit(invalidated)
# Current manifest schema cannot express an opposite local already confirmed before D250.
opposite=dict(base,opposite_confirmed_utc="2026-09-01T03:30:00Z")
assert not m.audit(opposite),m.audit(opposite)
# The gate accepts self-declared COMPLETE without a matching tape reference.
unproven=dict(base,public_trades_sha256="",mark_sha256="",m1_sha256="")
assert not m.audit(unproven),m.audit(unproven)
print("4/4 assertions: current gate accepts base and three semantically unproven rows.")
print("These are regression demonstrations, not historical trades, fills, or PnL.")
