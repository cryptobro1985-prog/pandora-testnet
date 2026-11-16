"""Regression checks for M1 replay coverage and intrabar entry, research only.
Run: python research/hype_terminal_local_strategy/tests/test_m1_stop_replay_boundary_20261116.py
Expected on current module: two known defects reproduced; no real fills inferred.
"""
import importlib.util
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"m1_stop_order_ambiguity_replay_20261116.py"
spec=importlib.util.spec_from_file_location("m1",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def bar(t,lo=99.5,hi=101):
    return dict(ts_ms=t,open=100,high=hi,low=lo,close=100)
def episode(**kw):
    d=dict(id="test",side="LONG",entry_ts_ms=0,entry_price=100,stop_price=99,exit_ts_ms=120000,exit_price=100,bars=[bar(0),bar(60000)])
    d.update(kw);return d
# Pre-entry minute's low must NOT be used as a post-entry stop.
r=m.replay(episode(entry_ts_ms=30000,bars=[bar(0,lo=98),bar(60000)]))
assert r["status"]=="NO_STOP_TOUCH_IN_M1",r
print("REPRODUCED: entry inside first M1 bar silently accepted despite unknown post-entry path")
# Coverage from entry to exit must include all minutes; current module can accept an incomplete tail.
r=m.replay(episode(exit_ts_ms=180000,bars=[bar(0),bar(60000)]))
assert r["status"]=="NO_STOP_TOUCH_IN_M1",r
print("REPRODUCED: missing final minute incorrectly accepted as no stop touch")
# No real execution/fill proof in this test.
print("PASS: two known boundary defects reproduced; not an execution replay")
