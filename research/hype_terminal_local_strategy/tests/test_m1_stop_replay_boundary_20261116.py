"""Regression checks for M1 replay coverage and intrabar entry, research only.
Run: python research/hype_terminal_local_strategy/tests/test_m1_stop_replay_boundary_20261116.py
Expected: boundary defects blocked; no real fills inferred.
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
assert r["status"]=="UNKNOWN_ENTRY_INTRABAR",r
print("PASS: entry inside first M1 bar fails closed")
# Coverage from entry to exit must include all minutes; current module can accept an incomplete tail.
r=m.replay(episode(exit_ts_ms=180000,bars=[bar(0),bar(60000)]))
assert r["status"]=="UNKNOWN_COVERAGE",r
print("PASS: missing final minute fails closed")
# No real execution/fill proof in this test.
print("PASS: boundary cases blocked; not an execution replay")

# Discontinuity outside the actual holding window must not invalidate a complete interval.
r=m.replay(episode(bars=[bar(-180000),bar(0),bar(60000),bar(240000)]))
assert r["status"]=="NO_STOP_TOUCH_IN_M1",r
print("PASS: out-of-window archival gaps ignored")
# In a stop-touch candle, favorable high can occur after the stop: not captured MFE.
r=m.replay(episode(bars=[bar(0,lo=98,hi=110),bar(60000)]))
assert r["status"]=="STOP_TOUCHED_FILL_UNKNOWN",r
assert r["mfe_upper_bound"] is None,r
assert r["pre_stop_bar_favorable_upper_bound"]>=0.1-1e-9,r
print("PASS: stop-bar favorable extreme not misrepresented as realized MFE")
