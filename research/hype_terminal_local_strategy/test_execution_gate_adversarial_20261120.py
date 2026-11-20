"""Adversarial regression for frozen D250 execution gate; research-only.
Run: python -m research.hype_terminal_local_strategy.test_execution_gate_adversarial_20261120
No orders, no model fitting. Tests demonstrate gaps, not verified fills.
"""
from dataclasses import replace
from research.hype_terminal_local_strategy.execution_event_integrity_gate_20261120 import Quote, Trade, validate

def run():
    # 250 minutes after extreme; entry after confirmed local.
    t=Trade("LONG",0,14_000_000,15_000_000,15_000_001,15_000_002,
            100,100,.005,.01,.0015,.02,90,14_500_000,15_120_000)
    q=[Quote(ts,100,100.1,100,2,2,"synthetic")
       for ts in range(15_000_002,15_120_001,60_000)]
    q.append(Quote(15_120_000,100,100.1,100,2,2,"synthetic"))
    # First failure: opposite extreme before entry is still accepted.
    result=validate(t,q)
    assert result["status"]=="QUOTE_PROVENANCE_ONLY", result
    assert t.opposite_extreme_ts_ms<t.entry_fill_ts_ms
    # Second failure: synthetic source is accepted as if quote provenance.
    assert result["status"]=="QUOTE_PROVENANCE_ONLY"
    # Third failure: mark crosses liquidation boundary but status remains permissive.
    crossed=q.copy()
    crossed[1]=replace(crossed[1],mark=89)
    danger=validate(t,crossed)
    assert danger["status"]=="QUOTE_PROVENANCE_ONLY" and danger["observed_mark_liquidation_boundary_cross"],danger
    # Directional SHORT case: future opposite extreme before entry also accepted.
    s=replace(t,side="SHORT",liquidation_mark=110)
    assert validate(s,q)["status"]=="QUOTE_PROVENANCE_ONLY"
    print("4 adversarial checks reproduced; status=QUOTE_PROVENANCE_ONLY is not an execution approval")
if __name__=="__main__":
    run()
