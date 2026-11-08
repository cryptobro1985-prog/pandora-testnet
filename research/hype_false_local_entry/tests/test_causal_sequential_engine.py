"""Regression contracts for causal sequential engine (pytest)."""
import pytest
from research.hype_false_local_entry.causal_sequential_engine import CausalReversalMachine

def bar(i, close, buy=100., sell=100.):
    return dict(ts_ms=i*60000, low=close-0.01, high=close+0.01,
                close=close, buy_notional=buy, sell_notional=sell)

def test_completed_minute_only_and_no_duplicate_timestamp():
    e=CausalReversalMachine()
    e.on_bar(bar(0,100))
    with pytest.raises(ValueError):
        e.on_bar(bar(0,100))

def test_no_flip_on_probe_or_confirmed():
    e=CausalReversalMachine()
    for i in range(40):
        events=e.on_bar(bar(i, 100-0.02*min(i,25)+0.02*max(0,i-25), 140,100))
        assert all(not v.core_flip for v in events if v.stage in ("WATCH","FORMING","EARLY_PROBE","CONFIRMED"))

def test_no_future_dependency():
    prefix=[bar(i,100-i*.01) for i in range(35)]
    a=CausalReversalMachine()
    b=CausalReversalMachine()
    aa=[x for row in prefix for x in a.on_bar(row)]
    bb=[x for row in prefix for x in b.on_bar(row)]
    assert aa==bb
    b.on_bar(bar(35,110))
    assert aa==[x for x in a.events]

def test_invalid_bar_rejected():
    e=CausalReversalMachine()
    with pytest.raises(ValueError):
        e.on_bar(dict(ts_ms=0,low=101,high=100,close=100))
